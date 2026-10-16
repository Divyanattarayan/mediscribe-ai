"""Check every clinical claim in a generated note against the transcript.

This replaces `soap_generator._ungrounded_terms`, a lexical proxy that flagged
any medication or condition appearing in the note but not in the transcript. It
was cheap and it was wrong in both directions: it could not tell a fabricated
prescription from a legitimately proposed differential (pericarditis for
pleuritic pain reads as a hallucination), and it saw nothing at all when the
note invented a *relationship* between terms that were both present — "the
patient takes amlodipine for their diabetes" passes a vocabulary check and is
still false.

The check here is per claim rather than per term. The note is decomposed into
atomic clinical assertions and each is judged against the transcript, returning
the supporting quote. That is the same call shape the eval harness has used as
a metric since Phase 1, promoted into the pipeline now that the fact table gives
generation something grounded to work from.

Two deliberate constraints:

**Nothing is rewritten.** Unsupported claims are reported, and the section is
handed back to the generator with the specific claims named. The old repair
layer deleted any sentence matching a regex, which silently dropped true
findings; a verifier that edits clinical prose by pattern is the same mistake in
a new place.

**A verifier failure is not a note failure.** If the check cannot run, the note
is returned unverified and says so, rather than being blocked or silently
treated as clean.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any

from groq_client import chat_json

CLAIM_VERIFICATION_ENABLED = os.getenv("CLAIM_VERIFICATION", "1") not in ("0", "false", "False")

# Each verification is one extra model call per note, so the budget has to cover
# a full note's worth of claims without truncating the reply.
MAX_TOKENS = int(os.getenv("CLAIM_VERIFICATION_MAX_TOKENS", "3000"))

SUPPORTED = "supported"
UNSUPPORTED = "unsupported"
CONTRADICTED = "contradicted"

_VERIFICATION_PROMPT = """You are auditing a clinical note against the transcript it was generated from.

Break the note into atomic clinical claims — one assertion each — and judge every claim:

- "supported": the transcript states it, or states something that directly entails it.
- "unsupported": the transcript does not contain it.
- "contradicted": the transcript states something incompatible with it.

Return ONLY valid JSON:
{"claims": [{"claim": "...", "section": "subjective|objective|assessment|plan",
             "verdict": "supported|unsupported|contradicted",
             "evidence": "verbatim transcript quote, or empty if none"}]}

Judging rules:
- Evidence MUST be copied verbatim from the transcript. Never paraphrase it.
- Documentation scaffolding asserts nothing about the patient and must be
  SKIPPED, not judged. This includes section headings and every statement about
  what the RECORD lacks rather than about the patient:
    "not documented in transcript", "not elicited in this recording",
    "was not asked", "no information available", "history gaps identified",
    "objective findings are pending examination",
    "this recording captures history-taking only".
  A statement that a topic was not covered is a claim about the consultation,
  and it is true whenever the transcript indeed does not cover it. Never mark
  one unsupported merely because the transcript lacks the topic — that is
  precisely what the statement says.
- A recorded NEGATIVE is a claim about the patient and must be judged: "denies
  chest pain" is supported only if the transcript shows the denial.
- Clinical reasoning is judged on its premises, not its conclusion. A
  differential diagnosis, a proposed investigation or a planned treatment is
  "supported" when the findings it rests on are in the transcript; it is not
  unsupported merely because the transcript never names the diagnosis.
- Continuing something the transcript establishes is supported: if the patient
  states they take a medication, "continue <medication>" rests on that.
- A value correctly COMPUTED from data the transcript states is supported, even
  if the transcript never says the computed value itself. An age stated as a
  number is supported when the transcript gives a date of birth the age is
  consistent with — the transcript need not say the age aloud for the
  arithmetic to be grounded.
- Judge only what the note ASSERTS about this patient. Hedged or conditional
  wording ("consider", "if symptoms persist", "to be confirmed by the treating
  clinician") asserts a plan, not a fact, and is supported when the situation
  prompting it is in the transcript.
- A stated fact about the patient — a medication they take, a measurement, a
  history item — is supported ONLY if the transcript contains it.
"""


@dataclass
class ClaimVerification:
    """One claim and what the verifier made of it."""

    claim: str
    verdict: str
    section: str = ""
    evidence: str = ""

    @property
    def is_problem(self) -> bool:
        return self.verdict in (UNSUPPORTED, CONTRADICTED)


@dataclass
class VerificationReport:
    claims: list[ClaimVerification] = field(default_factory=list)
    ran: bool = False
    error: str = ""

    @property
    def problems(self) -> list[ClaimVerification]:
        return [claim for claim in self.claims if claim.is_problem]

    @property
    def unsupported_rate(self) -> float:
        if not self.claims:
            return 0.0
        return round(len(self.problems) / len(self.claims), 4)

    def problems_by_section(self) -> dict[str, list[str]]:
        grouped: dict[str, list[str]] = {}
        for claim in self.problems:
            section = claim.section if claim.section in (
                "subjective", "objective", "assessment", "plan"
            ) else "unattributed"
            grouped.setdefault(section, []).append(claim.claim)
        return grouped

    def to_dict(self) -> dict[str, Any]:
        return {
            "ran": self.ran,
            "error": self.error,
            "claims_total": len(self.claims),
            "claims_unsupported": len(self.problems),
            "claims_contradicted": sum(1 for c in self.claims if c.verdict == CONTRADICTED),
            "unsupported_rate": self.unsupported_rate,
            "problems_by_section": self.problems_by_section(),
            "problem_claims": [
                {"claim": c.claim, "section": c.section, "verdict": c.verdict}
                for c in self.problems
            ],
        }


def _note_as_text(note: dict[str, Any]) -> str:
    return "\n\n".join(
        f"{section.upper()}:\n{note.get(section, '')}"
        for section in ("subjective", "objective", "assessment", "plan")
        if str(note.get(section, "")).strip()
    )


def verify_note(note: dict[str, Any], transcript: str) -> VerificationReport:
    """Judge every claim in `note` against `transcript`.

    Never raises. A verifier that cannot run returns `ran=False`, so callers can
    tell "nothing was wrong" apart from "nothing was checked" — the distinction
    the old lexical check could not make.
    """
    report = VerificationReport()

    if not CLAIM_VERIFICATION_ENABLED:
        report.error = "claim verification is disabled (CLAIM_VERIFICATION=0)"
        return report

    note_text = _note_as_text(note)
    if not note_text.strip() or not transcript.strip():
        report.error = "nothing to verify"
        return report

    try:
        payload = chat_json(
            _VERIFICATION_PROMPT,
            f"Transcript:\n{transcript}\n\nNote:\n{note_text}",
            max_tokens=MAX_TOKENS,
            temperature=0.0,
        )
    except Exception as exc:
        report.error = f"{type(exc).__name__}: {exc}"
        print(f"Claim verification unavailable: {report.error}")
        return report

    for raw in payload.get("claims", []) or []:
        if not isinstance(raw, dict):
            continue
        claim = str(raw.get("claim", "")).strip()
        verdict = str(raw.get("verdict", "")).strip().lower()
        if not claim or verdict not in (SUPPORTED, UNSUPPORTED, CONTRADICTED):
            continue
        report.claims.append(ClaimVerification(
            claim=claim,
            verdict=verdict,
            section=str(raw.get("section", "")).strip().lower(),
            evidence=str(raw.get("evidence", "")).strip(),
        ))

    report.ran = bool(report.claims)
    if not report.ran:
        report.error = "verifier returned no usable claims"
    return report
