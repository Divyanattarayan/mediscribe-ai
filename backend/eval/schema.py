"""Data contract for the evaluation harness.

One `EvalCase` is one clinical encounter with whatever ground truth we have for
it. Every field except `case_id` is optional, because the public datasets carry
different things: PriMock57 has audio + transcript + note, ACI-Bench has
dialogue + note but no audio, MTS-Dialog has dialogue + a single section.
Metrics that need a reference simply skip cases that lack one, and the run
report records how many cases each metric was actually computed over — an
average over three cases is not the same claim as an average over fifty.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterator

SOAP_SECTIONS = ("subjective", "objective", "assessment", "plan")


@dataclass
class EvalCase:
    case_id: str
    source: str                                   # dataset name, e.g. "primock57"
    audio_path: str | None = None                 # local file, if one exists
    audio_url: str | None = None                  # streamed on demand instead
    reference_transcript: str | None = None       # for ASR metrics / note input
    reference_note: dict[str, str] | None = None  # section name -> text
    reference_entities: list[dict[str, Any]] = field(default_factory=list)
    # Human-authored findings expected to appear in the note, each
    # {"text": ..., "criticality": ...}. Distinct from `reference_note`: these
    # are what a clinician said was present, not one clinician's phrasing of it.
    reference_items: list[dict[str, Any]] = field(default_factory=list)
    encounter_type: str = "follow_up"
    # Optional human rating (0-100) used to calibrate the LLM judge. Without
    # these, judge scores are uncalibrated numbers and must be reported as such.
    human_score: float | None = None
    notes: str = ""

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "EvalCase":
        known = {f: raw.get(f) for f in cls.__dataclass_fields__ if f in raw}
        known.setdefault("case_id", raw.get("id", ""))
        known.setdefault("source", "local")
        if known.get("reference_entities") is None:
            known["reference_entities"] = []
        return cls(**{k: v for k, v in known.items() if v is not None or k in ("audio_path", "reference_transcript", "reference_note", "human_score")})

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class CaseResult:
    """What the pipeline produced for one case, plus its per-case metrics."""

    case_id: str
    source: str
    hypothesis_transcript: str | None = None
    hypothesis_note: dict[str, str] | None = None
    hypothesis_entities: list[dict[str, Any]] = field(default_factory=list)
    metrics: dict[str, float] = field(default_factory=dict)
    details: dict[str, Any] = field(default_factory=dict)
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def load_cases(path: str | Path) -> list[EvalCase]:
    """Read a JSONL case file. Blank lines and `#` comment lines are ignored."""
    cases: list[EvalCase] = []
    for line in _iter_json_lines(Path(path)):
        cases.append(EvalCase.from_dict(line))
    return cases


def _iter_json_lines(path: Path) -> Iterator[dict[str, Any]]:
    with path.open(encoding="utf-8") as handle:
        for number, raw in enumerate(handle, start=1):
            stripped = raw.strip()
            if not stripped or stripped.startswith("#"):
                continue
            try:
                yield json.loads(stripped)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path}:{number} is not valid JSON: {exc}") from exc


def write_cases(cases: list[EvalCase], path: str | Path) -> None:
    with Path(path).open("w", encoding="utf-8") as handle:
        for case in cases:
            handle.write(json.dumps(case.to_dict(), ensure_ascii=False) + "\n")
