"""LLM-as-judge scoring, plus the calibration numbers that make it reportable.

Two jobs:

1. `rubric_score` — score a note against a fixed clinical documentation rubric.
2. `claim_entailment` — split the note into atomic claims and ask, per claim,
   whether the transcript supports it, returning the supporting span. This is
   the precursor to the Phase 3 in-pipeline verifier: the same call shape, run
   offline as a metric first so we can measure how well it works before we let
   it gate generation.

An unvalidated judge is an opinion, not a metric, so `agreement()` reports how
closely judge scores track the human scores on cases that carry one. Report the
judge number *with* its agreement figure or not at all.
"""

from __future__ import annotations

import json
import os
from typing import Any

try:
    from groq_client import JUDGE_MODEL, chat_json, resolve_role
except ImportError:  # pragma: no cover - the harness runs without it
    JUDGE_MODEL = ""
    chat_json = None  # type: ignore
    resolve_role = None  # type: ignore

RUBRIC = {
    "faithfulness": "Every clinical statement is supported by the transcript. No invented findings, vitals, medications, or history.",
    "completeness": "Clinically significant information present in the transcript reaches the note.",
    "section_discipline": "Content sits in the right SOAP section: no interpretation in S or O, no raw history in A.",
    "clinical_reasoning": "The assessment follows from the subjective and objective content, with reasoning proportionate to the evidence.",
    "actionability": "The plan addresses the assessment, is specific, and includes follow-up or safety-netting where warranted.",
}

_RUBRIC_PROMPT = """You are evaluating a clinical SOAP note against the transcript it was generated from.

Score each criterion from 1 to 5, where 1 is unacceptable and 5 is what an experienced clinician would have written.
Judge only against the transcript. Do not reward detail the transcript does not support — that is a faithfulness failure, not thoroughness.

Return ONLY valid JSON of the form:
{"scores": {"<criterion>": {"score": <1-5>, "justification": "<one sentence>"}}}

Criteria:
"""

_ENTAILMENT_PROMPT = """You are checking a clinical note for statements the transcript does not support.

Split the note into atomic clinical claims. For each claim, decide:
- "supported": the transcript states it or directly implies it.
- "unsupported": the transcript does not contain it.
- "contradicted": the transcript states something incompatible with it.

Standard clinical framing that asserts nothing about the patient (section headings,
"not documented in transcript", "pending examination") should be skipped, not scored.

Return ONLY valid JSON of the form:
{"claims": [{"claim": "<text>", "verdict": "supported|unsupported|contradicted", "evidence": "<exact transcript quote, or empty>"}]}
"""


class JudgeUnavailable(RuntimeError):
    """Raised when no judge backend is configured. Callers skip the metric."""


def _complete(system: str, user: str, *, max_tokens: int) -> dict[str, Any]:
    """Judge call, routed through the shared model access point.

    This used to hold its own Groq client, which meant it missed the retry
    classification, the token accounting and the provider selection that every
    other model call gets — and its model name defaulted to one Groq had
    decommissioned, so an unconfigured judge run 404'd rather than saying it was
    misconfigured. Going through `chat_json` is what makes
    `EVAL_JUDGE_PROVIDER` able to point the judge at a different model from the
    one that wrote the note.
    """
    if chat_json is None or resolve_role is None:
        raise JudgeUnavailable("The model client is unavailable; install `groq` and `openai`.")
    try:
        provider, _ = resolve_role("judge")
    except ValueError as exc:
        raise JudgeUnavailable(str(exc)) from exc
    if not os.getenv(provider.key_env):
        raise JudgeUnavailable(f"{provider.key_env} is not set, so the judge cannot run.")

    try:
        return chat_json(system, user, max_tokens=max_tokens, temperature=0.0, role="judge")
    except (json.JSONDecodeError, EnvironmentError) as exc:
        raise JudgeUnavailable(str(exc)) from exc


def _note_as_text(note: dict[str, str] | str) -> str:
    if isinstance(note, str):
        return note
    return "\n\n".join(f"{key.upper()}:\n{value}" for key, value in note.items() if value)


