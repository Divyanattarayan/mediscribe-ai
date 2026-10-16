"""Tests for Evidence-Linked SOAP Note Statements Service.

Validates:
- Supported statements with verbatim transcript quotes and accurate offsets
- Unsupported statements displaying 'Evidence not found — review required.'
- Conflicting statements (e.g. denied in transcript but asserted in note)
- Ambiguous / hedged statements
- Guarantee that transcript quotations are never fabricated
- Disclaimer presence (evidence linking does not guarantee clinical correctness)
- Separation of evidence mapping from SOAP prose
- REST API endpoint GET /api/consultations/{id}/soap/evidence
"""

import pytest
from evidence_linking_service import (
    evidence_linking_service,
    EVIDENCE_DISCLAIMER,
    UNSUPPORTED_MESSAGE,
    CONFLICTING_MESSAGE,
    AMBIGUOUS_MESSAGE,
)
import models
from tests.conftest import auth_header


# ---------------------------------------------------------------------------
# Unit tests
# ---------------------------------------------------------------------------

def test_supported_statement_locates_verbatim_quote_and_offsets():
    """
    Statements derived from the dialogue are marked 'supported', with exact character offsets
    and verbatim transcript quotes.
    """
    transcript = (
        "Doctor: Hello, what brings you in today?\n"
        "Patient: I have had a severe throbbing headache for two days now.\n"
        "Doctor: Understood. Let's start with ibuprofen 400mg."
    )
    soap_note = {
        "subjective": "Patient reports severe throbbing headache for two days.",
        "objective": "Not documented",
        "assessment": "Tension headache.",
        "plan": "Start ibuprofen 400mg.",
    }

    res = evidence_linking_service.link_soap_evidence(transcript, soap_note)

    assert res["disclaimer"] == EVIDENCE_DISCLAIMER
    assert res["supported_count"] >= 2

    # Check subjective statement
    subj_stmt = next(s for s in res["statements"] if s["section"] == "subjective")
    assert subj_stmt["status"] == "supported"
    assert subj_stmt["evidence_quote"] is not None
    assert "throbbing headache" in subj_stmt["evidence_quote"]
    assert subj_stmt["similarity"] >= 70.0

    # Non-fabrication guarantee: quote MUST exactly match transcript slice
    start = subj_stmt["evidence_start"]
    end = subj_stmt["evidence_end"]
    assert transcript[start:end] == subj_stmt["evidence_quote"]


def test_unsupported_statement_displays_required_notice():
    """
    Statements that have no grounding in the transcript must return 'unsupported'
    and display the exact message: 'Evidence not found — review required.'
    """
    transcript = (
        "Doctor: How can I help you today?\n"
        "Patient: My left knee hurts when I run."
    )
    soap_note = {
        "subjective": "Left knee pain with running.",
        "objective": "Blood pressure 145/92 mmHg, heart rate 88 bpm regular.",
        "assessment": "Patellofemoral pain syndrome.",
        "plan": "Rest and ice.",
    }

    res = evidence_linking_service.link_soap_evidence(transcript, soap_note)

    # Objective statement mentions vitals completely absent from transcript
    obj_stmt = next(s for s in res["statements"] if s["section"] == "objective")
    assert obj_stmt["status"] == "unsupported"
    assert obj_stmt["evidence_quote"] is None
    assert obj_stmt["evidence_start"] is None
    assert obj_stmt["evidence_end"] is None
    assert obj_stmt["review_message"] == UNSUPPORTED_MESSAGE


def test_conflicting_statement_flagged():
    """
    When the transcript explicitly contradicts a statement (e.g. patient denied fever,
    but note asserts patient reports fever), status must be 'conflicting'.
    """
    transcript = (
        "Doctor: Have you had any fever or chills?\n"
        "Patient: No, definitely no fever, no chills at all.\n"
        "Doctor: Okay, just the sore throat then."
    )
    soap_note = {
        "subjective": "Patient reports high fever and chills for three days.",
        "objective": "Not documented",
        "assessment": "Viral pharyngitis.",
        "plan": "Warm fluids and rest.",
    }

    res = evidence_linking_service.link_soap_evidence(transcript, soap_note)

    subj_stmt = next(s for s in res["statements"] if s["section"] == "subjective")
    assert subj_stmt["status"] == "conflicting"
    assert subj_stmt["review_message"] == CONFLICTING_MESSAGE
    assert subj_stmt["evidence_quote"] is not None
    # Verbatim slice guarantee
    start = subj_stmt["evidence_start"]
    end = subj_stmt["evidence_end"]
    assert transcript[start:end] == subj_stmt["evidence_quote"]
    assert "no fever" in subj_stmt["evidence_quote"].lower()


