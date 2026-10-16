"""Per-request vocabulary for biasing the speech recogniser.

Whisper conditions its decoding on an `initial_prompt`, which makes the words in
that prompt more likely to be produced. That is a real and useful lever, and it
was being pulled in the wrong direction: the prompt was a fixed sentence listing
"chest pain, palpitations, pericarditis, troponin, diabetes, HbA1c, metformin,
thrush" — the vocabulary of the two recordings the project was built around —
applied to every user's audio regardless of what their patient had.

The terms that actually help are the ones this *particular* encounter is likely
to contain. A clinician sees the same conditions and prescribes the same drugs
week after week, so their own history is a better predictor than any fixed list,
and it costs one indexed query.

Only the caller's own data is used. Nothing here reaches across users.
"""

from __future__ import annotations

from sqlalchemy import func
from sqlalchemy.orm import Session

import models

# Whisper's prompt window is limited and a long prompt starts crowding out the
# audio, so this keeps to the terms most likely to recur.
MAX_TERMS = 40

# Categories worth biasing toward. Drug names are the clear win — they are
# phonetically unusual, frequently mangled, and clinically costly to get wrong.
# Conditions help for the same reason. Symptoms are ordinary English and adding
# them mostly crowds the window.
BIASED_CATEGORIES = ("medication", "condition")


def build_vocabulary(db: Session, user_id: int, limit: int = MAX_TERMS) -> list[str]:
    """Terms this clinician's previous encounters actually contained.

    Ordered by how often each has appeared, so a drug seen in twenty
    consultations outranks one seen once. Returns an empty list for a new user,
    which leaves the decoder unbiased — the right default, since a wrong bias is
    worse than none.
    """
    rows = (
        db.query(
            models.MedicalEntity.text,
            func.count(models.MedicalEntity.id).label("mentions"),
        )
        .join(models.Transcription, models.MedicalEntity.transcription_id == models.Transcription.id)
        .filter(models.Transcription.user_id == user_id)
        .filter(models.MedicalEntity.ontology_system.isnot(None))
        .group_by(models.MedicalEntity.text)
        .order_by(func.count(models.MedicalEntity.id).desc())
        .limit(limit * 2)
        .all()
    )

    # Deduplicate case-insensitively, keeping the most frequent spelling.
    vocabulary: list[str] = []
    seen: set[str] = set()
    for text, _mentions in rows:
        term = (text or "").strip()
        key = term.lower()
        if not term or key in seen:
            continue
        seen.add(key)
        vocabulary.append(term)
        if len(vocabulary) >= limit:
            break

    return vocabulary


def specialty_terms(user) -> list[str]:
    """The clinician's specialty, if they recorded one.

    Deliberately just the specialty word rather than a curated term list per
    specialty: inventing "cardiology implies troponin, ECG, angina" would
    recreate the fixed-list problem one level up, with no evidence that the
    guesses help.
    """
    specialty = (getattr(user, "specialty", None) or "").strip()
    return [specialty] if specialty else []
