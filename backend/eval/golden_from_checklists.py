"""Turn clinician checklists into golden-set reference annotations.

Provenance matters more here than anywhere else in the harness, so it is worth
stating exactly which parts are human and which are not:

* the **transcript** is human — PriMock57's manual transcription;
* the **clinical items** are human — written by the clinicians who designed the
  consultations, and rated Critical / Non-Critical / Irrelevant by them;
* the **mapping** from a checklist phrase to a term and its assertion axes is
  the only machine-derived step, and it is deliberately rule-based rather than
  model-based so that it cannot share a blind spot with the pipeline it scores.

The rules below are shallow on purpose. A cleverer mapper would be a second
clinical NLP system, and scoring one clinical NLP system with another is how a
metric ends up measuring agreement instead of correctness.

Two filters keep the references honest:

**Nothing is dropped for being absent from our dictionary.** A checklist item
our lexicon does not know is a real miss and should score as one — that is how
the "visual changes" gap surfaced earlier. Filtering to terms we already have
would make recall near-perfect by construction.

**An item is only kept if its words appear in the transcript.** The golden set's
convention is to annotate the span that exists; a concept the clinician listed
but nobody said aloud is not something a transcript-based extractor can be
expected to find.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from eval.primock_checklists import ChecklistItem

# Qualifier prefixes the checklists use to structure sub-items. The clinical
# concept is what follows them.
_QUALIFIER_PREFIX = re.compile(
    r"^(location|nature|feels like|onset|duration|severity|timing|radiation|"
    r"frequency|character|site|aggravating|relieving|associated)\s*[-:]\s*",
    re.IGNORECASE,
)

# Items that are quantities, durations or bookkeeping rather than findings.
_NOT_A_FINDING = re.compile(
    r"^(\d+\s*(days?|weeks?|months?|years?|hours?|times?|/day|x/day)|"
    r"\d+\s*times?\s*/?\s*day|\d+/10|n/a|none|nil|correct|incorrect|note\s*\d*)$",
    re.IGNORECASE,
)

_NEGATION = re.compile(r"^(no|not|nil|denies|denied|without|never)\b[\s:]*", re.IGNORECASE)

# Wording that places a finding in the past rather than the present.
_HISTORICAL = re.compile(
    r"\b(ago|previously|stopped|resolved|settled|at the start|in the past|"
    r"used to|history of|childhood|as a child|last (week|month|year)|"
    r"since (resolved|stopped))\b",
    re.IGNORECASE,
)

_FAMILY = re.compile(
    r"\b(family history|mother|father|mum|mom|dad|brother|sister|parent|sibling|"
    r"runs in the family)\b",
    re.IGNORECASE,
)

# Trailing annotations the clinicians appended to items.
_TRAILING_NOTE = re.compile(r"\s*[-–]\s*(subjective|objective|reported|per patient)\s*$", re.IGNORECASE)

_PUNCTUATION = re.compile(r"[^a-z0-9 ]")
_WHITESPACE = re.compile(r"\s+")


@dataclass(frozen=True)
class ReferenceEntity:
    text: str
    negated: bool
    temporality: str
    experiencer: str
    criticality: str

    def to_dict(self) -> dict:
        return {
            "text": self.text,
            "negated": self.negated,
            "temporality": self.temporality,
            "experiencer": self.experiencer,
            "criticality": self.criticality,
        }


def _normalise(text: str) -> str:
    return _WHITESPACE.sub(" ", _PUNCTUATION.sub(" ", text.lower())).strip()


def _british_to_american(text: str) -> str:
    """The checklists use British spellings; the transcripts are inconsistent.

    Applied to both sides of every comparison, so it only ever merges forms
    that should match.
    """
    for british, american in (
        ("diarrhoea", "diarrhea"), ("oedema", "edema"), ("oesoph", "esoph"),
        ("haemo", "hemo"), ("anaemia", "anemia"), ("paediatric", "pediatric"),
        ("vomitted", "vomited"), ("catheterisation", "catheterization"),
    ):
        text = text.replace(british, american)
    return text


def _core_concept(text: str) -> str:
    """Strip the checklist's structural scaffolding down to the finding itself."""
    text = _TRAILING_NOTE.sub("", text.strip().rstrip(",.;"))
    text = _QUALIFIER_PREFIX.sub("", text)
    text = _NEGATION.sub("", text)
    # "Abdominal pain - lower" keeps the head, drops the qualifier.
    text = re.split(r"\s*[-–]\s*", text)[0]
    return text.strip().rstrip(",.;")


def _appears_in(concept: str, transcript_normalised: str) -> bool:
    """Whether every word of the concept is present in the transcript.

    Word-set containment rather than substring: the checklist writes "Blood in
    stool" where the transcript says "any blood in your stools", and requiring
    a contiguous match would reject a finding that is plainly there.
    """
    words = [w for w in _normalise(_british_to_american(concept)).split() if len(w) > 2]
    if not words:
        return False
    return all(word in transcript_normalised for word in words)


def reference_entities(
    items: list[ChecklistItem],
    transcript: str,
    *,
    max_words: int = 4,
) -> list[ReferenceEntity]:
    """Reference annotations for one consultation."""
    transcript_words = set(_normalise(_british_to_american(transcript)).split())

    references: dict[str, ReferenceEntity] = {}

    for item in items:
        if not item.is_scored:
            continue

        raw = item.text.strip()
        if _NOT_A_FINDING.match(raw):
            continue

        concept = _core_concept(raw)
        if not concept or _NOT_A_FINDING.match(concept):
            continue

        # Long phrases are sentences describing a finding, not the finding; an
        # extractor is not expected to emit them as a single entity.
        if len(concept.split()) > max_words:
            continue

        if not _appears_in(concept, transcript_words):
            continue

        negated = bool(_NEGATION.match(raw))
        temporality = "historical" if _HISTORICAL.search(raw) else "current"
        experiencer = "family" if _FAMILY.search(raw) else "patient"

        key = _normalise(_british_to_american(concept))
        if not key:
            continue

        # A term listed twice with different assertions keeps the stronger
        # claim: an explicit negative is more informative than its absence.
        existing = references.get(key)
        if existing is None or (negated and not existing.negated):
            references[key] = ReferenceEntity(
                text=concept.lower(),
                negated=negated,
                temporality=temporality,
                experiencer=experiencer,
                criticality=item.criticality,
            )

    return list(references.values())
