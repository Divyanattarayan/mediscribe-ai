"""Per-request decoder vocabulary.

The property that matters most here is isolation: the prompt is built from the
caller's own history, and one clinician's patients must never bias another's
transcription.
"""

import models
from decoder_vocabulary import build_vocabulary, specialty_terms
from transcription import build_initial_prompt


def _entity(text, system="RXNORM"):
    return {"text": text, "label": "CHEMICAL", "ontology_system": system}


def _seed(db_session, user_id, entities):
    transcription = models.Transcription(
        user_id=user_id, patient_id="PT-1", filename="a.mp3",
        transcription="t", medical_content_score=90.0, status="complete",
    )
    db_session.add(transcription)
    db_session.flush()
    for entity in entities:
        db_session.add(models.MedicalEntity(
            transcription_id=transcription.id,
            text=entity["text"], label=entity["label"], start=0, end=1,
            ontology_system=entity["ontology_system"],
        ))
    db_session.commit()


def test_a_new_clinician_gets_no_vocabulary(db_session, make_user):
    """An empty list leaves the decoder unbiased, which beats biasing it wrongly."""
    _token, user = make_user("new@example.com")
    assert build_vocabulary(db_session, user["id"]) == []


def test_terms_come_from_the_callers_own_encounters(db_session, make_user):
    _token, user = make_user("mine@example.com")
    _seed(db_session, user["id"], [_entity("amlodipine"), _entity("metformin")])

    vocabulary = build_vocabulary(db_session, user["id"])
    assert set(vocabulary) == {"amlodipine", "metformin"}


def test_another_clinicians_history_never_leaks(db_session, make_user):
    _token, mine = make_user("a@example.com")
    _token2, theirs = make_user("b@example.com")
    _seed(db_session, theirs["id"], [_entity("warfarin")])

    assert build_vocabulary(db_session, mine["id"]) == []


def test_frequent_terms_come_first(db_session, make_user):
    """A drug seen in twenty consultations is a better bet than one seen once."""
    _token, user = make_user("freq@example.com")
    _seed(db_session, user["id"], [_entity("rare")] + [_entity("common")] * 3)

    assert build_vocabulary(db_session, user["id"])[0] == "common"


def test_unlinked_entities_are_excluded(db_session, make_user):
    """Only terms an ontology resolved are trusted enough to bias decoding —
    otherwise a misrecognised word feeds itself back into the next encounter."""
    _token, user = make_user("unlinked@example.com")
    _seed(db_session, user["id"], [_entity("amlodipine"), _entity("wibble", system=None)])

    assert build_vocabulary(db_session, user["id"]) == ["amlodipine"]


def test_the_term_limit_is_respected(db_session, make_user):
    _token, user = make_user("many@example.com")
    _seed(db_session, user["id"], [_entity(f"drug{i}") for i in range(30)])

    assert len(build_vocabulary(db_session, user["id"], limit=5)) == 5


def test_specialty_is_used_only_when_recorded():
    assert specialty_terms(type("U", (), {"specialty": "Cardiology"})()) == ["Cardiology"]
    assert specialty_terms(type("U", (), {"specialty": None})()) == []
    assert specialty_terms(type("U", (), {"specialty": "   "})()) == []


# ── Prompt construction ───────────────────────────────────────────────────────

def test_a_clinician_with_no_history_still_gets_the_generic_framing():
    """Removing the prompt entirely measured worst of every variant tried, so
    the fallback is condition-neutral clinical framing rather than nothing."""
    from transcription import DEFAULT_INITIAL_PROMPT

    assert build_initial_prompt([]) == DEFAULT_INITIAL_PROMPT
    assert build_initial_prompt(None) == DEFAULT_INITIAL_PROMPT
    # And it names no diagnosis, which is the whole point.
    for condition in ("pericarditis", "diabetes", "chest pain", "troponin"):
        assert condition not in DEFAULT_INITIAL_PROMPT.lower()


def test_vocabulary_extends_the_framing_rather_than_replacing_it():
    from transcription import DEFAULT_INITIAL_PROMPT

    prompt = build_initial_prompt(["amlodipine"])
    assert prompt.startswith(DEFAULT_INITIAL_PROMPT)
    assert "amlodipine" in prompt


def test_a_prompt_lists_the_supplied_terms():
    prompt = build_initial_prompt(["amlodipine", "atorvastatin"])
    assert "amlodipine" in prompt and "atorvastatin" in prompt


def test_duplicate_terms_are_collapsed():
    prompt = build_initial_prompt(["Amlodipine", "amlodipine", "AMLODIPINE"])
    assert prompt.lower().count("amlodipine") == 1


def test_blank_terms_are_ignored():
    from transcription import DEFAULT_INITIAL_PROMPT

    assert build_initial_prompt(["", "   ", None]) == DEFAULT_INITIAL_PROMPT
