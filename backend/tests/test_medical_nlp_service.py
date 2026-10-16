"""Comprehensive unit tests for the Medical Information Extraction Service.

Synthetic test cases covering:
1. Positive findings and patient-reported symptoms
2. Strict negation handling ("The patient denies fever" must not be positive)
3. Medication distinctions: prescribed vs current vs discontinued + dosage extraction
4. Symptoms vs confirmed diagnoses
5. Explicit allergy mentions (with reactions) and NKDA detection
6. Duration and timing extraction
7. Uncertain / ambiguous statements flagged for review
8. Missing information / clinical gaps detection (no hallucinated facts)
9. Transparent model limitations and clinical disclaimers
"""

import pytest
from medical_nlp_service import (
    MedicalNLPService,
    AI_EXTRACTION_DISCLAIMER,
    MODEL_LIMITATIONS,
)


@pytest.fixture
def nlp_service():
    return MedicalNLPService()


# ── Positive Findings & Symptoms ──────────────────────────────────────────────

def test_extract_positive_symptoms(nlp_service):
    transcript = (
        "Patient presents with severe throbbing headache and persistent nausea for 3 days. "
        "Also reports feeling tired and fatigued."
    )
    result = nlp_service.process_transcript(transcript)

    assert result["success"] is True
    symptom_names = [s["text"].lower() for s in result["symptoms"]]
    assert "headache" in symptom_names
    assert "nausea" in symptom_names
    assert "fatigue" in symptom_names or "tiredness" in symptom_names or "tired" in symptom_names

    # Check positive findings list
    pos_findings = [f["finding"].lower() for f in result["positive_findings"]]
    assert "headache" in pos_findings
    assert "nausea" in pos_findings


# ── Negation Handling ─────────────────────────────────────────────────────────

def test_negation_denied_fever_not_positive(nlp_service):
    """Critical clinical safety test: denied fever MUST NOT be extracted as a positive symptom."""
    transcript = (
        "Patient has a mild cough. The patient denies fever and reports no chest pain or shortness of breath."
    )
    result = nlp_service.process_transcript(transcript)

    # Cough is positive
    pos = [f["finding"].lower() for f in result["positive_findings"]]
    assert "cough" in pos
    assert "fever" not in pos
    assert "chest pain" not in pos
    assert "shortness of breath" not in pos

    # Fever, chest pain, and shortness of breath must be in negative findings
    neg = [f["finding"].lower() for f in result["negative_findings"]]
    assert "fever" in neg
    assert "chest pain" in neg
    assert "shortness of breath" in neg

    # Check symptom attributes
    for sym in result["symptoms"]:
        if sym["text"].lower() in ("fever", "chest pain", "shortness of breath"):
            assert sym["negated"] is True


def test_negation_backward_cues(nlp_service):
    transcript = "Abdominal tenderness was ruled out. Palpitations were not observed."
    result = nlp_service.process_transcript(transcript)

    neg = [f["finding"].lower() for f in result["negative_findings"]]
    assert "palpitations" in neg or "tenderness" in neg


# ── Symptoms vs. Confirmed Diagnoses ──────────────────────────────────────────

def test_distinguish_symptoms_from_diagnoses(nlp_service):
    transcript = (
        "Patient has a long history of hypertension and established type 2 diabetes. "
        "Today presenting with acute dizziness and lightheadedness."
    )
    result = nlp_service.process_transcript(transcript)

    conditions = [c["text"].lower() for c in result["medical_conditions"]]
    assert "hypertension" in conditions
    # "type 2 diabetes" is matched as the full multi-word canonical term
    assert any("diabetes" in c for c in conditions)

    symptoms = [s["text"].lower() for s in result["symptoms"]]
    assert "dizziness" in symptoms or "lightheadedness" in symptoms


# ── Medications: Mentioned vs. Prescribed vs. Discontinued ────────────────────

