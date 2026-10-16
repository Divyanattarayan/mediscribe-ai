"""Run the pipeline over a suite of cases and score the output.

Stages are opt-in so the expensive parts are only paid for when wanted:

* `asr`   — transcribe `audio_path` and score against `reference_transcript`.
            Needs the Whisper model; skipped for text-only datasets.
* `note`  — run entity extraction + clinical extraction + SOAP generation over
            the transcript (the reference one when available, so note quality
            is measured independently of ASR error).
* `judge` — LLM rubric and claim-entailment scoring. Needs GROQ_API_KEY.

Offline metrics (WER, medical-term error rate, entity F1, lexical grounding)
always run when their inputs exist, which is what makes `--stages note` usable
as a CI gate without any network beyond generation itself.

Heavy imports are deliberately deferred into the functions that need them: the
Whisper and scispaCy models take tens of seconds to load, and a metrics-only
re-scoring run should not pay for either.
"""

from __future__ import annotations

import json
import time
import traceback
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Sequence

from eval.audio_source import local_audio
from eval.metrics import asr as asr_metrics
from eval.metrics import entities as entity_metrics
from eval.metrics import coverage as coverage_metrics
from eval.metrics import grounding as grounding_metrics
from eval.metrics import judge as judge_metrics
from eval.schema import CaseResult, EvalCase

RESULTS_DIR = Path(__file__).resolve().parent / "results"

STAGES = ("asr", "note", "judge")


@dataclass
class RunConfig:
    suite: str
    stages: tuple[str, ...] = ("note",)
    limit: int | None = None
    # Skips the first N cases. Exists so a setting tuned on some cases can be
    # confirmed on ones it has never seen — tuning and testing on the same
    # audio is how a dev-set result gets mistaken for a real improvement.
    offset: int = 0
    label: str = ""
    results_dir: Path = RESULTS_DIR
    # None means audio is fetched, transcribed and deleted per case. Set a
    # directory to keep downloads for repeat runs.
    audio_cache_dir: Path | None = None
    style_profile: dict[str, Any] = field(default_factory=dict)


def run_suite(cases: Sequence[EvalCase], config: RunConfig) -> dict[str, Any]:
    remaining = list(cases)[config.offset:]
    selected = remaining[: config.limit] if config.limit else remaining
    started = time.perf_counter()

    # What a run costs is a planning input, not a curiosity: the free tiers are
    # the binding constraint on how much of PriMock57 can be evaluated, and
    # "will this finish inside today's quota" is unanswerable without a
    # per-provider figure from a previous run.
    try:
        from groq_client import reset_usage, usage_by_provider
    except ImportError:  # pragma: no cover - metrics-only runs need no client
        reset_usage = usage_by_provider = None  # type: ignore
    if reset_usage is not None:
        reset_usage()

    results: list[CaseResult] = []
    for index, case in enumerate(selected, start=1):
        print(f"[{index}/{len(selected)}] {case.case_id}")
        results.append(_run_case(case, config))

    report = {
        "suite": config.suite,
        "label": config.label,
        "offset": config.offset,
        "stages": list(config.stages),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "case_count": len(results),
        "failed_cases": [r.case_id for r in results if r.error],
        "runtime_seconds": round(time.perf_counter() - started, 2),
        "aggregate": aggregate_metrics(results),
        "cases": [result.to_dict() for result in results],
    }
    if "asr" in config.stages:
        report["asr_config"] = asr_config()
    if usage_by_provider is not None:
        usage = usage_by_provider()
        report["token_usage"] = usage
        if usage and selected:
            report["token_usage_per_case"] = {
                name: {key: round(value / len(selected), 1) for key, value in counts.items()}
                for name, counts in usage.items()
            }
    report["aggregate"].update(_judge_agreement(selected, results))
    return report


