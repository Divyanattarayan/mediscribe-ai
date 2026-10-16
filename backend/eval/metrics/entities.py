"""Entity-extraction metrics.

Two matching modes, because the two questions differ:

* `strict` — text *and* category must match. Answers "did we label it right".
* `lenient` — text only. Answers "did we find it at all", which is what the
  downstream SOAP prompt actually consumes.

Both report the confusion counts alongside P/R/F1 so a low score can be read as
"we miss things" or "we invent things" rather than a single opaque number.

`assertion_scores` answers a third, separate question: of the entities we *did*
find, did we read them correctly? Detection and assertion accuracy have to be
measured apart, because a pipeline can find every mention and still record a
denied symptom as present — which is worse than missing it.
"""

from __future__ import annotations

import re
from typing import Any, Iterable

_WHITESPACE = re.compile(r"\s+")
_PUNCTUATION = re.compile(r"[^a-z0-9' ]")

# The extractor emits NER labels; references use category names. Neither
# vocabulary is authoritative, so both are folded to one set before comparing.
_LABEL_TO_CATEGORY = {
    "CHEMICAL": "medication",
    "MEDICATION": "medication",
    "DISEASE": "condition",
    "CONDITION": "condition",
    "SYMPTOM": "symptom",
    "TEST": "test",
    "PROCEDURE": "procedure",
    "ANATOMICAL": "anatomical",
}


def canonical_category(label: str | None) -> str:
    if not label:
        return "other"
    return _LABEL_TO_CATEGORY.get(str(label).upper(), str(label).lower())


def canonical_text(text: str) -> str:
    lowered = str(text).lower().replace("’", "'")
    cleaned = _WHITESPACE.sub(" ", _PUNCTUATION.sub(" ", lowered)).strip()
    return " ".join(_singularise(token) for token in cleaned.split())


def _singularise(token: str) -> str:
    """Fold plural forms so `headaches` matches `headache`.

    Not linguistically correct — "diabetes" becomes "diabete" — and it does not
    need to be. The transform is applied to both sides of every comparison, so
    it can only merge forms that should match; it never separates ones that
    should. Scoring a correct extraction as *both* a miss and a false positive
    because the speaker used the plural is far worse than the occasional
    over-merge this risks.

    Deliberately only two rules. A richer set ("-ches" → strip "es", to turn
    "boxes" into "box") breaks the invariant, because it fires on the plural
    without a matching transform for the singular: "headaches" became "headach"
    while "headache" stayed itself, and the two stopped matching.
    """
    if len(token) <= 3 or token.endswith("ss"):
        return token
    if token.endswith("ies"):
        return token[:-3] + "y"
    if token.endswith("s"):
        return token[:-1]
    return token


def _keys(entities: Iterable[dict[str, Any]], strict: bool) -> set:
    """The distinct concepts a list mentions.

    Sets, not multisets. References annotate a *term*, while the extractor emits
    one entity per *mention*, so counting occurrences scored a transcript that
    says "headaches" three times as two false positives for finding it three
    times. Repetition is a property of the conversation, not of extraction
    quality.
    """
    keys = set()
    for entity in entities:
        text = canonical_text(entity.get("text", ""))
        if not text:
            continue
        keys.add((text, canonical_category(entity.get("label"))) if strict else (text,))
    return keys


def _prf(true_positives: int, predicted: int, actual: int) -> dict[str, float]:
    precision = true_positives / predicted if predicted else 0.0
    recall = true_positives / actual if actual else 0.0
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) else 0.0
    return {"precision": round(precision, 4), "recall": round(recall, 4), "f1": round(f1, 4)}


