"""Assertion detection: negation, temporality, experiencer and uncertainty.

Without this layer, `"the patient denies chest pain"` produces a positive chest
pain symptom and `"my dad had a heart attack"` becomes the patient's cardiac
history. Both errors then propagate into the SOAP note, which is worse than
missing the entity entirely — a note that asserts a symptom the patient
explicitly denied is a clinical safety problem, not a quality one.

Implemented with medspaCy's ConText, the standard implementation of the ConText
algorithm (Harkema et al.), rather than hand-rolled regex. The four axes it
resolves are the four that change what a mention *means*:

    negated       "denies chest pain"          -> the symptom is absent
    historical    "asthma as a child"          -> not an active problem
    hypothetical  "if the pain comes back"     -> conditional, not a finding
    family        "his father had a heart attack" -> not the patient's history

ConText runs over `doc.ents`, but our entity list is built in two passes (NER
plus a dictionary scan) and is only assembled *after* the pipeline has run. So
the component is invoked a second time here, against the merged list, rather
than left to fire during `nlp(text)` on the NER entities alone. That matters:
the dictionary scan is what finds most symptom mentions, and those are exactly
the ones most often negated.
"""

from __future__ import annotations

import re
from typing import Any

import spacy
from spacy.tokens import Doc, Span
from spacy.util import filter_spans

try:
    # Importing medspacy is what registers the `medspacy_context` factory with
    # spaCy. Nothing else here uses the module directly, but without the import
    # `nlp.add_pipe(CONTEXT_PIPE)` raises E002.
    import medspacy  # noqa: F401
    MEDSPACY_AVAILABLE = True
except ImportError:  # pragma: no cover - assertion detection degrades, nothing breaks
    MEDSPACY_AVAILABLE = False

CONTEXT_PIPE = "medspacy_context"

# ConText ships with rules written for dictated clinical notes ("history of",
# "past medical history"). Consultation speech says the same things differently,
# and the default set misses it: "asthma as a child" reads as a current problem.
#
# These additions are all *conversational phrasings of the same four axes* — no
# condition names, no specialty assumptions — so they generalise the way the
# rules they supplement do. Direction is relative to the modifier: BACKWARD
# modifies what came before it, FORWARD what follows.
#
# Rule for adding rules: a new entry has to be justifiable as a general
# phrasing of its axis, not by the fact that it makes a golden case pass. The
# golden set is four cases; tuning against it would rebuild exactly the
# overfitting Phase 0 removed. "weeks ago" earns its place because "years ago"
# and "months ago" are already here and the class is obviously the same;
# "in his fifties" does not, however tempting the failing case is.
_CUSTOM_RULE_SPECS: tuple[tuple[str, str, str], ...] = (
    # Historical, stated after the finding
    ("as a child", "HISTORICAL", "BACKWARD"),
    ("as a kid", "HISTORICAL", "BACKWARD"),
    ("when i was younger", "HISTORICAL", "BACKWARD"),
    ("when he was younger", "HISTORICAL", "BACKWARD"),
    ("when she was younger", "HISTORICAL", "BACKWARD"),
    ("years ago", "HISTORICAL", "BACKWARD"),
    ("months ago", "HISTORICAL", "BACKWARD"),
    ("weeks ago", "HISTORICAL", "BACKWARD"),
    ("days ago", "HISTORICAL", "BACKWARD"),
    ("last week", "HISTORICAL", "BACKWARD"),
    ("last month", "HISTORICAL", "BACKWARD"),
    ("last year", "HISTORICAL", "BACKWARD"),
    ("in the past", "HISTORICAL", "BACKWARD"),
    ("a long time ago", "HISTORICAL", "BACKWARD"),
    # Historical, stated before the finding
    ("used to have", "HISTORICAL", "FORWARD"),
    ("used to get", "HISTORICAL", "FORWARD"),
    ("previously had", "HISTORICAL", "FORWARD"),
    ("has had", "HISTORICAL", "FORWARD"),
    ("kept getting", "HISTORICAL", "FORWARD"),
    ("keeps getting", "HISTORICAL", "FORWARD"),
    # "i had" was here and was too broad: it fired on "the blood test said I had
    # diabetes" and marked an active diagnosis as historical. A rule that
    # depends on tense alone cannot tell a resolved illness from a new one.
    # Family, conversational
    ("runs in the family", "FAMILY", "BACKWARD"),
    ("my dad", "FAMILY", "FORWARD"),
    ("my mum", "FAMILY", "FORWARD"),
    ("my mom", "FAMILY", "FORWARD"),
    ("my brother", "FAMILY", "FORWARD"),
    ("my sister", "FAMILY", "FORWARD"),
    # Hypothetical / conditional
    ("if it comes back", "HYPOTHETICAL", "BIDIRECTIONAL"),
    ("if that happens", "HYPOTHETICAL", "BIDIRECTIONAL"),
    ("should you develop", "HYPOTHETICAL", "FORWARD"),
    ("in case of", "HYPOTHETICAL", "FORWARD"),
    ("watch out for", "HYPOTHETICAL", "FORWARD"),
    # Negation, conversational
    ("nothing like", "NEGATED_EXISTENCE", "FORWARD"),
    ("never had", "NEGATED_EXISTENCE", "FORWARD"),
    ("i haven't had", "NEGATED_EXISTENCE", "FORWARD"),
    ("not had any", "NEGATED_EXISTENCE", "FORWARD"),
)

