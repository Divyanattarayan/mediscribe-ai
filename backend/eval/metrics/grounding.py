"""Offline groundedness metrics: does the note say things the source did not,
and does it omit things the source did?

These are *lexical proxies* computed over the medication/condition/procedure
lexicon. They are cheap, deterministic, and need no API key, which makes them
the metric that can run in CI on every commit. They are not a substitute for
claim-level entailment (see `judge.py`, and Phase 3 of the roadmap): a note can
be lexically grounded and still assert a relationship the transcript never
supported.

Reported alongside every number is the denominator, so a hallucination rate of
0.0 over two detected terms is not mistaken for a clean bill of health.
"""

from __future__ import annotations

import re
from typing import Any

from medical_categories import CONDITIONS, MEDICATIONS, PROCEDURES, SYMPTOMS

_PUNCTUATION = re.compile(r"[^a-z0-9' ]")
_WHITESPACE = re.compile(r"\s+")

# Short entries produce substring noise rather than signal, so the same >4
# character cut-off as the in-pipeline check applies here.
#
# Symptoms are in scope for the metric but not for the in-pipeline check in
# `soap_generator._GROUNDING_TERMS`, and the asymmetry is deliberate. The
# in-pipeline check decides whether to spend an LLM call regenerating a
# section, so it favours precision and stays on drugs and diagnoses. The metric
# only reports, so it can afford the wider net — and a symptom the note dropped
# is exactly the kind of omission worth measuring.
_CLINICAL_TERMS: frozenset[str] = frozenset(
    _WHITESPACE.sub(" ", _PUNCTUATION.sub(" ", term.lower())).strip()
    for term in (MEDICATIONS | CONDITIONS | PROCEDURES | SYMPTOMS)
    if len(term) > 4
)


def _normalise(text: Any) -> str:
    lowered = str(text).lower().replace("’", "'")
    return _WHITESPACE.sub(" ", _PUNCTUATION.sub(" ", lowered)).strip()


def _terms_present(text: str) -> set[str]:
    padded = f" {_normalise(text)} "
    return {term for term in _CLINICAL_TERMS if f" {term} " in padded}


def note_text(note: dict[str, str] | str | None) -> str:
    if note is None:
        return ""
    if isinstance(note, str):
        return note
    return " ".join(str(value) for value in note.values() if value)


def grounding_scores(
    generated_note: dict[str, str] | str,
    source_transcript: str,
    reference_note: dict[str, str] | str | None = None,
) -> dict[str, float]:
    """Hallucination against the transcript; omission against the reference note.

    * hallucination_rate — share of clinical terms in the generated note that
      appear nowhere in the transcript.
    * omission_rate — share of clinical terms in the *reference* note that the
      generated note failed to carry over. Only computed when a reference note
      exists; otherwise reported as -1.0 to keep it distinguishable from a
      genuine zero.
    """
    generated_terms = _terms_present(note_text(generated_note))
    source_terms = _terms_present(source_transcript)

    unsupported = generated_terms - source_terms
    hallucination_rate = len(unsupported) / len(generated_terms) if generated_terms else 0.0

    metrics = {
        "hallucination_rate": round(hallucination_rate, 4),
        "hallucinated_term_count": float(len(unsupported)),
        "generated_term_count": float(len(generated_terms)),
    }

    if reference_note is None:
        metrics["omission_rate"] = -1.0
        metrics["reference_term_count"] = 0.0
        return metrics

    reference_terms = _terms_present(note_text(reference_note))
    omitted = reference_terms - generated_terms
    metrics["omission_rate"] = round(
        len(omitted) / len(reference_terms), 4
    ) if reference_terms else 0.0
    metrics["omitted_term_count"] = float(len(omitted))
    metrics["reference_term_count"] = float(len(reference_terms))
    return metrics


def grounding_details(
    generated_note: dict[str, str] | str,
    source_transcript: str,
    reference_note: dict[str, str] | str | None = None,
) -> dict[str, list[str]]:
    """The terms behind the rates, for triaging a bad case by hand."""
    generated_terms = _terms_present(note_text(generated_note))
    source_terms = _terms_present(source_transcript)
    details = {"hallucinated": sorted(generated_terms - source_terms)}
    if reference_note is not None:
        details["omitted"] = sorted(_terms_present(note_text(reference_note)) - generated_terms)
    return details
