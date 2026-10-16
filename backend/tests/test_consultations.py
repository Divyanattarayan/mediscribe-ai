"""Tests for MediScribe AI Consultation API endpoints.

Covers:
- GET /health and GET /api/health
- POST /api/consultations/upload (valid, invalid extension, empty, oversized, auth)
- POST /api/consultations/{id}/transcribe (503 when STT service unconfigured)
- GET and PUT /api/consultations/{id}/transcript (retrieval, editing, validation)
- POST /api/consultations/{id}/extract (medical NLP extraction)
- POST and PUT /api/consultations/{id}/soap (generation, editing, validation)
- POST /api/consultations/{id}/approve (clinical approval workflow, state guards)
- GET /api/consultations and GET /api/consultations/{id} (list, detail, user scoping)
"""

import io
import pytest
import models
from tests.conftest import auth_header


# ── Health checks ─────────────────────────────────────────────────────────────

def test_health_checks(client):
    r1 = client.get("/health")
    assert r1.status_code == 200
    data1 = r1.json()
    assert data1["status"] == "healthy"
    assert "service" in data1
    assert "secret" not in str(data1).lower()

    r2 = client.get("/api/health")
    assert r2.status_code == 200
    data2 = r2.json()
    assert data2["status"] == "healthy"
    assert "version" in data2
    assert "speech_recognition_configured" in data2
    assert "llm_configured" in data2
    assert "nlp_configured" in data2
    # Ensure no secrets leak
    assert "password" not in str(data2).lower()
    assert "key" not in str(data2).lower() or "configured" in str(data2).lower()


# ── Audio upload ──────────────────────────────────────────────────────────────

def test_upload_valid_audio(client, make_user):
    token, user = make_user()
    audio_data = b"RIFF....WAVEfmt ...."

    response = client.post(
        "/api/consultations/upload",
        files={"file": ("test_audio.wav", io.BytesIO(audio_data), "audio/wav")},
        data={"title": "Follow-up Cardiology Visit"},
        headers=auth_header(token),
    )

    assert response.status_code == 201
    data = response.json()
    assert data["id"] > 0
    assert data["patient_id"].startswith("PT-")
    assert data["title"] == "Follow-up Cardiology Visit"
    assert data["filename"] == "test_audio.wav"
    assert data["status"] == "uploaded"
    assert data["review_status"] == "draft"


def test_upload_invalid_extension(client, make_user):
    token, _ = make_user()
    response = client.post(
        "/api/consultations/upload",
        files={"file": ("notes.txt", io.BytesIO(b"clinical notes"), "text/plain")},
        headers=auth_header(token),
    )
    assert response.status_code == 400
    assert "Unsupported file format" in response.json()["detail"]


def test_upload_empty_audio(client, make_user):
    token, _ = make_user()
    response = client.post(
        "/api/consultations/upload",
        files={"file": ("empty.mp3", io.BytesIO(b""), "audio/mpeg")},
        headers=auth_header(token),
    )
    assert response.status_code == 400
    assert "empty" in response.json()["detail"].lower()


def test_upload_oversized_audio(client, make_user):
    token, _ = make_user()
    # 51 MB mock payload
    oversized = b"x" * (51 * 1024 * 1024)
    response = client.post(
        "/api/consultations/upload",
        files={"file": ("large.wav", io.BytesIO(oversized), "audio/wav")},
        headers=auth_header(token),
    )
    assert response.status_code == 413
    assert "exceeds" in response.json()["detail"].lower()


def test_upload_requires_auth(client):
    response = client.post(
        "/api/consultations/upload",
        files={"file": ("test.wav", io.BytesIO(b"audio"), "audio/wav")},
    )
    assert response.status_code == 401


# ── Transcription endpoint ───────────────────────────────────────────────────