def test_ambiguous_hedged_dialogue_flagged():
    """
    When transcript contains explicit hedges/uncertainty for the matched statement,
    status is flagged as 'ambiguous'.
    """
    transcript = (
        "Doctor: Did you hit your head when you tripped?\n"
        "Patient: Maybe, I am not sure, possibly hit the edge of the table.\n"
        "Doctor: Let me examine your scalp."
    )
    soap_note = {
        "subjective": "Head strike against table edge following fall.",
        "objective": "Scalp contusion.",
        "assessment": "Minor head injury.",
        "plan": "Neurological observation.",
    }

    res = evidence_linking_service.link_soap_evidence(transcript, soap_note)

    subj_stmt = next(s for s in res["statements"] if s["section"] == "subjective")
    assert subj_stmt["status"] == "ambiguous"
    assert subj_stmt["review_message"] == AMBIGUOUS_MESSAGE
    assert subj_stmt["evidence_quote"] is not None


def test_never_fabricate_quotations_invariant():
    """
    Invariant check across multiple synthetic consultations:
    Every non-null evidence quote must strictly equal transcript[start:end].
    """
    transcript = (
        "Doctor: Good morning. How has your asthma been?\n"
        "Patient: I use my albuterol inhaler twice a week. Wheezing happens at night.\n"
        "Doctor: Lungs have expiratory wheezes. Let's continue albuterol and add fluticasone."
    )
    soap_note = {
        "subjective": "Nocturnal wheezing, albuterol used twice weekly.",
        "objective": "Expiratory wheezes on lung auscultation.",
        "assessment": "Mild persistent asthma.",
        "plan": "Continue albuterol. Initiate fluticasone daily.",
    }

    res = evidence_linking_service.link_soap_evidence(transcript, soap_note)

    for stmt in res["statements"]:
        if stmt["evidence_quote"] is not None:
            s_start = stmt["evidence_start"]
            s_end = stmt["evidence_end"]
            assert transcript[s_start:s_end] == stmt["evidence_quote"], (
                f"Fabricated quote violation: '{stmt['evidence_quote']}' != '{transcript[s_start:s_end]}'"
            )


def test_empty_or_scaffolding_handling():
    """
    Boilerplate scaffolding like 'Not documented' is cleanly excluded from statement evidence audits.
    """
    transcript = "Doctor: Brief checkup. Patient: Doing well."
    soap_note = {
        "subjective": "Doing well.",
        "objective": "Not documented",
        "assessment": "Not documented",
        "plan": "None reported",
    }

    res = evidence_linking_service.link_soap_evidence(transcript, soap_note)
    # Only "Doing well." is an actual clinical assertion
    assert len(res["statements"]) == 1
    assert res["statements"][0]["statement"] == "Doing well."


# ---------------------------------------------------------------------------
# Integration tests via API Endpoints
# ---------------------------------------------------------------------------

def test_get_consultation_soap_evidence_endpoint(client, make_user, db_session):
    """
    GET /api/consultations/{id}/soap/evidence returns structured evidence links.
    """
    token, user = make_user()
    consultation = models.Transcription(
        user_id=user["id"],
        patient_id="PT-EVID-1",
        filename="rec.mp3",
        transcription="Patient reports right ankle pain after twisting it playing basketball. No deformity. Ice and elevate.",
        status="transcribed",
        review_status="draft",
    )
    db_session.add(consultation)
    db_session.commit()

    soap_note = models.SoapNote(
        transcription_id=consultation.id,
        subjective="Right ankle pain following inversion injury during sports.",
        objective="No bony deformity noted.",
        assessment="Ankle sprain.",
        plan="Ice and elevation recommended.",
        source="groq-llama-3.3-70b-versatile",
    )
    db_session.add(soap_note)
    db_session.commit()

    res = client.get(
        f"/api/consultations/{consultation.id}/soap/evidence",
        headers=auth_header(token),
    )
    assert res.status_code == 200
    data = res.json()
    assert "disclaimer" in data
    assert "statements" in data
    assert data["total_statements"] > 0
    assert any(s["status"] == "supported" for s in data["statements"])


def test_evidence_recomputed_on_soap_edit(client, make_user, db_session):
    """
    When PUT /api/consultations/{id}/soap updates sections, evidence links are recomputed.
    """
    token, user = make_user()
    consultation = models.Transcription(
        user_id=user["id"],
        patient_id="PT-EVID-2",
        filename="rec.mp3",
        transcription="Patient complains of earache. Tympanic membrane erythematous.",
        status="transcribed",
        review_status="draft",
    )
    db_session.add(consultation)
    db_session.commit()

    # Edit SOAP to add an unsupported statement
    payload = {
        "subjective": "Patient complains of severe earache.",
        "objective": "Blood pressure 160/100 mmHg. Tympanic membrane erythematous.",
        "assessment": "Otitis media with severe hypertension.",
        "plan": "Amoxicillin 500mg TID. Amlodipine 10mg daily.",
    }

    res = client.put(
        f"/api/consultations/{consultation.id}/soap",
        json=payload,
        headers=auth_header(token),
    )
    assert res.status_code == 200
    data = res.json()
    assert "evidence_links" in data
    assert data["evidence_links"] is not None

    statements = data["evidence_links"]["statements"]
    # Look for the hypertension / BP statement which is unsupported
    unsupported = [s for s in statements if s["status"] == "unsupported"]
    assert len(unsupported) > 0
    assert any("Evidence not found — review required." in u["review_message"] for u in unsupported)