def rubric_score(note: dict[str, str] | str, transcript: str) -> dict[str, Any]:
    """Rubric scores plus a 0-100 aggregate (unweighted mean of the criteria)."""
    criteria = "\n".join(f"- {name}: {description}" for name, description in RUBRIC.items())
    parsed = _complete(
        _RUBRIC_PROMPT + criteria,
        f"Transcript:\n{transcript}\n\nNote:\n{_note_as_text(note)}",
        max_tokens=900,
    )

    scores = parsed.get("scores", {})
    values = [
        float(entry.get("score", 0))
        for entry in scores.values()
        if isinstance(entry, dict) and entry.get("score") is not None
    ]
    aggregate = (sum(values) / len(values)) * 20 if values else 0.0
    return {
        "judge_score": round(aggregate, 2),
        "criteria": scores,
        "judge_model": JUDGE_MODEL,
    }


def claim_entailment(note: dict[str, str] | str, transcript: str) -> dict[str, Any]:
    """Per-claim support check. `judge_hallucination_rate` is the share of
    scored claims that are unsupported or contradicted."""
    parsed = _complete(
        _ENTAILMENT_PROMPT,
        f"Transcript:\n{transcript}\n\nNote:\n{_note_as_text(note)}",
        max_tokens=1600,
    )

    claims = [claim for claim in parsed.get("claims", []) if isinstance(claim, dict)]
    verdicts = [str(claim.get("verdict", "")).lower() for claim in claims]
    unsupported = sum(1 for verdict in verdicts if verdict in ("unsupported", "contradicted"))
    total = len(verdicts)

    return {
        "judge_hallucination_rate": round(unsupported / total, 4) if total else 0.0,
        "judge_claims_total": float(total),
        "judge_claims_unsupported": float(unsupported),
        "judge_claims_contradicted": float(sum(1 for v in verdicts if v == "contradicted")),
        "unsupported_claims": [
            claim for claim, verdict in zip(claims, verdicts)
            if verdict in ("unsupported", "contradicted")
        ],
    }


def agreement(judge_scores: list[float], human_scores: list[float]) -> dict[str, float]:
    """How far the judge is from the humans it is standing in for.

    Reports mean absolute error and Spearman rank correlation. Rank correlation
    matters more than MAE here: a judge that is consistently 8 points generous
    but ranks notes correctly is still useful for regression detection.
    """
    pairs = [
        (judge, human)
        for judge, human in zip(judge_scores, human_scores)
        if judge is not None and human is not None
    ]
    if len(pairs) < 2:
        return {"judge_agreement_n": float(len(pairs)), "judge_mae": -1.0, "judge_spearman": -2.0}

    judged = [pair[0] for pair in pairs]
    human = [pair[1] for pair in pairs]
    mae = sum(abs(a - b) for a, b in pairs) / len(pairs)

    return {
        "judge_agreement_n": float(len(pairs)),
        "judge_mae": round(mae, 3),
        "judge_spearman": round(_spearman(judged, human), 4),
    }


def _rank(values: list[float]) -> list[float]:
    """Average ranks, so ties do not distort the correlation."""
    order = sorted(range(len(values)), key=lambda index: values[index])
    ranks = [0.0] * len(values)
    position = 0
    while position < len(order):
        end = position
        while end + 1 < len(order) and values[order[end + 1]] == values[order[position]]:
            end += 1
        shared = (position + end) / 2 + 1
        for index in range(position, end + 1):
            ranks[order[index]] = shared
        position = end + 1
    return ranks


def _spearman(left: list[float], right: list[float]) -> float:
    left_ranks, right_ranks = _rank(left), _rank(right)
    n = len(left_ranks)
    mean_left = sum(left_ranks) / n
    mean_right = sum(right_ranks) / n
    covariance = sum((a - mean_left) * (b - mean_right) for a, b in zip(left_ranks, right_ranks))
    variance_left = sum((a - mean_left) ** 2 for a in left_ranks) ** 0.5
    variance_right = sum((b - mean_right) ** 2 for b in right_ranks) ** 0.5
    if variance_left == 0 or variance_right == 0:
        return 0.0
    return covariance / (variance_left * variance_right)