def test_transcribe_unconfigured_service_returns_503(client, make_user):
    token, _ = make_user()
    # Upload first
    upload_res = client.post(
        "/api/consultations/upload",
        files={"file": ("consultation.mp3", io.BytesIO(b"fake audio data"), "audio/mpeg")},
        headers=auth_header(token),
    )
    consultation_id = upload_res.json()["id"]

    # In test environment, faster-whisper is stubbed with _StubWhisperModel
    res = client.post(
        f"/api/consultations/{consultation_id}/transcribe",
        headers=auth_header(token),
    )
    assert res.status_code == 503
    assert "Speech recognition service" in res.json()["detail"]


def test_transcribe_unknown_consultation_is_404(client, make_user):
    token, _ = make_user()
    res = client.post("/api/consultations/999999/transcribe", headers=auth_header(token))
    assert res.status_code == 404


# ── Transcript retrieval and editing ──────────────────────────────────────────

def test_transcript_get_and_update(client, make_user, db_session):
    token, user = make_user()

    consultation = models.Transcription(
        user_id=user["id"],
        patient_id="PT-12345",
        filename="rec.mp3",
        transcription="Patient presents with persistent cough and mild dyspnea.",
        medical_content_score=80.0,
        status="transcribed",
        review_status="draft",
    )
    db_session.add(consultation)
    db_session.commit()
    db_session.refresh(consultation)

    # GET transcript
    get_res = client.get(
        f"/api/consultations/{consultation.id}/transcript",
        headers=auth_header(token),
    )
    assert get_res.status_code == 200
    assert get_res.json()["transcription"] == "Patient presents with persistent cough and mild dyspnea."

    # PUT update transcript
    new_text = "Patient presents with persistent productive cough and moderate dyspnea for 3 days."
    put_res = client.put(
        f"/api/consultations/{consultation.id}/transcript",
        json={"transcription": new_text},
        headers=auth_header(token),
    )
    assert put_res.status_code == 200
    assert put_res.json()["transcription"] == new_text

    # Verify updated in DB
    db_session.expire_all()
    refreshed = db_session.get(models.Transcription, consultation.id)
    assert refreshed.transcription == new_text



def test_transcript_update_empty_text_returns_422(client, make_user, db_session):
    token, user = make_user()
    consultation = models.Transcription(
        user_id=user["id"],
        patient_id="PT-12345",
        filename="rec.mp3",
        transcription="Original transcript",
        status="transcribed",
        review_status="draft",
    )
    db_session.add(consultation)
    db_session.commit()

    res = client.put(
        f"/api/consultations/{consultation.id}/transcript",
        json={"transcription": "   "},
        headers=auth_header(token),
    )
    assert res.status_code == 422


# ── Medical NLP entity extraction ─────────────────────────────────────────────

def test_extract_without_transcript_returns_422(client, make_user, db_session):
    token, user = make_user()
    consultation = models.Transcription(
        user_id=user["id"],
        patient_id="PT-12345",
        filename="rec.mp3",
        transcription="",
        status="uploaded",
        review_status="draft",
    )
    db_session.add(consultation)
    db_session.commit()

    res = client.post(
        f"/api/consultations/{consultation.id}/extract",
        headers=auth_header(token),
    )
    assert res.status_code == 422


def test_extract_entities_success(client, make_user, db_session):
    token, user = make_user()
    consultation = models.Transcription(
        user_id=user["id"],
        patient_id="PT-12345",
        filename="rec.mp3",
        transcription="Patient was prescribed metformin for diabetes and reports chest pain.",
        status="transcribed",
        review_status="draft",
    )
    db_session.add(consultation)
    db_session.commit()

    res = client.post(
        f"/api/consultations/{consultation.id}/extract",
        headers=auth_header(token),
    )
    assert res.status_code == 200
    data = res.json()
    assert data["consultation_id"] == consultation.id
    assert "entities" in data
    assert "category_counts" in data


# ── SOAP note generation and editing ─────────────────────────────────────────

def test_soap_generation_without_transcript_is_422(client, make_user, db_session):
    token, user = make_user()
    consultation = models.Transcription(
        user_id=user["id"],
        patient_id="PT-12345",
        filename="rec.mp3",
        transcription="",
        status="uploaded",
        review_status="draft",
    )
    db_session.add(consultation)
    db_session.commit()

    res = client.post(
        f"/api/consultations/{consultation.id}/soap",
        headers=auth_header(token),
    )
    assert res.status_code == 422


