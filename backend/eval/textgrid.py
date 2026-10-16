"""Minimal Praat TextGrid reader for the PriMock57 transcripts.

PriMock57 ships manual transcripts as TextGrid interval tiers: one interval per
utterance, each with a start time, an end time and the transcribed text. That is
all we need, so this parses the handful of fields it uses rather than pulling in
a TextGrid library — the format is stable and the parser is twenty lines.

The transcripts carry two annotation tags:

    <UNSURE>text</UNSURE>   the transcriber was unsure of the words
    <UNIN/>                 an unintelligible stretch of audio

`<UNSURE>` markers are stripped and the text kept: the transcriber's best guess
is still the best reference available. `<UNIN/>` is removed entirely — there is
no reference text for it, so scoring against it would charge the ASR for words
no human could make out. Both choices are lossy, and both are stated in the run
report so a WER figure from this harness can be compared like for like.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

_INTERVAL = re.compile(
    r"intervals\s*\[\d+\]:\s*"
    r"xmin\s*=\s*([\d.eE+-]+)\s*"
    r"xmax\s*=\s*([\d.eE+-]+)\s*"
    r'text\s*=\s*"((?:[^"]|"")*)"',
    flags=re.DOTALL,
)
_TIER_NAME = re.compile(r'name\s*=\s*"([^"]*)"')

_UNSURE = re.compile(r"</?UNSURE>", flags=re.IGNORECASE)
_UNINTELLIGIBLE = re.compile(r"<UNIN\s*/?>", flags=re.IGNORECASE)
_WHITESPACE = re.compile(r"\s+")


@dataclass(frozen=True)
class Utterance:
    start: float
    end: float
    text: str
    speaker: str = ""


def clean_transcript_text(text: str) -> str:
    """Strip PriMock57 annotation tags and normalise whitespace."""
    text = _UNINTELLIGIBLE.sub(" ", text)
    text = _UNSURE.sub(" ", text)
    return _WHITESPACE.sub(" ", text.replace('""', '"')).strip()


def read_textgrid(path: str | Path) -> list[Utterance]:
    """Return the non-empty utterances of a TextGrid, in time order."""
    # TextGrid files are written as UTF-8 or UTF-16 depending on the tool that
    # produced them; PriMock57 uses UTF-8, but fall back rather than raise.
    raw = Path(path)
    try:
        content = raw.read_text(encoding="utf-8")
    except UnicodeDecodeError:  # pragma: no cover - defensive
        content = raw.read_text(encoding="utf-16")

    tier_match = _TIER_NAME.search(content)
    speaker = tier_match.group(1) if tier_match else ""

    utterances = []
    for start, end, text in _INTERVAL.findall(content):
        cleaned = clean_transcript_text(text)
        if cleaned:
            utterances.append(Utterance(float(start), float(end), cleaned, speaker))
    return utterances


def transcript_text(path: str | Path) -> str:
    """The whole channel as one string, utterances joined in time order."""
    return " ".join(utterance.text for utterance in read_textgrid(path))


def merge_channels(*paths: str | Path) -> str:
    """Interleave separate speaker channels into one speaker-labelled dialogue.

    PriMock57 records the doctor and the patient on separate tracks, so the
    conversation only exists once the two are merged by utterance start time.
    The result is labelled dialogue of the same shape the pipeline sees in
    production, which is what makes note generation measurable against the
    clinician's own note.
    """
    utterances: list[Utterance] = []
    for path in paths:
        utterances.extend(read_textgrid(path))
    utterances.sort(key=lambda utterance: utterance.start)

    lines = []
    for utterance in utterances:
        speaker = utterance.speaker.strip() or "Speaker"
        lines.append(f"{speaker}: {utterance.text}")
    return "\n".join(lines)