# Values written onto every entity, so downstream code can rely on the keys
# existing rather than testing for their presence.
DEFAULT_ASSERTIONS: dict[str, Any] = {
    "negated": False,
    "temporality": "current",
    "experiencer": "patient",
    "uncertain": False,
    "assertion_source": "default",
}


# Speaker labels are the single largest source of assertion misses on dialogue
# transcripts. ConText's rules were written for dictated prose, and a leading
# "Patient:" stops the negation triggers firing: "No nausea." is detected,
# "Patient: No nausea." is not.
#
# The labels are replaced with spaces rather than deleted so every character
# offset in the transcript stays exactly where it was — entity spans, the
# dictionary scan and anything stored in the database all keep pointing at the
# right text.
_SPEAKER_LABEL = re.compile(
    r"\b(?:doctor|dr|clinician|physician|nurse|gp|patient|pt|caller|interviewer|speaker\s*\d+)\s*:",
    flags=re.IGNORECASE,
)


def mask_speaker_labels(text: str) -> str:
    """Blank out `Doctor:` / `Patient:` style labels, preserving text length."""
    return _SPEAKER_LABEL.sub(lambda match: " " * len(match.group(0)), text)


def attach_context(nlp: spacy.language.Language) -> spacy.language.Language:
    """Add the ConText component to an existing pipeline, once.

    ConText needs sentence boundaries, which the scispaCy pipeline supplies via
    its parser. A pipeline without one gets a sentencizer so the component
    cannot raise at call time.
    """
    if CONTEXT_PIPE in nlp.pipe_names:
        return nlp

    if not MEDSPACY_AVAILABLE:
        # Every entity keeps the defaults and is marked unresolved, so the
        # degradation shows up in `assertion_counts` instead of silently
        # asserting that nothing was ever negated.
        print("medspacy is not installed - assertion detection is disabled.")
        return nlp

    if not nlp.has_pipe("parser") and not nlp.has_pipe("senter") and not nlp.has_pipe("sentencizer"):
        nlp.add_pipe("sentencizer", first=True)

    nlp.add_pipe(CONTEXT_PIPE)
    _add_custom_rules(nlp.get_pipe(CONTEXT_PIPE))
    return nlp


def _add_custom_rules(context_component: Any) -> None:
    """Extend the default ConText rules with conversational phrasings.

    Failure here is not fatal: the default rules still apply, and the run
    degrades to note-style triggers only rather than losing assertions entirely.
    """
    try:
        from medspacy.context import ConTextRule

        context_component.add([
            ConTextRule(literal=literal, category=category, direction=direction)
            for literal, category, direction in _CUSTOM_RULE_SPECS
        ])
    except Exception as exc:  # pragma: no cover - defensive
        print(f"Could not add conversational ConText rules: {type(exc).__name__}: {exc}")