def test_soap_generation_and_editing(client, make_user, db_session, monkeypatch):
    token, user = make_user()
    consultation = models.Transcription(
        user_id=user["id"],
        patient_id="PT-12345",
        filename="rec.mp3",
        transcription="Patient has hypertension and takes lisinopril. Experiencing mild headaches.",
        status="transcribed",
        review_status="draft",
    )
    db_session.add(consultation)
    db_session.commit()

    # Mock external Groq generation call
    mock_soap = {
        "subjective": "Patient reports mild headaches. History of hypertension, currently on lisinopril.",
        "objective": "Not documented",
        "assessment": "Hypertension with tension headaches.",
        "plan": "Continue lisinopril as prescribed. Monitor BP at home.",
        "review_flags": ["Objective section lacks physical examination or vital signs documentation."],
        "source": "groq-llama-3.3-70b-versatile",
        "is_draft": True,
        "disclaimer": "AI-generated clinical draft. Requires clinician review, editing, and approval before signing.",
    }
    from soap_generation_service import soap_generation_service
    monkeypatch.setattr(soap_generation_service, "generate_soap_note", lambda **kwargs: mock_soap)

    # Generate SOAP
    gen_res = client.post(
        f"/api/consultations/{consultation.id}/soap",
        headers=auth_header(token),
    )
    assert gen_res.status_code == 200
    soap = gen_res.json()
    assert soap["subjective"] is not None
    assert soap["objective"] is not None
    assert soap["assessment"] is not None
    assert soap["plan"] is not None
    assert soap["review_status"] == "needs_review"
    assert soap["is_draft"] is True
    assert len(soap["review_flags"]) > 0

    # Edit SOAP
    edit_payload = {
        "subjective": "Patient reports bilateral throbbing headache for 2 days. Denies visual changes.",
        "objective": "BP 138/86 mmHg, heart rate 72 bpm regular. Neurological exam normal.",
        "assessment": "Essential hypertension with tension headache.",
        "plan": "Continue lisinopril 10mg daily. Hydration and rest. Return if pain worsens.",
    }
    edit_res = client.put(
        f"/api/consultations/{consultation.id}/soap",
        json=edit_payload,
        headers=auth_header(token),
    )
    assert edit_res.status_code == 200
    edited = edit_res.json()
    assert edited["subjective"] == edit_payload["subjective"]
    assert edited["assessment"] == edit_payload["assessment"]


def test_soap_editing_empty_section_returns_422(client, make_user, db_session):
    token, user = make_user()
    consultation = models.Transcription(
        user_id=user["id"],
        patient_id="PT-12345",
        filename="rec.mp3",
        transcription="Some transcript",
        status="transcribed",
        review_status="draft",
    )
    db_session.add(consultation)
    db_session.commit()

    invalid_payload = {
        "subjective": "Subjective text",
        "objective": "   ",  # blank objective
        "assessment": "Assessment text",
        "plan": "Plan text",
    }
    res = client.put(
        f"/api/consultations/{consultation.id}/soap",
        json=invalid_payload,
        headers=auth_header(token),
    )
    assert res.status_code == 422


# ── Clinical approval workflow ────────────────────────────────────────────────

def test_approve_requires_complete_soap_note(client, make_user, db_session):
    token, user = make_user()
    consultation = models.Transcription(
        user_id=user["id"],
        patient_id="PT-12345",
        filename="rec.mp3",
        transcription="Patient transcript",
        status="transcribed",
        review_status="draft",
    )
    db_session.add(consultation)
    db_session.commit()

    # Try approve with no SOAP note at all
    res = client.post(
        f"/api/consultations/{consultation.id}/approve",
        json={"approved_by": "Dr. Smith, MD"},
        headers=auth_header(token),
    )
    assert res.status_code == 422
    assert "SOAP note has not been generated" in res.json()["detail"]


