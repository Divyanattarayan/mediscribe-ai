"""Speech-recognition metrics.

Word error rate is implemented here rather than pulled from `jiwer` for two
reasons: it avoids a dependency for ~40 lines of well-understood code, and the
alignment it produces is reused by `medical_term_error_rate`, which is the
metric that actually matters clinically. A transcript can post a respectable
overall WER while dropping every drug name in the encounter.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from medical_categories import (
    CONDITIONS,
    MEDICATIONS,
    PROCEDURES,
    SYMPTOMS,
)

_PUNCTUATION = re.compile(r"[^a-z0-9' ]")
_WHITESPACE = re.compile(r"\s+")

# Hesitation sounds and acknowledgement tokens. Human transcribers write them;
# Whisper is trained to produce clean prose and omits them. That is a
# transcription-convention difference, not a recognition failure — and on
# PriMock57 it accounts for about 60% of the words the ASR appears to "miss".
#
# Only sounds and backchannels are here. Words that can carry clinical meaning
# ("no", "yes", "right" as an answer) are deliberately absent: dropping those
# would hide real errors.
DISFLUENCIES = frozenset({
    "um", "umm", "uh", "uhh", "erm", "er", "ah", "ahh", "eh",
    "mm", "mmm", "hmm", "hm", "mhm", "uhhuh", "mmhmm",
})

# Terms whose transcription errors change clinical meaning. Symptoms are
# included because a dropped symptom changes the note as much as a dropped drug.
_MEDICAL_LEXICON: frozenset[str] = frozenset(
    term.lower() for term in (MEDICATIONS | CONDITIONS | PROCEDURES | SYMPTOMS)
)
_MAX_TERM_WORDS = max(len(term.split()) for term in _MEDICAL_LEXICON)


def normalise(text: str, *, strip_disfluencies: bool = False) -> list[str]:
    """Lowercase, strip punctuation, collapse whitespace, split to tokens."""
    lowered = str(text).lower().replace("’", "'")
    cleaned = _PUNCTUATION.sub(" ", lowered)
    tokens = _WHITESPACE.sub(" ", cleaned).strip().split()
    if strip_disfluencies:
        tokens = [token for token in tokens if token not in DISFLUENCIES]
    return tokens


@dataclass
class WerResult:
    wer: float
    substitutions: int
    deletions: int
    insertions: int
    reference_words: int

    def as_metrics(self, prefix: str = "wer") -> dict[str, float]:
        return {
            prefix: round(self.wer, 4),
            f"{prefix}_substitutions": float(self.substitutions),
            f"{prefix}_deletions": float(self.deletions),
            f"{prefix}_insertions": float(self.insertions),
            f"{prefix}_reference_words": float(self.reference_words),
        }


def word_error_rate(reference: str, hypothesis: str, *, strip_disfluencies: bool = False) -> WerResult:
    """Levenshtein WER with an edit-type breakdown.

    `strip_disfluencies` removes hesitation sounds from *both* sides before
    aligning. Use it when the question is "did the ASR capture what was said",
    rather than "does it reproduce a verbatim transcript" — a scribe wants the
    former, and a verbatim reference otherwise charges it for omitting "um".

    An empty reference yields WER 0.0 for an empty hypothesis and 1.0 otherwise,
    rather than dividing by zero.
    """
    ref = normalise(reference, strip_disfluencies=strip_disfluencies)
    hyp = normalise(hypothesis, strip_disfluencies=strip_disfluencies)

    if not ref:
        return WerResult(0.0 if not hyp else 1.0, 0, 0, len(hyp), 0)

    # distance[i][j] = (cost, substitutions, deletions, insertions)
    previous: list[tuple[int, int, int, int]] = [(j, 0, 0, j) for j in range(len(hyp) + 1)]
    for i in range(1, len(ref) + 1):
        current: list[tuple[int, int, int, int]] = [(i, 0, i, 0)]
        for j in range(1, len(hyp) + 1):
            if ref[i - 1] == hyp[j - 1]:
                current.append(previous[j - 1])
                continue
            sub_cost, sub_s, sub_d, sub_i = previous[j - 1]
            del_cost, del_s, del_d, del_i = previous[j]
            ins_cost, ins_s, ins_d, ins_i = current[j - 1]
            best = min(
                (sub_cost + 1, sub_s + 1, sub_d, sub_i),
                (del_cost + 1, del_s, del_d + 1, del_i),
                (ins_cost + 1, ins_s, ins_d, ins_i + 1),
                key=lambda item: item[0],
            )
            current.append(best)
        previous = current

    cost, substitutions, deletions, insertions = previous[-1]
    return WerResult(cost / len(ref), substitutions, deletions, insertions, len(ref))


def _term_counts(tokens: list[str]) -> dict[str, int]:
    """Greedy longest-match count of medical terms in a token stream."""
    counts: dict[str, int] = {}
    index = 0
    while index < len(tokens):
        matched = False
        for window in range(min(_MAX_TERM_WORDS, len(tokens) - index), 0, -1):
            candidate = " ".join(tokens[index: index + window])
            if candidate in _MEDICAL_LEXICON:
                counts[candidate] = counts.get(candidate, 0) + 1
                index += window
                matched = True
                break
        if not matched:
            index += 1
    return counts


def medical_term_error_rate(reference: str, hypothesis: str) -> dict[str, float]:
    """Error rate restricted to clinically meaningful terms.

    Computed over multisets of matched terms: a term the reference mentions
    twice and the hypothesis once counts as one miss. Spurious terms the ASR
    invented count too, since a hallucinated drug name is worse than a dropped
    one.
    """
    reference_terms = _term_counts(normalise(reference))
    hypothesis_terms = _term_counts(normalise(hypothesis))

    total_reference = sum(reference_terms.values())
    missed = 0
    for term, count in reference_terms.items():
        missed += max(0, count - hypothesis_terms.get(term, 0))
    spurious = 0
    for term, count in hypothesis_terms.items():
        spurious += max(0, count - reference_terms.get(term, 0))

    if total_reference == 0:
        rate = 0.0 if spurious == 0 else 1.0
    else:
        rate = (missed + spurious) / total_reference

    return {
        "medical_term_error_rate": round(rate, 4),
        "medical_terms_in_reference": float(total_reference),
        "medical_terms_missed": float(missed),
        "medical_terms_spurious": float(spurious),
        "medical_term_recall": round(
            (total_reference - missed) / total_reference, 4
        ) if total_reference else 0.0,
    }