def annotate_assertions(
    doc: Doc,
    entities: list[dict[str, Any]],
    nlp: spacy.language.Language,
) -> list[dict[str, Any]]:
    """Annotate `entities` in place with assertion attributes and return them.

    `entities` are our own dicts carrying character offsets. They are projected
    onto the doc as spans, ConText is run, and the results are read back by
    offset. Entities that cannot be projected — or that lose an overlap
    conflict — keep the defaults and are marked `assertion_source: "default"`
    so a low-coverage run is visible rather than silently assumed correct.
    """
    for entity in entities:
        entity.update(DEFAULT_ASSERTIONS)

    if not entities or CONTEXT_PIPE not in nlp.pipe_names:
        return entities

    spans: list[Span] = []
    for entity in entities:
        # `expand` because the dictionary scan matches on characters and may cut
        # across token boundaries; a span that snaps outward still sits in the
        # right sentence, which is the only thing ConText needs.
        span = doc.char_span(
            int(entity["start"]),
            int(entity["end"]),
            label=str(entity.get("label", "")),
            alignment_mode="expand",
        )
        if span is not None:
            spans.append(span)

    if not spans:
        return entities

    original_ents = doc.ents
    try:
        doc.ents = filter_spans(spans)
        nlp.get_pipe(CONTEXT_PIPE)(doc)
        resolved = {(span.start_char, span.end_char): _read_span(span) for span in doc.ents}
    except Exception as exc:  # a failure here must not lose the entities
        print(f"Assertion detection skipped: {type(exc).__name__}: {exc}")
        return entities
    finally:
        try:
            doc.ents = original_ents
        except ValueError:
            pass

    for entity in entities:
        span = doc.char_span(
            int(entity["start"]), int(entity["end"]), alignment_mode="expand"
        )
        if span is None:
            continue
        attributes = resolved.get((span.start_char, span.end_char))
        if attributes:
            entity.update(attributes)

    return entities


def _read_span(span: Span) -> dict[str, Any]:
    """Fold ConText's five booleans into the four axes we store.

    Temporality is a single value rather than two flags because a mention is
    reported in one tense; where ConText marks both, hypothetical wins, since
    "if the chest pain returns" is a weaker assertion than "had chest pain".
    """
    is_historical = bool(getattr(span._, "is_historical", False))
    is_hypothetical = bool(getattr(span._, "is_hypothetical", False))

    if is_hypothetical:
        temporality = "hypothetical"
    elif is_historical:
        temporality = "historical"
    else:
        temporality = "current"

    return {
        "negated": bool(getattr(span._, "is_negated", False)),
        "temporality": temporality,
        "experiencer": "family" if bool(getattr(span._, "is_family", False)) else "patient",
        "uncertain": bool(getattr(span._, "is_uncertain", False)),
        "assertion_source": CONTEXT_PIPE,
    }


def assertion_counts(entities: list[dict[str, Any]]) -> dict[str, int]:
    """Summary for logging and for the API response."""
    return {
        "negated": sum(1 for entity in entities if entity.get("negated")),
        "historical": sum(1 for entity in entities if entity.get("temporality") == "historical"),
        "hypothetical": sum(1 for entity in entities if entity.get("temporality") == "hypothetical"),
        "family": sum(1 for entity in entities if entity.get("experiencer") == "family"),
        "uncertain": sum(1 for entity in entities if entity.get("uncertain")),
        # A missing key counts as unresolved too: an entity that never reached
        # assertion detection is exactly as unverified as one ConText declined
        # to resolve, and reporting it as resolved would overstate coverage.
        "unresolved": sum(
            1 for entity in entities if entity.get("assertion_source", "default") == "default"
        ),
    }


def is_active_patient_finding(entity: dict[str, Any]) -> bool:
    """True when a mention asserts something currently true of this patient.

    The single predicate downstream code should use before treating an entity
    as an active problem.
    """
    return (
        not entity.get("negated", False)
        and entity.get("experiencer", "patient") == "patient"
        and entity.get("temporality", "current") == "current"
    )