def test_approve_happy_path_and_guards(client, make_user, db_session):
    token, user = make_user()
    consultation = models.Transcription(
        user_id=user["id"],
        patient_id="PT-12345",
        filename="rec.mp3",
        transcription="Full consultation transcript",
        status="transcribed",
        review_status="needs_review",
    )
    db_session.add(consultation)
    db_session.commit()

    soap = models.SoapNote(
        transcription_id=consultation.id,
        subjective="Symptom details.",
        objective="Vitals normal.",
        assessment="Acute bronchitis.",
        plan="Supportive care and fluids.",
        source="rule-based-fallback",
    )
    db_session.add(soap)
    db_session.commit()

    # Approve
    approve_res = client.post(
        f"/api/consultations/{consultation.id}/approve",
        json={"approved_by": "Dr. Sarah Connor, MD", "approval_notes": "Reviewed and verified."},
        headers=auth_header(token),
    )
    assert approve_res.status_code == 200
    app_data = approve_res.json()
    assert app_data["review_status"] == "approved"
    assert app_data["approved_by"] == "Dr. Sarah Connor, MD"
    assert app_data["approved_at"] is not None

    # Cannot approve again (409 Conflict)
    reapprove_res = client.post(
        f"/api/consultations/{consultation.id}/approve",
        json={"approved_by": "Dr. Sarah Connor, MD"},
        headers=auth_header(token),
    )
    assert reapprove_res.status_code == 409
    assert "already approved" in reapprove_res.json()["detail"]

    # Cannot edit transcript once approved (409 Conflict)
    edit_trans = client.put(
        f"/api/consultations/{consultation.id}/transcript",
        json={"transcription": "Changed transcript"},
        headers=auth_header(token),
    )
    assert edit_trans.status_code == 409

    # Cannot edit SOAP once approved (409 Conflict)
    edit_soap = client.put(
        f"/api/consultations/{consultation.id}/soap",
        json={
            "subjective": "Subj",
            "objective": "Obj",
            "assessment": "Assess",
            "plan": "Plan",
        },
        headers=auth_header(token),
    )
    assert edit_soap.status_code == 409


# ── Consultations listing and scoping ─────────────────────────────────────────

def test_consultations_list_and_detail(client, make_user, db_session):
    token_a, user_a = make_user("dr_a@example.com")
    token_b, user_b = make_user("dr_b@example.com")

    # Dr A record
    c_a = models.Transcription(
        user_id=user_a["id"],
        patient_id="PT-A0001",
        title="Dr A Patient",
        filename="a.wav",
        transcription="Dr A transcript",
        status="transcribed",
        review_status="approved",
    )
    # Dr B record
    c_b = models.Transcription(
        user_id=user_b["id"],
        patient_id="PT-B0001",
        title="Dr B Patient",
        filename="b.wav",
        transcription="Dr B transcript",
        status="uploaded",
        review_status="draft",
    )
    db_session.add_all([c_a, c_b])
    db_session.commit()

    # Dr A listing should only include Dr A's consultation
    list_res = client.get("/api/consultations", headers=auth_header(token_a))
    assert list_res.status_code == 200
    rows = list_res.json()
    assert len(rows) == 1
    assert rows[0]["patient_id"] == "PT-A0001"
    assert rows[0]["title"] == "Dr A Patient"

    # Dr A can get own detail
    detail_res = client.get(f"/api/consultations/{c_a.id}", headers=auth_header(token_a))
    assert detail_res.status_code == 200
    assert detail_res.json()["patient_id"] == "PT-A0001"

    # Dr A cannot access Dr B's consultation
    forbidden_res = client.get(f"/api/consultations/{c_b.id}", headers=auth_header(token_a))
    assert forbidden_res.status_code == 404


# ── Audio cleanup & deletion tests ────────────────────────────────────────────

