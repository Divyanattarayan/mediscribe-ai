"""End-to-end happy path for POST /api/transcribe with the pipeline stubbed.

Guards against regressions in the endpoint's own orchestration/persistence
logic (the ML steps are replaced with canned returns).
"""

import io

import main
import models
from tests.conftest import auth_header


def _stub_full_pipeline(monkeypatch, *, duration=132.0):
    monkeypatch.setattr(
        main, "transcribe_audio",
        lambda *a, **k: {
            "success": True,
            "text": "patient reports chest pain radiating to the left arm",
            "duration": duration,
            "confidence": 0.91,
            "words": [],
            "language": "en",
            "error": None,
        },
    )
    monkeypatch.setattr(
        main, "correct_medical_spelling",
        lambda text, **k: (text, []),
    )
    monkeypatch.setattr(
        main, "validate_medical_content",
        lambda *a, **k: {"is_valid": True, "confidence_score": 0.82, "reason": "ok", "details": {}},
    )
    monkeypatch.setattr(
        main, "extract_medical_entities",
        lambda *a, **k: {
            "total_entities": 1,
            "category_counts": {"symptoms": 1},
            "categorized": {"symptoms": [{"text": "chest pain"}]},
            "entities": [{"text": "chest pain", "label": "SYMPTOM", "confidence": 0.0, "start": 16, "end": 26}],
        },
    )
    monkeypatch.setattr(main, "extract_clinical_representation", lambda *a, **k: {"encounter": {"type": "acute_visit"}})
    monkeypatch.setattr(main, "build_fact_table", lambda *a, **k: [])
    monkeypatch.setattr(main, "fact_table_summary", lambda *a, **k: {"total": 0})
    monkeypatch.setattr(main, "facts_to_json", lambda *a, **k: [])
    monkeypatch.setattr(
        main, "generate_soap_note",
        lambda *a, **k: {
            "subjective": "S", "objective": "O", "assessment": "A", "plan": "P",
            "source": "groq-llama-3.3-70b-versatile",
        },
    )
    monkeypatch.setattr(main, "format_soap_note_text", lambda note: "S\nO\nA\nP")


def test_successful_transcribe_persists_a_row(client, make_user, db_session, monkeypatch):
    _stub_full_pipeline(monkeypatch)
    token, user = make_user("clinician@example.com")

    files = {"file": ("visit.mp3", io.BytesIO(b"\x00" * 128), "audio/mpeg")}
    response = client.post(
        "/api/transcribe",
        headers=auth_header(token),
        files=files,
        data={"encounter_type": "acute_visit"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["success"] is True
    assert body["filename"] == "visit.mp3"

    rows = db_session.query(models.Transcription).all()
    assert len(rows) == 1
    row = rows[0]
    assert row.user_id == user["id"]
    assert row.duration == "2:12"                 # from the real 132.0s duration
    assert row.patient_id.startswith("PT-")
    assert row.patient_id[3:].isdigit() and len(row.patient_id[3:]) == 8
    assert row.soap_note.source == "groq-llama-3.3-70b-versatile"


def test_short_real_audio_is_rejected_even_if_header_lies(client, make_user, monkeypatch):
    """Header says 999s, decoded audio is 10s → rejected on the authoritative value."""
    _stub_full_pipeline(monkeypatch, duration=10.0)
    token, _ = make_user()

    files = {"file": ("short.mp3", io.BytesIO(b"\x00" * 128), "audio/mpeg")}
    response = client.post(
        "/api/transcribe",
        headers={**auth_header(token), "X-Audio-Duration-Seconds": "999"},
        files=files,
        data={"encounter_type": "acute_visit"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["success"] is False
    assert "too short" in body["message"].lower()
