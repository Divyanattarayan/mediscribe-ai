"""Behavioural coverage for the medical-content gate."""

import content_validator
from content_validator import validate_medical_content

NON_MEDICAL = (
    "Ok, let's talk about heated rivalry. This show is pure tension from the very "
    "first moment. It's not just about hockey, it's about ego, competition, and two "
    "people who absolutely refuse to lose. The pacing is relentless and every episode "
    "ends on a cliffhanger that makes you want to keep watching all night long."
)

DICTATED_NOTE = (
    "Patient is a 45 year old male presenting with chest pain and shortness of breath. "
    "History of hypertension and type 2 diabetes. Vital signs show blood pressure 140/90, "
    "heart rate 88 bpm, respiratory rate 18. Physical examination reveals clear lung sounds. "
    "Assessment: chest pain, likely cardiac. Plan: ECG, troponin, aspirin, admit for monitoring."
)


def test_non_medical_audio_is_rejected():
    result = validate_medical_content(NON_MEDICAL)
    assert result["is_valid"] is False
    assert "clinical audio only" in result["reason"].lower()


def test_dictated_clinical_note_passes():
    result = validate_medical_content(DICTATED_NOTE)
    assert result["is_valid"] is True
    assert 0.0 < result["confidence_score"] <= 1.0


def test_empty_transcription_is_rejected():
    result = validate_medical_content("")
    assert result["is_valid"] is False
    assert result["confidence_score"] == 0.0


def test_short_clinical_clip_reads_as_too_short_not_non_medical():
    short_clinical = "Patient reports chest pain. Denies shortness of breath."
    result = validate_medical_content(short_clinical)
    assert result["is_valid"] is False
    assert "too short" in result["reason"].lower()


def test_marker_heavy_conversational_history_passes():
    """A history-taking dialogue: lower term density, many clinical markers."""
    transcript = (
        "So what's brought you in today? I've been getting chest pain for about three days. "
        "Can you describe the pain for me? It's a sharp pain, right in the middle. "
        "Does it go anywhere? Not really. On a scale of 1 to 10 how bad is it? About a six. "
        "What makes it worse? Breathing in deeply. Any other symptoms, any shortness of breath? "
        "A little. Have you had this before? No. Let me just check your name and date of birth. "
        "Any medications, are you taking anything regularly? Just the occasional paracetamol. "
        "Are you allergic to anything? No known allergies. Any past medical history of note?"
    )
    result = validate_medical_content(transcript)
    assert result["is_valid"] is True


def test_thresholds_are_configurable():
    text = "Patient presents with cough. " * 20
    strict = validate_medical_content(text, min_density=0.9, min_markers=50)
    assert strict["is_valid"] is False


def test_module_smoke_block_still_runs(capsys):
    """The historical __main__ demo should keep working as a manual check."""
    content_validator.validate_medical_content(NON_MEDICAL)
    content_validator.validate_medical_content(DICTATED_NOTE)
