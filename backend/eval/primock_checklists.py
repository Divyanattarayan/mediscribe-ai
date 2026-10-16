"""Read PriMock57's clinician-authored consultation checklists.

The golden set needs reference annotations that were not produced by the same
machinery being measured. Annotating transcripts with our own extractor and then
scoring our extractor against those annotations measures self-agreement, not
correctness — recall would be near 1.0 by construction, because we cannot miss
what we never wrote down.

PriMock57 ships a checklist per consultation, authored by the clinicians who
designed the cases. It lists what was clinically present, rates each item
Critical / Non-Critical / Irrelevant, and — most usefully for the assertion
layer — states the explicit negatives ("No blood in stool", "no vomiting").
That is genuine external ground truth.

The files are .xlsx. They are unzipped and parsed directly rather than through
openpyxl: the format is a zip of XML, only two parts of it are needed, and a
dependency added for one script is a dependency every deployment carries.
"""

from __future__ import annotations

import html
import re
import zipfile
from dataclasses import dataclass
from pathlib import Path

# Columns holding checklist items, each paired with its criticality column.
ITEM_COLUMNS = {"A": "B", "C": "D"}

CRITICALITY = {"c": "critical", "nc": "non_critical", "i": "irrelevant"}

# Section headers that appear in the item column and are not clinical items.
_SECTION_HEADERS = {
    "checklist", "pc/hpc", "pmh", "dh", "fh", "sh", "ice", "examination",
    "management", "plan", "red flags", "differentials", "summary", "notes",
}

_TAG = re.compile(r"<[^>]+>")
_ROW = re.compile(r'<row[^>]*r="(\d+)"[^>]*>(.*?)</row>', re.S)
_CELL = re.compile(r'<c r="([A-Z]+)\d+"([^>]*)>(?:<v>(.*?)</v>)?')
_SHARED = re.compile(r"<si>(.*?)</si>", re.S)

# Leading markers the checklists use for sub-items, and the arrow used in the
# free-text note columns.
_ITEM_PREFIX = re.compile(r"^[*↳•\-\s]+")


@dataclass(frozen=True)
class ChecklistItem:
    text: str
    criticality: str

    @property
    def is_scored(self) -> bool:
        """Irrelevant items are explicitly marked as not clinically meaningful."""
        return self.criticality in ("critical", "non_critical")


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(_TAG.sub("", text))).strip()


def read_checklist(path: str | Path) -> list[ChecklistItem]:
    """Every scored clinical item in one consultation's checklist."""
    with zipfile.ZipFile(path) as archive:
        shared_xml = archive.read("xl/sharedStrings.xml").decode("utf-8", "replace")
        sheet_xml = archive.read("xl/worksheets/sheet1.xml").decode("utf-8", "replace")

    strings = [_clean(chunk) for chunk in _SHARED.findall(shared_xml)]

    def value_of(attributes: str, raw: str | None) -> str:
        if raw is None:
            return ""
        if 't="s"' in attributes and raw.isdigit() and int(raw) < len(strings):
            return strings[int(raw)]
        return _clean(raw)

    items: list[ChecklistItem] = []
    seen: set[str] = set()

    for _row_number, body in _ROW.findall(sheet_xml):
        cells = {
            column: value_of(attributes, raw)
            for column, attributes, raw in _CELL.findall(body)
        }
        for item_column, criticality_column in ITEM_COLUMNS.items():
            raw_item = cells.get(item_column, "")
            if not raw_item:
                continue

            text = _ITEM_PREFIX.sub("", raw_item).strip()
            if not text or text.lower() in _SECTION_HEADERS:
                continue

            criticality = CRITICALITY.get(cells.get(criticality_column, "").lower().strip(), "")
            if not criticality:
                continue

            key = text.lower()
            if key in seen:
                continue
            seen.add(key)
            items.append(ChecklistItem(text=text, criticality=criticality))

    return items


def checklist_paths(root: str | Path) -> dict[str, list[Path]]:
    """Map `day1_consultation01` style stems to their checklist files.

    The checklist filenames are prose ("Day 1 Consultation 1 - Checklist.xlsx")
    while everything else in the dataset uses the transcript stem, so the two
    have to be reconciled before they can be joined.

    A list rather than a single path because two clinicians annotated some of
    the same consultations. Keeping only one would throw away half the expert
    judgement available; their union is the better reference.
    """
    directory = Path(root) / "consultation_checklists"
    mapping: dict[str, list[Path]] = {}

    for path in sorted(directory.rglob("*.xlsx")):
        match = re.search(r"Day\s*(\d+)\s*Consultation\s*(\d+)", path.name, re.IGNORECASE)
        if not match:
            continue
        day, consultation = int(match.group(1)), int(match.group(2))
        mapping.setdefault(f"day{day}_consultation{consultation:02d}", []).append(path)

    return mapping


def read_consultation(paths: list[str | Path]) -> list[ChecklistItem]:
    """Union of every clinician's checklist for one consultation.

    Where two clinicians listed the same item, the more severe criticality wins:
    if either expert thought something was critical, treating it as critical is
    the safer reading.
    """
    severity = {"critical": 2, "non_critical": 1, "irrelevant": 0}
    best: dict[str, ChecklistItem] = {}

    for path in paths:
        for item in read_checklist(path):
            key = item.text.lower()
            existing = best.get(key)
            if existing is None or severity[item.criticality] > severity[existing.criticality]:
                best[key] = item

    return list(best.values())