def entity_scores(
    reference: list[dict[str, Any]],
    hypothesis: list[dict[str, Any]],
    *,
    strict: bool = False,
) -> dict[str, float]:
    """P/R/F1 over the distinct concepts each side mentions."""
    ref = _keys(reference, strict)
    hyp = _keys(hypothesis, strict)

    true_positives = len(ref & hyp)
    predicted = len(hyp)
    actual = len(ref)

    prefix = "entity_strict" if strict else "entity_lenient"
    scores = _prf(true_positives, predicted, actual)
    return {
        f"{prefix}_precision": scores["precision"],
        f"{prefix}_recall": scores["recall"],
        f"{prefix}_f1": scores["f1"],
        f"{prefix}_true_positives": float(true_positives),
        f"{prefix}_predicted": float(predicted),
        f"{prefix}_reference": float(actual),
    }


def missed_and_spurious(
    reference: list[dict[str, Any]],
    hypothesis: list[dict[str, Any]],
) -> dict[str, list[str]]:
    """The actual terms behind the numbers, for eyeballing a regression."""
    ref = _keys(reference, strict=False)
    hyp = _keys(hypothesis, strict=False)
    return {
        "missed": sorted(key[0] for key in (ref - hyp)),
        "spurious": sorted(key[0] for key in (hyp - ref)),
    }


# ── Assertion accuracy ────────────────────────────────────────────────────────

ASSERTION_AXES = ("negated", "temporality", "experiencer")

_AXIS_DEFAULTS = {"negated": False, "temporality": "current", "experiencer": "patient"}


def _axis_value(entity: dict[str, Any], axis: str) -> Any:
    value = entity.get(axis, _AXIS_DEFAULTS[axis])
    return bool(value) if axis == "negated" else str(value).lower()


def assertion_scores(
    reference: list[dict[str, Any]],
    hypothesis: list[dict[str, Any]],
) -> dict[str, float]:
    """Per-axis accuracy over entities present in both lists.

    Scored only on matched entities, so a detection failure is charged to the
    entity metrics and not double-counted here. `assertion_exact_accuracy` is
    the share where all three axes are right at once — the number that says
    whether a mention was read correctly, rather than mostly correctly.

    A reference with no assertion annotations produces no scores rather than a
    perfect one: every axis would trivially match its default.
    """
    if not any(any(axis in entity for axis in ASSERTION_AXES) for entity in reference):
        return {}

    by_text: dict[str, dict[str, Any]] = {}
    for entity in hypothesis:
        text = canonical_text(entity.get("text", ""))
        # Keep the first mention of a term; references annotate the term, not
        # each occurrence, so comparing against a later mention with different
        # context would be scoring something the reference never claimed.
        if text and text not in by_text:
            by_text[text] = entity

    matched = 0
    correct = {axis: 0 for axis in ASSERTION_AXES}
    fully_correct = 0

    for expected in reference:
        text = canonical_text(expected.get("text", ""))
        actual = by_text.get(text)
        if actual is None:
            continue
        matched += 1
        hits = 0
        for axis in ASSERTION_AXES:
            if _axis_value(expected, axis) == _axis_value(actual, axis):
                correct[axis] += 1
                hits += 1
        if hits == len(ASSERTION_AXES):
            fully_correct += 1

    if matched == 0:
        return {"assertion_matched_entities": 0.0}

    scores = {
        f"assertion_{axis}_accuracy": round(correct[axis] / matched, 4)
        for axis in ASSERTION_AXES
    }
    scores["assertion_exact_accuracy"] = round(fully_correct / matched, 4)
    scores["assertion_matched_entities"] = float(matched)
    return scores


def assertion_errors(
    reference: list[dict[str, Any]],
    hypothesis: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """The mentions we read wrongly, for triage."""
    by_text = {}
    for entity in hypothesis:
        text = canonical_text(entity.get("text", ""))
        if text and text not in by_text:
            by_text[text] = entity

    errors = []
    for expected in reference:
        text = canonical_text(expected.get("text", ""))
        actual = by_text.get(text)
        if actual is None:
            continue
        wrong = {
            axis: {"expected": _axis_value(expected, axis), "actual": _axis_value(actual, axis)}
            for axis in ASSERTION_AXES
            if _axis_value(expected, axis) != _axis_value(actual, axis)
        }
        if wrong:
            errors.append({"text": text, "axes": wrong})
    return errors