def test_delete_consultation_removes_audio_and_record(client, make_user, db_session, tmp_path):
    token, user = make_user("del_doc@example.com")
    import os
    from pathlib import Path

    # Create dummy audio file inside uploads/consultations
    uploads_dir = Path("uploads/consultations")
    uploads_dir.mkdir(parents=True, exist_ok=True)
    test_audio = uploads_dir / "unit_test_audio_delete.wav"
    test_audio.write_bytes(b"dummy wav data for deletion test")
    assert test_audio.exists()

    consultation = models.Transcription(
        user_id=user["id"],
        patient_id="PT-DEL01",
        title="Deletion Test",
        filename="test.wav",
        transcription="Ready to be deleted",
        status="uploaded",
        review_status="draft",
        audio_path=str(test_audio),
    )
    db_session.add(consultation)
    db_session.commit()
    db_session.refresh(consultation)

    c_id = consultation.id

    # Delete consultation
    res = client.delete(f"/api/consultations/{c_id}", headers=auth_header(token))
    assert res.status_code == 204

    # Verify DB record is gone
    check_db = db_session.query(models.Transcription).filter(models.Transcription.id == c_id).first()
    assert check_db is None

    # Verify audio file was safely removed from disk
    assert not test_audio.exists()


def test_delete_consultation_audio_only(client, make_user, db_session):
    token, user = make_user("purge_doc@example.com")
    from pathlib import Path

    uploads_dir = Path("uploads/consultations")
    uploads_dir.mkdir(parents=True, exist_ok=True)
    test_audio = uploads_dir / "unit_test_audio_purge_only.wav"
    test_audio.write_bytes(b"dummy wav data for purge test")
    assert test_audio.exists()

    consultation = models.Transcription(
        user_id=user["id"],
        patient_id="PT-PURGE01",
        title="Purge Audio Test",
        filename="test.wav",
        transcription="Keep the transcript, purge audio",
        status="transcribed",
        review_status="draft",
        audio_path=str(test_audio),
    )
    db_session.add(consultation)
    db_session.commit()
    db_session.refresh(consultation)

    c_id = consultation.id

    # Purge only audio
    res = client.delete(f"/api/consultations/{c_id}/audio", headers=auth_header(token))
    assert res.status_code == 200
    assert res.json()["success"] is True

    # Record still exists
    db_session.expire_all()
    check_db = db_session.query(models.Transcription).filter(models.Transcription.id == c_id).first()
    assert check_db is not None
    assert check_db.transcription == "Keep the transcript, purge audio"
    assert check_db.audio_path is None

    # Audio file on disk is gone
    assert not test_audio.exists()


def test_safe_delete_path_traversal_protection(tmp_path):
    from lib.utils import safe_delete_audio_file
    from pathlib import Path

    # Create a sensitive file outside the uploads directory
    sensitive_file = tmp_path / "system_file.txt"
    sensitive_file.write_text("critical data")
    assert sensitive_file.exists()

    # Attempting to delete a file outside uploads directory must return False and not delete
    result = safe_delete_audio_file(str(sensitive_file), base_upload_dir="uploads")
    assert result is False
    assert sensitive_file.exists()

    # Clean up test artifact
    sensitive_file.unlink()


# ── Workflow State Transitions & Approval Guard Tests ─────────────────────────