def test_medication_action_distinctions_and_dosage(nlp_service):
    transcript = (
        "Patient is currently taking metformin 500mg twice daily for diabetes. "
        "Due to elevated blood pressure, I am starting lisinopril 10mg daily. "
        "We have discontinued aspirin 81mg due to stomach upset."
    )
    result = nlp_service.process_transcript(transcript)
    meds = result["medications"]

    # Prescribed
    prescribed_names = [m["text"].lower() for m in meds["prescribed"]]
    assert "lisinopril" in prescribed_names
    lisinopril_entry = next(m for m in meds["prescribed"] if m["text"].lower() == "lisinopril")
    assert "10mg" in lisinopril_entry.get("dosage", "")

    # Current / mentioned
    current_names = [m["text"].lower() for m in meds["current_or_mentioned"]]
    assert "metformin" in current_names
    metformin_entry = next(m for m in meds["current_or_mentioned"] if m["text"].lower() == "metformin")
    assert "500mg" in metformin_entry.get("dosage", "")

    # Discontinued
    discontinued_names = [m["text"].lower() for m in meds["discontinued"]]
    assert "aspirin" in discontinued_names


# ── Allergies & NKDA ──────────────────────────────────────────────────────────

def test_explicit_allergy_with_reaction(nlp_service):
    transcript = (
        "Patient is allergic to penicillin, which causes severe rash and hives. "
        "Denies any other food or environmental allergies."
    )
    result = nlp_service.process_transcript(transcript)

    allergies = result["allergies"]
    assert len(allergies) >= 1
    penicillin_allergy = next(a for a in allergies if "penicillin" in a["allergen"].lower())
    assert penicillin_allergy["negated"] is False
    assert penicillin_allergy["reaction"] is not None
    assert "rash" in penicillin_allergy["reaction"].lower() or "hives" in penicillin_allergy["reaction"].lower()


def test_explicit_nkda_detection(nlp_service):
    transcript = "Patient has no known drug allergies. Vitals are stable."
    result = nlp_service.process_transcript(transcript)

    allergies = result["allergies"]
    assert len(allergies) == 1
    assert allergies[0]["negated"] is True
    assert "nkda" in allergies[0]["allergen"].lower() or "no known" in allergies[0]["allergen"].lower()


# ── Duration and Timing ───────────────────────────────────────────────────────

def test_duration_and_timing_association(nlp_service):
    transcript = "Patient has been suffering from joint pain for 2 weeks and fever since yesterday."
    result = nlp_service.process_transcript(transcript)

    durations = result["durations_and_timing"]
    phrases = [d["phrase"].lower() for d in durations]
    assert any("2 weeks" in p for p in phrases) or any("yesterday" in p for p in phrases)

    # Symptom duration association
    for sym in result["symptoms"]:
        if sym["text"].lower() == "joint pain":
            assert sym.get("duration") is not None


# ── Uncertain & Ambiguous Statements ──────────────────────────────────────────

def test_uncertain_statements_flagged_for_review(nlp_service):
    transcript = "Exam reveals possible pneumonia, rule out pulmonary embolism. EKG is borderline."
    result = nlp_service.process_transcript(transcript)

    uncertain = result["uncertain_findings"]
    assert len(uncertain) >= 1
    findings_text = [u["finding"].lower() for u in uncertain]
    assert "pneumonia" in findings_text or "pulmonary embolism" in findings_text
    assert all(u["requires_review"] is True for u in uncertain)


# ── Missing Information / Clinical Gaps ───────────────────────────────────────

def test_missing_information_detected_without_fabrication(nlp_service):
    """When vitals, allergy status, or durations are omitted, they must be flagged as gaps, not invented."""
    transcript = "Patient complains of headache. General exam unremarkable."
    result = nlp_service.process_transcript(transcript)

    gaps = result["missing_information"]
    assert any("allergy" in g.lower() for g in gaps)
    assert any("vital" in g.lower() for g in gaps)
    assert any("duration" in g.lower() for g in gaps)


# ── Limitations & Disclaimers ─────────────────────────────────────────────────

def test_model_info_and_disclaimer_presence(nlp_service):
    transcript = "Patient reports mild back pain."
    result = nlp_service.process_transcript(transcript)

    assert result["disclaimer"] == AI_EXTRACTION_DISCLAIMER
    assert "ai-generated" in result["disclaimer"].lower()
    assert "clinician" in result["disclaimer"].lower()

    model_info = result["model_info"]
    assert "spacy_model" in model_info
    assert "limitations" in model_info
    assert len(model_info["limitations"]) > 0
    assert any("negation" in lim.lower() for lim in model_info["limitations"])
