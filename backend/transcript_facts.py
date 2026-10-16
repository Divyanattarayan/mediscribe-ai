"""Shared transcript parsing helpers.

`soap_generator` and `clinical_extraction` both need to pull a date of birth and
the clinician's introduction out of the raw transcript. This module owns that
logic so the two callers cannot drift apart (they previously maintained two
near-identical copies with subtly different regexes).

Encounter-type classification also lives here. It used to be duplicated in both
callers, and both copies keyed off sentences lifted verbatim from two demo
recordings ("blood test said i had diabetes"). Those were removed in the Phase 0
de-overfitting pass; what remains is a generic marker-count classifier that is
only a *fallback* — `POST /api/transcribe` requires an `encounter_type` from the
caller, and that value is authoritative.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone

MONTH_NAME_TO_NUMBER = {
    "january": 1, "february": 2, "march": 3, "april": 4,
    "may": 5, "june": 6, "july": 7, "august": 8,
    "september": 9, "october": 10, "november": 11, "december": 12,
}

_NUMERIC_DOB = re.compile(r"(\d{1,2})[\/\.\-](\d{1,2})[\/\.\-](\d{4})")
_WORDY_DOB = re.compile(
    r"(\d{1,2})(?:st|nd|rd|th)?\s+of\s+(?:the\s+)?(\d{1,2}|[A-Za-z]+)(?:st|nd|rd|th)?[,]?\s+(\d{4})",
    flags=re.IGNORECASE,
)
_CLINICIAN_INTRO = re.compile(
    r"my name[' ]?s\s+([A-Z][a-z]+)[, ]+\s*i[' ]?m\s+(?:one of the\s+)?([^.,]+)",
    flags=re.IGNORECASE,
)


def parse_date_of_birth(transcription: str, *, now: datetime | None = None) -> tuple[str | None, int | None]:
    """Return ``(dob_as_DD/MM/YYYY, age_years)`` or ``(None, None)``.

    Age is only returned when it lands in a plausible 0–120 range.
    """
    match = _NUMERIC_DOB.search(transcription)
    if match:
        day, month, year = (int(g) for g in match.groups())
    else:
        words = _WORDY_DOB.search(transcription)
        if not words:
            return None, None
        day = int(words.group(1))
        token = words.group(2)
        month = int(token) if token.isdigit() else MONTH_NAME_TO_NUMBER.get(token.lower())
        year = int(words.group(3))

    if month is None or not (1 <= month <= 12):
        return None, None

    today = now or datetime.now(timezone.utc)
    dob = f"{day:02d}/{month:02d}/{year}"
    age = today.year - year - ((today.month, today.day) < (month, day))
    return dob, (age if 0 <= age <= 120 else None)


def parse_clinician(transcription: str) -> dict:
    """Return ``{"name": str|None, "role": str|None}`` from an introduction line."""
    match = _CLINICIAN_INTRO.search(transcription)
    if not match:
        return {"name": None, "role": None}

    role = match.group(2).strip()
    role = re.sub(r"\s+working\s+in\s+the\s+.*$", "", role, flags=re.IGNORECASE)
    role = role.replace("junior doctors", "junior doctor")
    return {"name": match.group(1).strip(), "role": role}


# Generic, encounter-shape markers. Deliberately free of any disease name: the
# classifier answers "what kind of consultation is this", not "what is wrong
# with the patient". Scored by marker count so no single phrase decides the
# outcome. Slated for replacement by a trained classifier (see MODEL_ROADMAP).
ENCOUNTER_MARKERS: dict[str, tuple[str, ...]] = {
    "medication_review": (
        "medication review", "medicines review", "repeat prescription",
        "review your tablets", "how are you getting on with the tablets",
        "still taking", "dose", "side effects",
    ),
    "counselling_education": (
        "does that make sense", "have a chat about", "talk you through",
        "explain what", "let me explain", "leaflet", "any questions about",
        "what do you understand", "summarise what we", "summarize what we",
    ),
    "acute_visit": (
        "came in today with", "started suddenly", "getting worse",
        "severe pain", "emergency", "urgent", "999", "a and e",
        "how long has it been going on", "on a scale of",
    ),
    "follow_up": (
        "follow up", "follow-up", "review appointment", "since we last",
        "last time you were", "how have you been since", "results are back",
    ),
}

DEFAULT_ENCOUNTER_TYPE = "follow_up"


def classify_encounter_type(transcription: str) -> str:
    """Best-effort encounter classification from generic consultation markers.

    Returns the type with the most marker hits, falling back to
    ``follow_up``. This is only used when the caller supplied no encounter
    type; the request-supplied value always wins.
    """
    text_lower = transcription.lower()
    scores = {
        encounter_type: sum(1 for marker in markers if marker in text_lower)
        for encounter_type, markers in ENCOUNTER_MARKERS.items()
    }
    best = max(scores, key=lambda key: scores[key])
    return best if scores[best] > 0 else DEFAULT_ENCOUNTER_TYPE