def test_workflow_end_to_end_transitions(client, make_user, db_session, monkeypatch):
    token, user = make_user("workflow_doc@example.com")
    from soap_generation_service import soap_generation_service

    # Step 1: Upload audio -> status is "uploaded", review_status is "draft"
    audio_data = b"RIFF....WAVEfmt ...."
    res_up = client.post(
        "/api/consultations/upload",
        files={"file": ("clinical_visit.wav", io.BytesIO(audio_data), "audio/wav")},
        data={"title": "Workflow Test Consultation"},
        headers=auth_header(token),
    )
    assert res_up.status_code == 201
    c_data = res_up.json()
    c_id = c_data["id"]
    assert c_data["status"] == "uploaded"
    assert c_data["review_status"] == "draft"

    # Step 2: Edit/Set Transcript -> status transitions to "transcript_ready", review_status remains "draft"
    res_trans = client.put(
        f"/api/consultations/{c_id}/transcript",
        json={"transcription": "Patient reports bilateral throbbing headache for 3 days and denies fever."},
        headers=auth_header(token),
    )
    assert res_trans.status_code == 200
    consultation = db_session.get(models.Transcription, c_id)
    assert consultation.status == "transcript_ready"
    assert consultation.review_status == "draft"

    # Step 3: Extract entities -> preserves "transcript_ready"
    res_ext = client.post(
        f"/api/consultations/{c_id}/extract",
        headers=auth_header(token),
    )
    assert res_ext.status_code == 200

    # Step 4: Generate draft SOAP note -> transitions to status "draft_generated", review_status "needs_review"
    # CRITICAL INVARIANT: Generation must NEVER mark the note as approved
    monkeypatch.setattr(
        soap_generation_service,
        "generate_soap_note",
        lambda *args, **kwargs: {
            "subjective": "Headache for 3 days.",
            "objective": "Normotensive, afebrile.",
            "assessment": "Tension headache.",
            "plan": "Acetaminophen and hydration.",
            "review_flags": ["Review dosage"],
            "source": "groq-mock",
        },
    )

    res_soap = client.post(
        f"/api/consultations/{c_id}/soap",
        headers=auth_header(token),
    )
    assert res_soap.status_code == 200
    soap_data = res_soap.json()
    assert soap_data["is_draft"] is True
    assert soap_data["review_status"] == "needs_review"
    assert soap_data["status"] == "draft_generated"
    assert soap_data["review_status"] != "approved"

    # Step 5: Clinician reviews and edits SOAP sections -> transitions to "in_review", review_status "in_review"
    res_edit = client.put(
        f"/api/consultations/{c_id}/soap",
        json={
            "subjective": "Patient reports bilateral tension headache for 3 days. Denies visual aura or photophobia.",
            "objective": "Blood pressure 122/78 mmHg, neurologically intact.",
            "assessment": "Tension-type headache, primary.",
            "plan": "Hydration, sleep hygiene, ibuprofen 400mg PRN with food.",
        },
        headers=auth_header(token),
    )
    assert res_edit.status_code == 200
    edited_data = res_edit.json()
    assert edited_data["status"] == "in_review"
    assert edited_data["review_status"] == "in_review"
    assert edited_data["is_draft"] is True

    # Step 6: Explicit Clinician Approval Action -> transitions to "approved", review_status "approved"
    res_app = client.post(
        f"/api/consultations/{c_id}/approve",
        json={
            "approved_by": "Dr. Meredith Grey, MD",
            "approval_notes": "Reviewed and confirmed clinical accuracy.",
        },
        headers=auth_header(token),
    )
    assert res_app.status_code == 200
    app_data = res_app.json()
    assert app_data["status"] == "approved"
    assert app_data["review_status"] == "approved"
    assert app_data["approved_by"] == "Dr. Meredith Grey, MD"
    assert app_data["approved_at"] is not None

    # Step 7: Verify final database state directly
    db_session.expire_all()
    final_db = db_session.get(models.Transcription, c_id)
    assert final_db.status == "approved"
    assert final_db.review_status == "approved"
    assert final_db.approved_by == "Dr. Meredith Grey, MD"
    assert final_db.approved_at is not None


