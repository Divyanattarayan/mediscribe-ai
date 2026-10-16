"""Does the note contain what a clinician said was clinically present?

This is the metric the checklists are actually good for, and it came out of an
attempt at something else. The first plan was to convert PriMock57's
clinician-authored checklists into entity-level reference annotations and grow
the golden set that way. The conversion did not survive inspection: about half
the output was real findings ("blood in stool", negated; "night sweats",
negated; "asthma") and half was fragments the checklists use as scaffolding
("one side", "comes and goes", "accountant", "and 2 children"). Scoring an
entity extractor against references containing "accountant" would understate its
recall for reasons that have nothing to do with extraction.

Filtering the fragments out needs a clinical vocabulary. Using *ours* would make
recall near-perfect by construction — we cannot miss what we never wrote down —
and an external one did not work either: the NLM conditions endpoint rejected
"loss of appetite" and "watery stool" while matching "left" to *Left ventricular
dysfunction* at full confidence.

So the mapping to entity spans is abandoned, and the checklist items are used
whole, at the level they were written: **did the generated note cover this
item?** That question needs no span mapping, keeps the clinicians' own
Critical / Non-Critical rating, and measures something a clinician would
actually care about — whether the note lost a finding they considered critical.

It is a coverage measure, not an accuracy measure. A note that mentions every
checklist item and also invents three more scores perfectly here; hallucination
is what `claim_verification` is for. The two are complementary and neither
replaces the other.

**Why the judging is model-based.** The obvious implementation — word overlap
between item and note — was written first and then calibrated by scoring the
clinician's own note against their own checklist. That ceiling came out at 22%.
A human reference scoring 22% means the metric is broken, not the note, and the
misses said why: the checklist writes "Abdominal pain - lower" where the note
writes "LLQ pain", and "7 times/day" where the note writes "x6/day". Clinical
shorthand does not word-match, so lexical coverage measures vocabulary overlap
rather than clinical coverage.

The model is therefore asked a narrow, checkable question — "is this specific
human-authored finding present in this note?" — rather than "is this note any
good". The items being judged are still human ground truth; only the matching is
automated. `ceiling_scores` re-runs the same judgement on the clinician's own
note so every reported figure comes with the score a human achieved on the same
items, which is the only way the number is interpretable.
"""

from __future__ import annotations

import re

from groq_client import chat_json

from eval.golden_from_checklists import _british_to_american
from eval.primock_checklists import ChecklistItem

_PUNCTUATION = re.compile(r"[^a-z0-9 ]")
_WHITESPACE = re.compile(r"\s+")

# Words carrying no clinical content, so requiring the note to repeat them would
# punish paraphrase rather than reward coverage.
_STOPWORDS = frozenset({
    "the", "a", "an", "of", "in", "on", "at", "to", "and", "or", "for", "with",
    "is", "was", "has", "had", "have", "been", "be", "his", "her", "their",
    "patient", "patients", "reports", "reported", "states", "no", "not", "any",
    "some", "more", "than", "that", "this", "it", "as", "by", "from",
})

# Below this share of an item's content words, a note is not covering it.
MIN_WORD_OVERLAP = 0.6


def _content_words(text: str) -> set[str]:
    normalised = _WHITESPACE.sub(" ", _PUNCTUATION.sub(" ", _british_to_american(text.lower())))
    return {word for word in normalised.split() if len(word) > 2 and word not in _STOPWORDS}


def covers(item_text: str, note_words: set[str]) -> bool:
    """Whether the note carries the substance of one checklist item.

    Word overlap rather than phrase matching, because a clinician writes
    "7 times/day" and a note writes "opening bowels seven times daily" — the
    finding is present and a substring check would miss it. Crude, and stated as
    crude: it rewards vocabulary overlap, not clinical equivalence.
    """
    words = _content_words(item_text)
    if not words:
        return False
    return len(words & note_words) / len(words) >= MIN_WORD_OVERLAP


def coverage_scores(items: list[ChecklistItem], note: dict[str, str] | str) -> dict[str, float]:
    """Share of clinician-listed items the note covers, split by criticality.

    `critical_item_coverage` is the headline: these are the findings the
    clinicians who designed the consultation marked as ones that matter.
    """
    text = note if isinstance(note, str) else " ".join(str(v) for v in note.values() if v)
    note_words = _content_words(text)

    scored = [item for item in items if item.is_scored]
    critical = [item for item in scored if item.criticality == "critical"]

    if not scored:
        return {}

    covered_all = sum(1 for item in scored if covers(item.text, note_words))
    covered_critical = sum(1 for item in critical if covers(item.text, note_words))

    metrics = {
        "checklist_coverage": round(covered_all / len(scored), 4),
        "checklist_items": float(len(scored)),
        "checklist_items_covered": float(covered_all),
    }
    if critical:
        metrics["critical_item_coverage"] = round(covered_critical / len(critical), 4)
        metrics["critical_items"] = float(len(critical))
        metrics["critical_items_covered"] = float(covered_critical)
    return metrics


