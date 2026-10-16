"""Adapters that turn public benchmarks into `EvalCase` records.

None of these datasets are vendored — they carry their own licences and some
require a data-use agreement. Each adapter reads from a local directory the
user has downloaded themselves; `eval/README.md` has the retrieval steps.

Coverage differs by dataset, and that difference is the point of having three:

| dataset          | audio | transcript | reference note | what it measures       |
|------------------|-------|------------|----------------|------------------------|
| primock57        | yes   | yes        | no             | ASR, per audio channel |
| primock57_notes  | no    | yes        | yes            | note generation        |
| aci_bench        | no    | yes        | yes (4 section)| note generation only   |
| mts_dialog       | no    | yes        | yes (1 section)| section-level accuracy |

PriMock57 supplies both suites from one download: the per-channel audio scores
ASR, and the same transcripts merged by timing score note generation against the
clinician's own note.

The data directory defaults to `eval/data/` but is overridable with
`MEDISCRIBE_EVAL_DATA`. Point it outside a cloud-synced folder: PriMock57 is
~1.9 GB of audio in full, which is not something to sync to OneDrive.
"""

from __future__ import annotations

import csv
import json
import os
from pathlib import Path
from typing import Callable, Iterator

from eval.audio_source import primock57_audio_url
from eval.primock_checklists import checklist_paths, read_consultation
from eval.schema import EvalCase, load_cases
from eval.textgrid import merge_channels, transcript_text

DATA_ROOT = Path(os.getenv("MEDISCRIBE_EVAL_DATA", Path(__file__).resolve().parent / "data"))


def _require(directory: Path, dataset: str) -> Path:
    if not directory.exists():
        raise FileNotFoundError(
            f"{dataset} not found at {directory}. See backend/eval/README.md for how to obtain it."
        )
    return directory


def load_local(path: str | Path | None = None) -> list[EvalCase]:
    """Our own golden set: hand-checked cases in JSONL."""
    target = Path(path) if path else Path(__file__).resolve().parent / "cases" / "golden.jsonl"
    if not target.exists():
        raise FileNotFoundError(f"No case file at {target}.")
    return load_cases(target)


def load_primock57(root: str | Path | None = None) -> list[EvalCase]:
    """PriMock57 as an ASR suite: one case per audio channel.

    The dataset records the doctor and the patient on separate tracks
    (`day1_consultation01_doctor.wav` / `..._patient.wav`) with a matching
    TextGrid per track. Scoring per channel keeps the comparison exact: our ASR
    runs on one file and is scored against the manual transcript of that same
    file, with no alignment step in between to blur the result.

    Consultation-level dialogue lives in `load_primock57_notes` instead, built
    from the transcript timings rather than from our own output.

    CC BY 4.0 (Babylon Health). Attribution required if results are published.
    """
    base = _require(Path(root) if root else DATA_ROOT / "primock57", "primock57")
    audio_dir, transcript_dir = base / "audio", base / "transcripts"

    # Cases are enumerated from the transcripts, not the audio directory: the
    # transcripts are a few hundred KB each and worth keeping, while the audio
    # is streamed per file and discarded (see eval/audio_source.py). A local
    # copy is used when one happens to exist.
    cases: list[EvalCase] = []
    for transcript_path in sorted(transcript_dir.glob("*.TextGrid")):
        stem = transcript_path.stem
        local_audio_path = audio_dir / f"{stem}.wav"
        has_local_audio = local_audio_path.exists() and local_audio_path.stat().st_size > 10_000
        cases.append(EvalCase(
            case_id=f"primock57/{stem}",
            source="primock57",
            audio_path=str(local_audio_path) if has_local_audio else None,
            audio_url=primock57_audio_url(f"{stem}.wav"),
            reference_transcript=transcript_text(transcript_path),
            notes="channel-level ASR case; <UNIN/> removed, <UNSURE> markers stripped",
        ))
    return cases