def _run_case(case: EvalCase, config: RunConfig) -> CaseResult:
    result = CaseResult(case_id=case.case_id, source=case.source)
    try:
        if "asr" in config.stages and (case.audio_path or case.audio_url):
            with local_audio(case.audio_path, case.audio_url, cache_dir=config.audio_cache_dir) as path:
                result.hypothesis_transcript = _transcribe(str(path))
            if case.reference_transcript:
                result.metrics.update(
                    asr_metrics.word_error_rate(
                        case.reference_transcript, result.hypothesis_transcript
                    ).as_metrics()
                )
                # Reported alongside raw WER, never instead of it. Verbatim
                # references include the hesitation sounds Whisper is trained to
                # drop, so raw WER answers "does this match the transcript" while
                # this answers "did it capture what was said".
                result.metrics.update(
                    asr_metrics.word_error_rate(
                        case.reference_transcript, result.hypothesis_transcript,
                        strip_disfluencies=True,
                    ).as_metrics(prefix="wer_fluent")
                )
                result.metrics.update(
                    asr_metrics.medical_term_error_rate(case.reference_transcript, result.hypothesis_transcript)
                )

        # Note quality is measured against the *reference* transcript when we
        # have one, so ASR error does not silently masquerade as a generation
        # defect. Falls back to our own transcript when it does not.
        transcript = case.reference_transcript or result.hypothesis_transcript
        if "note" in config.stages and transcript:
            note, entities, extras = _generate_note(transcript, case, config)
            result.hypothesis_note = note
            result.hypothesis_entities = entities
            result.metrics.update(extras.pop("metrics", {}))
            result.details.update(extras)

            if case.reference_entities:
                result.metrics.update(entity_metrics.entity_scores(case.reference_entities, entities))
                result.metrics.update(entity_metrics.entity_scores(case.reference_entities, entities, strict=True))
                result.metrics.update(entity_metrics.assertion_scores(case.reference_entities, entities))
                result.details["entities"] = entity_metrics.missed_and_spurious(case.reference_entities, entities)
                assertion_errors = entity_metrics.assertion_errors(case.reference_entities, entities)
                if assertion_errors:
                    result.details["assertion_errors"] = assertion_errors

            # Coverage against clinician-authored findings, reported alongside
            # the score the clinician's own note achieves on the same items —
            # a coverage figure without that ceiling is uninterpretable.
            if case.reference_items and "judge" in config.stages:
                from eval.primock_checklists import ChecklistItem

                items = [
                    ChecklistItem(text=entry["text"], criticality=entry.get("criticality", "critical"))
                    for entry in case.reference_items
                ]
                result.metrics.update(coverage_metrics.judged_coverage_scores(items, note))
                if case.reference_note:
                    reference_text = " ".join(str(v) for v in case.reference_note.values() if v)
                    result.metrics.update(coverage_metrics.ceiling_scores(items, reference_text))

            result.metrics.update(grounding_metrics.grounding_scores(note, transcript, case.reference_note))
            result.details["grounding"] = grounding_metrics.grounding_details(note, transcript, case.reference_note)

        if "judge" in config.stages and result.hypothesis_note and transcript:
            try:
                rubric = judge_metrics.rubric_score(result.hypothesis_note, transcript)
                result.metrics["judge_score"] = rubric["judge_score"]
                result.details["judge_criteria"] = rubric["criteria"]

                entailment = judge_metrics.claim_entailment(result.hypothesis_note, transcript)
                result.details["unsupported_claims"] = entailment.pop("unsupported_claims", [])
                result.metrics.update(entailment)
            except judge_metrics.JudgeUnavailable as exc:
                result.details["judge_skipped"] = str(exc)

    except Exception as exc:  # one bad case must not abandon the run
        result.error = f"{type(exc).__name__}: {exc}"
        result.details["traceback"] = traceback.format_exc()
        print(f"    failed: {result.error}")

    return result


def _transcribe(audio_path: str) -> str:
    from transcription import transcribe_audio_realtime

    text, _duration = transcribe_audio_realtime(audio_path)
    return text


def asr_config() -> dict[str, Any]:
    """The decoding settings a run used.

    Recorded in the report because every one of them is switchable, so a WER
    figure without them is unattributable — and comparing two runs that used
    different settings without knowing it is worse than having no number.
    """
    try:
        import transcription
    except Exception:  # pragma: no cover - ASR stage not in use
        return {}

    return {
        name: getattr(transcription, name)
        for name in (
            "WHISPER_MODEL", "WHISPER_COMPUTE_TYPE", "WHISPER_BEAM_SIZE",
            "WHISPER_VAD_FILTER", "WHISPER_CONDITION_ON_PREVIOUS",
            "WHISPER_WORD_TIMESTAMPS", "WHISPER_INITIAL_PROMPT",
        )
        if hasattr(transcription, name)
    }


def _generate_note(
    transcript: str,
    case: EvalCase,
    config: RunConfig,
) -> tuple[dict[str, str], list[dict[str, Any]], dict[str, Any]]:
    from clinical_extraction import extract_clinical_representation
    from clinical_facts import build_fact_table, fact_table_summary
    from entity_extraction import extract_medical_entities
    from soap_generator import generate_soap_note

    extracted = extract_medical_entities(transcript)
    representation = extract_clinical_representation(
        transcript, extracted["categorized"], case.encounter_type
    )
    fact_table = build_fact_table(transcript, extracted["entities"])
    soap = generate_soap_note(
        transcript, extracted["categorized"], representation,
        config.style_profile or None, fact_table,
    )
    note = {section: str(soap.get(section, "")) for section in ("subjective", "objective", "assessment", "plan")}

    # The pipeline's own verification, surfaced as a metric. This is the number
    # that supersedes the lexical `hallucination_rate` proxy: it counts claims
    # the transcript does not support, not vocabulary the transcript lacks.
    extras: dict[str, Any] = {"fact_table_summary": fact_table_summary(fact_table)}
    verification = soap.get("verification") or {}
    if verification.get("ran"):
        extras["metrics"] = {
            "pipeline_unsupported_claim_rate": verification.get("unsupported_rate", 0.0),
            "pipeline_claims_total": float(verification.get("claims_total", 0)),
            "pipeline_claims_unsupported": float(verification.get("claims_unsupported", 0)),
        }
        extras["problem_claims"] = verification.get("problem_claims", [])
    else:
        # Otherwise a fallback-to-lexical case is indistinguishable in the
        # report from one that never attempted verification at all — exactly
        # the failure mode `judge_skipped` exists to avoid for the judge metric.
        extras["verification_skipped"] = verification.get("error", "unknown reason")
    extras["quality_report"] = soap.get("quality_report", {})
    return note, extracted["entities"], extras