def missed_items(items: list[ChecklistItem], note: dict[str, str] | str) -> list[dict[str, str]]:
    """The clinician-listed findings the note did not carry, worst first."""
    text = note if isinstance(note, str) else " ".join(str(v) for v in note.values() if v)
    note_words = _content_words(text)

    missed = [
        {"item": item.text, "criticality": item.criticality}
        for item in items
        if item.is_scored and not covers(item.text, note_words)
    ]
    missed.sort(key=lambda entry: entry["criticality"] != "critical")
    return missed


# ── Model-judged coverage ─────────────────────────────────────────────────────

_COVERAGE_PROMPT = """You are checking whether a clinical note records specific findings.

You are given a numbered list of findings a clinician documented as present (or
explicitly absent) in a consultation, and the note produced for that
consultation. For each finding, decide whether the note conveys it.

Return ONLY valid JSON:
{"findings": [{"id": <number>, "covered": true|false}]}

Rules:
- Judge clinical equivalence, not wording. Clinical notes use shorthand and
  abbreviations: "LLQ pain" covers "Abdominal pain - lower"; "opening bowels
  x6/day" covers "6-7 times/day"; "3/7 hx" covers "3 days".
- A finding stated as ABSENT is covered only if the note also records it as
  absent. A note silent on it does not cover it, and a note asserting it as
  present certainly does not.
- Approximate quantities count as covered when they clearly refer to the same
  finding ("x6/day" covers "7 times/day").
- Judge only presence in the note. Do not assess whether the note is otherwise
  correct, complete or well written.
- Return exactly one entry per finding id you were given.
"""


def _judge_coverage(items: list[ChecklistItem], note_text: str) -> dict[int, bool] | None:
    """Ask the model which findings the note carries. None if it cannot run."""
    listing = "\n".join(f"{index}. {item.text}" for index, item in enumerate(items))
    try:
        payload = chat_json(
            _COVERAGE_PROMPT,
            f"Findings:\n{listing}\n\nNote:\n{note_text}",
            max_tokens=3000,
            temperature=0.0,
            # Judged by the evaluation model, not the one that wrote the note:
            # asking a model whether its own output covered a finding is a
            # self-assessment, and this metric already carries enough
            # interpretation risk without that.
            role="judge",
        )
    except Exception as exc:
        print(f"Coverage judging unavailable: {type(exc).__name__}: {exc}")
        return None

    verdicts: dict[int, bool] = {}
    for entry in payload.get("findings", []) or []:
        if isinstance(entry, dict) and isinstance(entry.get("id"), int):
            verdicts[entry["id"]] = bool(entry.get("covered"))
    return verdicts or None


def judged_coverage_scores(
    items: list[ChecklistItem],
    note: dict[str, str] | str,
    *,
    prefix: str = "",
) -> dict[str, float]:
    """Coverage as judged by the model, falling back to nothing if it cannot run.

    Returns an empty dict rather than lexical scores on failure: a silently
    weaker measurement reported under the same metric name is how two runs stop
    being comparable.
    """
    text = note if isinstance(note, str) else " ".join(str(v) for v in note.values() if v)
    scored = [item for item in items if item.is_scored]
    if not scored or not text.strip():
        return {}

    verdicts = _judge_coverage(scored, text)
    if verdicts is None:
        return {}

    critical_indices = [i for i, item in enumerate(scored) if item.criticality == "critical"]
    covered_all = sum(1 for i in range(len(scored)) if verdicts.get(i, False))
    covered_critical = sum(1 for i in critical_indices if verdicts.get(i, False))

    metrics = {
        f"{prefix}checklist_coverage": round(covered_all / len(scored), 4),
        f"{prefix}checklist_items": float(len(scored)),
    }
    if critical_indices:
        metrics[f"{prefix}critical_item_coverage"] = round(
            covered_critical / len(critical_indices), 4
        )
        metrics[f"{prefix}critical_items"] = float(len(critical_indices))
    return metrics


def ceiling_scores(items: list[ChecklistItem], clinician_note: str) -> dict[str, float]:
    """The same judgement applied to the clinician's own note.

    Without this a coverage figure is uninterpretable. A pipeline scoring 0.6 is
    poor if a human scored 0.95 on the same items and respectable if the human
    scored 0.65 — and the human's own note is the only fair reference for what
    these particular items allow.
    """
    return judged_coverage_scores(items, clinician_note, prefix="ceiling_")