def load_primock57_notes(root: str | Path | None = None) -> list[EvalCase]:
    """PriMock57 as a note-generation suite: one case per consultation.

    The reference transcript is the two channels merged by utterance start
    time, so the pipeline sees the dialogue as it actually happened, and the
    reference note is the clinician's own note for that consultation. No audio
    is used — note quality is measured independently of ASR error.
    """
    base = _require(Path(root) if root else DATA_ROOT / "primock57", "primock57")
    transcript_dir, note_dir = base / "transcripts", base / "notes"

    # Clinician-authored checklists exist for a subset of consultations. They
    # are the only external ground truth in the dataset for *what should be in
    # the note*, as opposed to one clinician's phrasing of it.
    checklists = checklist_paths(base)

    cases: list[EvalCase] = []
    for doctor_path in sorted(transcript_dir.glob("*_doctor.TextGrid")):
        stem = doctor_path.stem.replace("_doctor", "")
        patient_path = transcript_dir / f"{stem}_patient.TextGrid"
        note_path = note_dir / f"{stem}.json"
        if not patient_path.exists() or not note_path.exists():
            continue

        payload = json.loads(note_path.read_text(encoding="utf-8"))
        items = [
            {"text": item.text, "criticality": item.criticality}
            for item in read_consultation(checklists.get(stem, []))
        ] if stem in checklists else []
        cases.append(EvalCase(
            case_id=f"primock57-notes/{stem}",
            source="primock57_notes",
            reference_transcript=merge_channels(doctor_path, patient_path),
            reference_note={"note": payload.get("note", "")},
            encounter_type="acute_visit",
            reference_items=items,
            notes=str(payload.get("presenting_complaint", "")),
        ))
    return cases


def load_aci_bench(root: str | Path | None = None) -> list[EvalCase]:
    """ACI-Bench: dialogue → four-section clinical note.

    Expects the released CSVs with `dataset`, `encounter_id`, `dialogue` and
    `note` columns.
    """
    base = _require(Path(root) if root else DATA_ROOT / "aci_bench", "aci_bench")
    cases: list[EvalCase] = []
    for csv_path in sorted(base.glob("*.csv")):
        with csv_path.open(encoding="utf-8", newline="") as handle:
            for row in csv.DictReader(handle):
                dialogue = row.get("dialogue") or row.get("src")
                note = row.get("note") or row.get("tgt")
                if not dialogue:
                    continue
                identifier = row.get("encounter_id") or row.get("id") or f"{csv_path.stem}-{len(cases)}"
                cases.append(EvalCase(
                    case_id=f"aci_bench/{identifier}",
                    source="aci_bench",
                    reference_transcript=dialogue,
                    reference_note={"note": note} if note else None,
                ))
    return cases


def load_mts_dialog(root: str | Path | None = None) -> list[EvalCase]:
    """MTS-Dialog: short dialogue → one clinical section.

    Section-scoped, so it is the right suite for testing whether content lands
    in the correct SOAP section rather than whether a whole note is any good.
    """
    base = _require(Path(root) if root else DATA_ROOT / "mts_dialog", "mts_dialog")
    cases: list[EvalCase] = []
    for csv_path in sorted(base.glob("*.csv")):
        with csv_path.open(encoding="utf-8", newline="") as handle:
            for row in csv.DictReader(handle):
                dialogue = row.get("dialogue")
                summary = row.get("section_text")
                if not dialogue:
                    continue
                identifier = row.get("ID") or f"{csv_path.stem}-{len(cases)}"
                cases.append(EvalCase(
                    case_id=f"mts_dialog/{identifier}",
                    source="mts_dialog",
                    reference_transcript=dialogue,
                    reference_note={str(row.get("section_header", "note")).lower(): summary} if summary else None,
                    notes=f"section={row.get('section_header', '')}",
                ))
    return cases


def _read_first(directory: Path, stem: str, suffixes: tuple[str, ...]) -> str | None:  # noqa: F811
    for suffix in suffixes:
        candidate = directory / f"{stem}{suffix}"
        if not candidate.exists():
            continue
        text = candidate.read_text(encoding="utf-8")
        if suffix == ".json":
            payload = json.loads(text)
            if isinstance(payload, dict):
                return payload.get("text") or payload.get("transcript") or json.dumps(payload)
            return str(payload)
        return text
    return None


SUITES: dict[str, Callable[[], list[EvalCase]]] = {
    "local": load_local,
    "primock57": load_primock57,
    "primock57_notes": load_primock57_notes,
    "aci_bench": load_aci_bench,
    "mts_dialog": load_mts_dialog,
}


def load_suite(name: str) -> list[EvalCase]:
    if name not in SUITES:
        raise KeyError(f"Unknown suite '{name}'. Available: {', '.join(sorted(SUITES))}")
    return SUITES[name]()


def iter_suites() -> Iterator[str]:
    return iter(sorted(SUITES))