def aggregate_metrics(results: Iterable[CaseResult]) -> dict[str, Any]:
    """Mean of every metric, each with the count it was computed over.

    Metrics are averaged only across the cases that actually produced them, and
    the count travels with the value — an average over three cases and one over
    fifty must not read the same on a report.
    """
    sums: dict[str, float] = {}
    counts: dict[str, int] = {}
    for result in results:
        for name, value in result.metrics.items():
            if value is None or value < 0:  # sentinel for "not applicable"
                continue
            sums[name] = sums.get(name, 0.0) + float(value)
            counts[name] = counts.get(name, 0) + 1

    return {
        name: {"mean": round(total / counts[name], 4), "n": counts[name]}
        for name, total in sorted(sums.items())
    }


def _judge_agreement(cases: Sequence[EvalCase], results: Sequence[CaseResult]) -> dict[str, Any]:
    by_id = {case.case_id: case for case in cases}
    judged, human = [], []
    for result in results:
        case = by_id.get(result.case_id)
        score = result.metrics.get("judge_score")
        if case is None or case.human_score is None or score is None:
            continue
        judged.append(float(score))
        human.append(float(case.human_score))

    if not judged:
        return {}
    return {
        name: {"mean": value, "n": len(judged)}
        for name, value in judge_metrics.agreement(judged, human).items()
    }


def save_report(report: dict[str, Any], results_dir: Path = RESULTS_DIR) -> Path:
    results_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    slug = report["label"] or report["suite"]
    path = results_dir / f"{stamp}_{slug}.json"
    path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


# Metrics where a *higher* number is worse. Used by the regression gate so it
# does not have to guess from the metric name.
LOWER_IS_BETTER = {
    "pipeline_unsupported_claim_rate",
    "wer",
    "wer_fluent",
    "medical_term_error_rate",
    "hallucination_rate",
    "omission_rate",
    "judge_hallucination_rate",
    "judge_mae",
}

# Diagnostics, not quality. These are raw counts that explain the rates above —
# how many terms were in the note, how many entities were matched — and they
# move whenever the case set changes. Gating on them produces nonsense in both
# directions: a drop in `hallucinated_term_count` is an improvement, and a drop
# in `entity_lenient_reference` just means a smaller suite.
INFORMATIONAL = {
    "assertion_matched_entities",
    "checklist_items",
    "critical_items",
    "ceiling_checklist_items",
    "ceiling_critical_items",
    # The human ceiling is context for the score, not a target to beat.
    "ceiling_checklist_coverage",
    "ceiling_critical_item_coverage",
    "pipeline_claims_total",
    "pipeline_claims_unsupported",
    "generated_term_count",
    "hallucinated_term_count",
    "medical_terms_in_reference",
    "medical_terms_missed",
    "medical_terms_spurious",
    "omitted_term_count",
    "reference_term_count",
    "judge_agreement_n",
    "judge_claims_contradicted",
    "judge_claims_total",
    "judge_claims_unsupported",
    "wer_deletions",
    "wer_insertions",
    "wer_reference_words",
    "wer_substitutions",
    "wer_fluent_deletions",
    "wer_fluent_insertions",
    "wer_fluent_reference_words",
    "wer_fluent_substitutions",
}

# Suffixes that mark a count rather than a score, whatever the prefix.
_INFORMATIONAL_SUFFIXES = ("_predicted", "_reference", "_true_positives")


def is_informational(name: str) -> bool:
    return name in INFORMATIONAL or name.endswith(_INFORMATIONAL_SUFFIXES)


def compare_reports(baseline: dict[str, Any], current: dict[str, Any], tolerance: float = 0.01) -> dict[str, Any]:
    """Diff two runs. `regressions` lists metrics that moved the wrong way by
    more than `tolerance`, which is what a CI gate should fail on."""
    base_metrics = baseline.get("aggregate", {})
    new_metrics = current.get("aggregate", {})

    deltas: dict[str, dict[str, float]] = {}
    regressions: list[str] = []

    for name, new_entry in new_metrics.items():
        if name not in base_metrics:
            continue
        before = base_metrics[name]["mean"]
        after = new_entry["mean"]
        change = round(after - before, 4)
        deltas[name] = {"before": before, "after": after, "delta": change}

        if is_informational(name):
            continue
        worse = change > tolerance if name in LOWER_IS_BETTER else change < -tolerance
        if worse:
            regressions.append(name)

    # A comparison across different case sets is not a like-for-like read, so
    # say so rather than letting the deltas imply one.
    comparable = baseline.get("case_count") == current.get("case_count")

    return {
        "deltas": deltas,
        "regressions": regressions,
        "comparable_case_counts": comparable,
        "baseline_case_count": baseline.get("case_count"),
        "current_case_count": current.get("case_count"),
    }