def test_invalid_workflow_transitions(client, make_user, db_session):
    token, user = make_user("guard_doc@example.com")

    # 1. Cannot approve an un-transcribed / empty consultation
    c_empty = models.Transcription(
        user_id=user["id"],
        patient_id="PT-GUARD01",
        filename="empty.wav",
        transcription="",
        status="uploaded",
        review_status="draft",
    )
    db_session.add(c_empty)
    db_session.commit()

    res_no_soap = client.post(
        f"/api/consultations/{c_empty.id}/approve",
        json={"approved_by": "Dr. Smith"},
        headers=auth_header(token),
    )
    assert res_no_soap.status_code == 422
    assert "SOAP note has not been generated" in res_no_soap.json()["detail"]

    # 2. Cannot approve with an empty section
    c_incomplete = models.Transcription(
        user_id=user["id"],
        patient_id="PT-GUARD02",
        filename="inc.wav",
        transcription="Full conversation text here",
        status="draft_generated",
        review_status="needs_review",
    )
    db_session.add(c_incomplete)
    db_session.commit()

    soap_blank = models.SoapNote(
        transcription_id=c_incomplete.id,
        subjective="Some subjective text",
        objective="   ",  # Blank
        assessment="Assessment text",
        plan="Plan text",
    )
    db_session.add(soap_blank)
    db_session.commit()

    res_blank = client.post(
        f"/api/consultations/{c_incomplete.id}/approve",
        json={"approved_by": "Dr. Smith"},
        headers=auth_header(token),
    )
    assert res_blank.status_code == 422
    assert "must be non-empty" in res_blank.json()["detail"]

    # 3. Cannot approve without reviewer identity
    soap_blank.objective = "BP normal"
    db_session.commit()

    res_no_id = client.post(
        f"/api/consultations/{c_incomplete.id}/approve",
        json={"approved_by": "   "},
        headers=auth_header(token),
    )
    assert res_no_id.status_code == 422
    assert "Reviewer identity" in res_no_id.json()["detail"]

    # 4. Approve successfully
    res_ok = client.post(
        f"/api/consultations/{c_incomplete.id}/approve",
        json={"approved_by": "Dr. Smith"},
        headers=auth_header(token),
    )
    assert res_ok.status_code == 200

    # 5. Cannot approve again (duplicate approval prevention)
    res_dup = client.post(
        f"/api/consultations/{c_incomplete.id}/approve",
        json={"approved_by": "Dr. Smith"},
        headers=auth_header(token),
    )
    assert res_dup.status_code == 409
    assert "already approved" in res_dup.json()["detail"]

    # 6. Post-approval modification guards: all endpoints reject with 409 Conflict
    # Transcript edit
    res_mod_trans = client.put(
        f"/api/consultations/{c_incomplete.id}/transcript",
        json={"transcription": "Attempted edit after approval"},
        headers=auth_header(token),
    )
    assert res_mod_trans.status_code == 409

    # SOAP edit
    res_mod_soap = client.put(
        f"/api/consultations/{c_incomplete.id}/soap",
        json={"subjective": "S", "objective": "O", "assessment": "A", "plan": "P"},
        headers=auth_header(token),
    )
    assert res_mod_soap.status_code == 409

    # SOAP regenerate
    res_mod_gen = client.post(
        f"/api/consultations/{c_incomplete.id}/soap",
        headers=auth_header(token),
    )
    assert res_mod_gen.status_code == 409

    # Entity extract
    res_mod_ext = client.post(
        f"/api/consultations/{c_incomplete.id}/extract",
        headers=auth_header(token),
    )
    assert res_mod_ext.status_code == 409


def test_history_reflects_database_state(client, make_user, db_session):
    token, user = make_user("history_doc@example.com")
    from datetime import datetime, timezone

    # Create an approved consultation in DB
    c_app = models.Transcription(
        user_id=user["id"],
        patient_id="PT-HIST01",
        filename="approved.wav",
        transcription="Approved patient conversation",
        status="approved",
        review_status="approved",
        approved_by="Dr. Gregory House, MD",
        approved_at=datetime.now(timezone.utc),
        approval_notes="Clinician verified notes",
    )
    db_session.add(c_app)
    db_session.commit()

    # Create a draft consultation in DB
    c_draft = models.Transcription(
        user_id=user["id"],
        patient_id="PT-HIST02",
        filename="draft.wav",
        transcription="Draft conversation",
        status="draft_generated",
        review_status="needs_review",
    )
    db_session.add(c_draft)
    db_session.commit()

    # Query history endpoint
    res = client.get("/api/history", headers=auth_header(token))
    assert res.status_code == 200
    rows = res.json()
    assert len(rows) == 2

    approved_row = next(r for r in rows if r["patient_id"] == "PT-HIST01")
    assert approved_row["status"] == "approved"
    assert approved_row["review_status"] == "approved"
    assert approved_row["approved_by"] == "Dr. Gregory House, MD"
    assert approved_row["approved_at"] is not None
    assert approved_row["approval_notes"] == "Clinician verified notes"

    draft_row = next(r for r in rows if r["patient_id"] == "PT-HIST02")
    assert draft_row["status"] == "draft_generated"
    assert draft_row["review_status"] == "needs_review"
    assert draft_row["approved_by"] is None


