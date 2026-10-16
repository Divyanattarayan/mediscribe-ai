from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, Query, status
from sqlalchemy.orm import Session, selectinload
from sqlalchemy.sql import func
from datetime import datetime, timezone
from typing import List, Optional
import os
import uuid
import logging

import models
import schemas
from database import get_db
from auth import get_current_user, get_optional_user
from lib.utils import generate_patient_id, safe_delete_audio_file
import transcription
from entity_extraction import extract_medical_entities
from soap_generator import generate_soap_note
from documentation_style import resolve_style_profile
from transcription_service import (
    transcription_service,
    AudioValidationError,
    EmptyAudioError,
    ModelLoadError,
    TranscriptionError,
    TRANSCRIPTION_DISCLAIMER,
)
from content_validator import validate_medical_content
from medical_nlp_service import medical_nlp_service
from soap_generation_service import (
    soap_generation_service,
    MissingApiKeyError,
    GroqRateLimitError,
    GroqTimeoutError,
    GroqConnectionError,
    InvalidResponseError,
    SoapGenerationServiceError,
)
from evidence_linking_service import evidence_linking_service
import json



logger = logging.getLogger("mediscribe.consultations")

router = APIRouter(prefix="/api/consultations", tags=["consultations"])

ALLOWED_AUDIO_EXTENSIONS = ('.mp3', '.wav', '.m4a', '.webm', '.ogg', '.flac')
MAX_UPLOAD_BYTES = 50 * 1024 * 1024


def _to_str(val) -> str:
    if isinstance(val, str):
        return val
    if isinstance(val, dict):
        return "\n".join(f"{k}: {v}" for k, v in val.items())
    return str(val) if val is not None else ""


@router.post("/upload", response_model=schemas.ConsultationUploadResponse, status_code=status.HTTP_201_CREATED)
async def upload_consultation_audio(
    file: UploadFile = File(...),
    title: Optional[str] = Form(None),
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Accept an audio file for a clinical consultation.
    Validates extension, MIME type, and size. Stores safely in a local folder
    and persists a draft consultation record in the database.
    """
    original_filename = file.filename or "recording"
    ext = os.path.splitext(original_filename)[1].lower()

    if ext not in ALLOWED_AUDIO_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file format '{ext}'. Allowed extensions: {', '.join(ALLOWED_AUDIO_EXTENSIONS)}",
        )

    content_type = (file.content_type or "").lower()
    if content_type and not (
        content_type.startswith("audio/")
        or content_type in ("video/webm", "application/octet-stream")
    ):
        raise HTTPException(
            status_code=400,
            detail=f"Invalid MIME type '{content_type}'. Must be an audio file.",
        )

    audio_bytes = await file.read()
    if len(audio_bytes) == 0:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")
    if len(audio_bytes) > MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"File exceeds maximum upload size of {MAX_UPLOAD_BYTES // (1024 * 1024)}MB.",
        )

    consultations_dir = os.path.join("uploads", "consultations")
    os.makedirs(consultations_dir, exist_ok=True)
    safe_filename = f"{uuid.uuid4().hex}{ext}"
    safe_filepath = os.path.join(consultations_dir, safe_filename)

    with open(safe_filepath, "wb") as f:
        f.write(audio_bytes)

    patient_id = generate_patient_id()
    consultation_title = title.strip() if title and title.strip() else f"Consultation {patient_id}"

    consultation = models.Transcription(
        user_id=current_user.id,
        patient_id=patient_id,
        title=consultation_title,
        filename=original_filename,
        transcription="",
        medical_content_score=0.0,
        status="uploaded",
        review_status="draft",
        audio_path=safe_filepath,
    )

    db.add(consultation)
    db.commit()
    db.refresh(consultation)

    logger.info("Uploaded consultation audio id=%s patient_id=%s user_id=%s", consultation.id, patient_id, current_user.id)
    return consultation


@router.post("/{consultation_id}/transcribe", response_model=schemas.ConsultationOut)
async def transcribe_consultation(
    consultation_id: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Run speech recognition on the uploaded consultation audio.
    Returns 503 if the speech-to-text service is not configured or unavailable.
    """
    consultation = (
        db.query(models.Transcription)
        .options(
            selectinload(models.Transcription.entities),
            selectinload(models.Transcription.soap_note),
        )
        .filter(
            models.Transcription.id == consultation_id,
            models.Transcription.user_id == current_user.id,
        )
        .first()
    )

    if not consultation:
        raise HTTPException(status_code=404, detail="Consultation not found.")

    if consultation.review_status == "approved":
        raise HTTPException(status_code=409, detail="Cannot modify an approved consultation.")

    if not consultation.audio_path or not os.path.exists(consultation.audio_path):
        raise HTTPException(status_code=400, detail="Audio file not found for this consultation.")


    consultation.status = "transcribing"
    db.commit()

    try:
        model = transcription_service.get_model()
        if getattr(type(model), "__name__", "") == "_StubWhisperModel":
            consultation.status = "failed"
            db.commit()
            raise HTTPException(
                status_code=503,
                detail="Speech recognition service is not configured or unavailable in this environment.",
            )

        result = transcription_service.transcribe(consultation.audio_path)
        consultation.transcription = result["transcription"]
        consultation.duration = result["duration"]
        consultation.asr_confidence = result["asr_confidence"]
        consultation.status = "transcript_ready"
        consultation.review_status = "draft"

        val = validate_medical_content(consultation.transcription)
        consultation.medical_content_score = float(val.get("confidence_score", 0.0))

        db.commit()
        db.refresh(consultation)
        return consultation
    except AudioValidationError as e:
        consultation.status = "failed"
        db.commit()
        raise HTTPException(status_code=400, detail=str(e))
    except EmptyAudioError as e:
        consultation.status = "failed"
        db.commit()
        raise HTTPException(status_code=422, detail=str(e))
    except (ModelLoadError, TranscriptionError) as e:
        consultation.status = "failed"
        db.commit()
        logger.exception("Transcription failed for consultation %s", consultation_id)
        raise HTTPException(status_code=503, detail=f"Speech recognition service error: {str(e)}")
    except HTTPException:
        raise
    except Exception as e:
        consultation.status = "failed"
        db.commit()
        logger.exception("Unexpected error during transcription of consultation %s", consultation_id)
        raise HTTPException(status_code=503, detail=f"Speech recognition error: {str(e)}")




@router.get("/{consultation_id}/transcript", response_model=schemas.TranscriptResponse)
def get_consultation_transcript(
    consultation_id: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Retrieve the current transcript and extracted entities for a consultation.
    """
    consultation = (
        db.query(models.Transcription)
        .options(selectinload(models.Transcription.entities))
        .filter(
            models.Transcription.id == consultation_id,
            models.Transcription.user_id == current_user.id,
        )
        .first()
    )

    if not consultation:
        raise HTTPException(status_code=404, detail="Consultation not found.")

    return consultation


@router.put("/{consultation_id}/transcript", response_model=schemas.TranscriptResponse)
def update_consultation_transcript(
    consultation_id: int,
    payload: schemas.TranscriptUpdateRequest,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Update the transcript text for a consultation before downstream processing.
    """
    consultation = (
        db.query(models.Transcription)
        .options(selectinload(models.Transcription.entities))
        .filter(
            models.Transcription.id == consultation_id,
            models.Transcription.user_id == current_user.id,
        )
        .first()
    )

    if not consultation:
        raise HTTPException(status_code=404, detail="Consultation not found.")

    if consultation.review_status == "approved":
        raise HTTPException(status_code=409, detail="Cannot modify an approved consultation.")

    cleaned_text = payload.transcription.strip()
    if not cleaned_text:
        raise HTTPException(status_code=422, detail="Transcript text cannot be empty.")

    consultation.transcription = cleaned_text
    consultation.status = "transcript_ready"
    if consultation.review_status != "approved":
        consultation.review_status = "draft"

    db.commit()
    db.refresh(consultation)
    return consultation


@router.post("/{consultation_id}/extract")
def extract_entities_endpoint(
    consultation_id: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Extract clinical entities from the current consultation transcript.
    """
    consultation = (
        db.query(models.Transcription)
        .filter(
            models.Transcription.id == consultation_id,
            models.Transcription.user_id == current_user.id,
        )
        .first()
    )

    if not consultation:
        raise HTTPException(status_code=404, detail="Consultation not found.")

    if consultation.review_status == "approved":
        raise HTTPException(status_code=409, detail="Cannot modify an approved consultation.")

    if not consultation.transcription or not consultation.transcription.strip():
        raise HTTPException(
            status_code=422,
            detail="Consultation has no transcript to extract entities from.",
        )

    try:
        entities_result = extract_medical_entities(consultation.transcription)
        if not entities_result.get("success", True) and not entities_result.get("entities"):
            raise HTTPException(
                status_code=503,
                detail=f"Medical NLP extraction service unavailable: {entities_result.get('error', 'unknown error')}",
            )
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Entity extraction error for consultation %s", consultation_id)
        raise HTTPException(status_code=503, detail="Medical NLP extraction service unavailable.")

    # Remove previous entities
    db.query(models.MedicalEntity).filter(
        models.MedicalEntity.transcription_id == consultation.id
    ).delete()

    for ent in entities_result.get("entities", []):
        ontology = ent.get("ontology") or {}
        db.add(models.MedicalEntity(
            transcription_id=consultation.id,
            text=ent.get("text", ""),
            label=ent.get("label", ""),
            confidence=float(ent.get("confidence", 0.0)),
            start=int(ent.get("start", 0)),
            end=int(ent.get("end", 0)),
            negated=bool(ent.get("negated", False)),
            temporality=str(ent.get("temporality", "current")),
            experiencer=str(ent.get("experiencer", "patient")),
            uncertain=bool(ent.get("uncertain", False)),
            assertion_source=str(ent.get("assertion_source", "default")),
            ontology_system=ontology.get("system"),
            ontology_code=ontology.get("code"),
            ontology_display=ontology.get("display"),
            ontology_requires_review=bool(ontology.get("requires_review", False)),
        ))

    db.commit()

    # Process rich structured clinical NLP representation
    nlp_structured = medical_nlp_service.process_transcript(consultation.transcription)

    return {
        "consultation_id": consultation.id,
        "total_entities": len(entities_result.get("entities", [])),
        "entities": entities_result.get("entities", []),
        "category_counts": entities_result.get("category_counts", {}),
        "assertion_counts": entities_result.get("assertion_counts", {}),
        "ontology_counts": entities_result.get("ontology_counts", {}),
        "structured_clinical_data": {
            "symptoms": nlp_structured.get("symptoms", []),
            "medical_conditions": nlp_structured.get("medical_conditions", []),
            "medications": nlp_structured.get("medications", {}),
            "allergies": nlp_structured.get("allergies", []),
            "durations_and_timing": nlp_structured.get("durations_and_timing", []),
            "positive_findings": nlp_structured.get("positive_findings", []),
            "negative_findings": nlp_structured.get("negative_findings", []),
            "uncertain_findings": nlp_structured.get("uncertain_findings", []),
            "missing_information": nlp_structured.get("missing_information", []),
        },
        "model_info": nlp_structured.get("model_info", {}),
        "disclaimer": nlp_structured.get("disclaimer", ""),
    }



from pydantic import BaseModel as PydanticBaseModel


class DirectTranscriptSoapRequest(PydanticBaseModel):
    transcript: str
    encounter_type: Optional[str] = None


class DirectTranscriptExtractRequest(PydanticBaseModel):
    transcript: str


@router.post("/entities/extract-from-transcript")
def extract_entities_from_transcript_direct(
    payload: DirectTranscriptExtractRequest,
    current_user: Optional[models.User] = Depends(get_optional_user),
):
    """
    Extract clinical entities directly from a transcript string without needing a database consultation record.
    Used by live microphone recordings and transcript review editing.
    """
    transcript = (payload.transcript or "").strip()
    if not transcript:
        return {
            "success": True,
            "entities": [],
            "total_entities": 0,
            "medical_content_score": 0,
            "categorized": {},
        }

    try:
        entities_result = extract_medical_entities(transcript)
        entities = entities_result.get("entities", [])
        return {
            "success": True,
            "entities": entities,
            "total_entities": len(entities),
            "medical_content_score": entities_result.get("medical_content_score", 85),
            "categorized": entities_result.get("categorized", {}),
        }
    except Exception as e:
        logger.exception("Error extracting entities directly: %s", e)
        raise HTTPException(status_code=500, detail="Entity extraction failed.")



@router.post("/soap/generate-from-transcript", response_model=schemas.SoapResponse)
def generate_soap_from_transcript_direct(
    payload: DirectTranscriptSoapRequest,
    current_user: models.User = Depends(get_current_user),
):
    """
    Generate a SOAP note directly from a provided transcript string.
    Used by live microphone consultations that are not yet persisted to the database.
    No consultation database record is required.
    """
    transcript = payload.transcript.strip()
    if not transcript:
        raise HTTPException(
            status_code=422,
            detail="Transcript is empty. Please provide clinical dialogue to generate a SOAP note.",
        )

    structured_clinical_data = None
    try:
        structured_clinical_data = medical_nlp_service.process_transcript(transcript)
    except Exception as e:
        logger.warning("Clinical NLP pre-processing skipped for direct SOAP: %s", e)

    try:
        soap_result = soap_generation_service.generate_soap_note(
            transcript=transcript,
            extracted_entities=[],
            structured_clinical_data=structured_clinical_data,
        )
    except MissingApiKeyError as e:
        logger.error("SOAP generation aborted (direct): %s", str(e))
        raise HTTPException(
            status_code=503,
            detail="SOAP generation service is not configured (missing Groq API key).",
        )
    except GroqRateLimitError as e:
        raise HTTPException(
            status_code=429,
            detail="SOAP generation service rate limit reached. Please retry shortly.",
        )
    except (GroqTimeoutError, GroqConnectionError) as e:
        raise HTTPException(
            status_code=504,
            detail=f"SOAP generation service network error: {str(e)}",
        )
    except InvalidResponseError as e:
        raise HTTPException(
            status_code=502,
            detail=f"SOAP generation returned an invalid response: {str(e)}",
        )
    except SoapGenerationServiceError as e:
        raise HTTPException(
            status_code=500,
            detail=f"SOAP generation failed: {str(e)}",
        )

    return {
        "subjective": soap_result.get("subjective", ""),
        "objective": soap_result.get("objective", ""),
        "assessment": soap_result.get("assessment", ""),
        "plan": soap_result.get("plan", ""),
        "source": soap_result.get("source", "groq-llama-3.3-70b-versatile"),
        "review_flags": soap_result.get("review_flags", []),
        "is_draft": True,
        "disclaimer": "AI-generated draft — clinician must review and verify before clinical use.",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "review_status": "needs_review",
    }


@router.post("/{consultation_id}/soap", response_model=schemas.SoapResponse)
def generate_consultation_soap(
    consultation_id: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Generate structured SOAP note sections (Subjective, Objective, Assessment, Plan)
    from the consultation transcript using Groq LLM with safety review flags.
    Never returns a fake generated note if the API call fails.
    """
    consultation = (
        db.query(models.Transcription)
        .options(
            selectinload(models.Transcription.entities),
            selectinload(models.Transcription.soap_note),
        )
        .filter(
            models.Transcription.id == consultation_id,
            models.Transcription.user_id == current_user.id,
        )
        .first()
    )

    if not consultation:
        raise HTTPException(status_code=404, detail="Consultation not found.")

    if consultation.review_status == "approved":
        raise HTTPException(status_code=409, detail="Cannot modify an approved consultation.")

    if not consultation.transcription or not consultation.transcription.strip():
        raise HTTPException(
            status_code=422,
            detail="Consultation has no transcript to generate SOAP note from.",
        )

    # Gather extracted entities and structured clinical NLP data if available
    structured_clinical_data = None
    try:
        structured_clinical_data = medical_nlp_service.process_transcript(consultation.transcription)
    except Exception as e:
        logger.warning("Clinical NLP pre-processing skipped for SOAP: %s", e)

    raw_entities = [
        {"text": ent.text, "label": ent.label, "start": ent.start, "end": ent.end, "negated": ent.negated}
        for ent in consultation.entities
    ]

    try:
        soap_result = soap_generation_service.generate_soap_note(
            transcript=consultation.transcription,
            extracted_entities=raw_entities,
            structured_clinical_data=structured_clinical_data,
        )
    except MissingApiKeyError as e:
        logger.error("SOAP generation aborted: %s", str(e))
        raise HTTPException(
            status_code=503,
            detail="SOAP generation service is not configured (missing Groq API key).",
        )
    except GroqRateLimitError as e:
        logger.warning("Groq rate limit during consultation %s: %s", consultation_id, str(e))
        raise HTTPException(
            status_code=429,
            detail="SOAP generation service rate limit reached. Please retry shortly.",
        )
    except (GroqTimeoutError, GroqConnectionError) as e:
        logger.warning("Groq network error during consultation %s: %s", consultation_id, str(e))
        raise HTTPException(
            status_code=504,
            detail=f"SOAP generation service network error: {str(e)}",
        )
    except InvalidResponseError as e:
        logger.error("Groq invalid response during consultation %s: %s", consultation_id, str(e))
        raise HTTPException(
            status_code=502,
            detail=f"SOAP generation service returned an invalid response: {str(e)}",
        )
    except SoapGenerationServiceError as e:
        logger.exception("SOAP generation failed for consultation %s", consultation_id)
        raise HTTPException(
            status_code=503,
            detail=f"SOAP generation service error: {str(e)}",
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Unexpected error during SOAP generation for consultation %s", consultation_id)
        raise HTTPException(status_code=503, detail="SOAP generation service is unavailable.")

    subj = _to_str(soap_result.get("subjective", "Not documented"))
    obj = _to_str(soap_result.get("objective", "Not documented"))
    assess = _to_str(soap_result.get("assessment", "Not documented"))
    plan = _to_str(soap_result.get("plan", "Not documented"))
    source = soap_result.get("source", f"groq-{soap_generation_service.model_name}")
    review_flags = soap_result.get("review_flags", [])

    flags_json = json.dumps(review_flags)

    evidence_data = evidence_linking_service.link_soap_evidence(
        transcript=consultation.transcription,
        soap_note={"subjective": subj, "objective": obj, "assessment": assess, "plan": plan},
    )
    evidence_json = json.dumps(evidence_data)

    if not consultation.soap_note:
        soap_note = models.SoapNote(
            transcription_id=consultation.id,
            subjective=subj,
            objective=obj,
            assessment=assess,
            plan=plan,
            source=source,
            review_flags=flags_json,
            evidence_links=evidence_json,
        )
        db.add(soap_note)
    else:
        consultation.soap_note.subjective = subj
        consultation.soap_note.objective = obj
        consultation.soap_note.assessment = assess
        consultation.soap_note.plan = plan
        consultation.soap_note.source = source
        consultation.soap_note.review_flags = flags_json
        consultation.soap_note.evidence_links = evidence_json
        consultation.soap_note.updated_at = func.now()

    consultation.status = "draft_generated"
    consultation.review_status = "needs_review"
    db.commit()
    db.refresh(consultation)

    return {
        "subjective": subj,
        "objective": obj,
        "assessment": assess,
        "plan": plan,
        "review_flags": review_flags,
        "evidence_links": evidence_data,
        "source": source,
        "status": consultation.status,
        "review_status": consultation.review_status,
        "is_draft": True,
        "disclaimer": soap_result.get("disclaimer", "AI-generated clinical draft. Requires clinician review, editing, and approval before signing."),
        "updated_at": consultation.soap_note.updated_at if consultation.soap_note else None,
    }


@router.put("/{consultation_id}/soap", response_model=schemas.SoapResponse)
def update_consultation_soap(
    consultation_id: int,
    payload: schemas.SoapUpdateRequest,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Allow clinicians to modify generated SOAP sections prior to approval.
    Validates that required sections are not empty and recomputes evidence links.
    """
    consultation = (
        db.query(models.Transcription)
        .options(selectinload(models.Transcription.soap_note))
        .filter(
            models.Transcription.id == consultation_id,
            models.Transcription.user_id == current_user.id,
        )
        .first()
    )

    if not consultation:
        raise HTTPException(status_code=404, detail="Consultation not found.")

    if consultation.review_status == "approved":
        raise HTTPException(status_code=409, detail="Cannot modify an approved consultation.")

    subj = payload.subjective.strip()
    obj = payload.objective.strip()
    assess = payload.assessment.strip()
    pl = payload.plan.strip()

    if not (subj and obj and assess and pl):
        raise HTTPException(
            status_code=422,
            detail="All SOAP sections (subjective, objective, assessment, plan) must be non-empty.",
        )

    evidence_data = evidence_linking_service.link_soap_evidence(
        transcript=consultation.transcription or "",
        soap_note={"subjective": subj, "objective": obj, "assessment": assess, "plan": pl},
    )
    evidence_json = json.dumps(evidence_data)

    existing_flags = consultation.soap_note.parsed_review_flags if consultation.soap_note else []

    if not consultation.soap_note:
        soap_note = models.SoapNote(
            transcription_id=consultation.id,
            subjective=subj,
            objective=obj,
            assessment=assess,
            plan=pl,
            source="clinician-edited",
            review_flags=json.dumps(existing_flags),
            evidence_links=evidence_json,
        )
        db.add(soap_note)
    else:
        consultation.soap_note.subjective = subj
        consultation.soap_note.objective = obj
        consultation.soap_note.assessment = assess
        consultation.soap_note.plan = pl
        consultation.soap_note.source = "clinician-edited"
        consultation.soap_note.evidence_links = evidence_json
        consultation.soap_note.updated_at = func.now()

    consultation.status = "in_review"
    consultation.review_status = "in_review"
    db.commit()
    db.refresh(consultation)

    return {
        "subjective": subj,
        "objective": obj,
        "assessment": assess,
        "plan": pl,
        "review_flags": existing_flags,
        "evidence_links": evidence_data,
        "source": consultation.soap_note.source,
        "status": consultation.status,
        "review_status": consultation.review_status,
        "is_draft": True,
        "disclaimer": "AI-generated clinical draft. Requires clinician review, editing, and approval before signing.",
        "updated_at": consultation.soap_note.updated_at,
    }


@router.get("/{consultation_id}/soap/evidence", response_model=schemas.EvidenceLinksOut)
def get_consultation_soap_evidence(
    consultation_id: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Retrieve statement-level transcript evidence links for a consultation SOAP note.
    Identifies supporting transcript excerpts, character offsets, similarity metrics,
    and flags unsupported, ambiguous, or conflicting statements.
    """
    consultation = (
        db.query(models.Transcription)
        .options(selectinload(models.Transcription.soap_note))
        .filter(
            models.Transcription.id == consultation_id,
            models.Transcription.user_id == current_user.id,
        )
        .first()
    )

    if not consultation:
        raise HTTPException(status_code=404, detail="Consultation not found.")

    if not consultation.soap_note:
        raise HTTPException(status_code=404, detail="SOAP note not found for this consultation.")

    if not consultation.transcription or not consultation.transcription.strip():
        raise HTTPException(status_code=422, detail="Consultation has no transcript.")

    # Return cached evidence links if available, else recompute
    if consultation.soap_note.evidence_links:
        try:
            cached = json.loads(consultation.soap_note.evidence_links)
            if isinstance(cached, dict) and "statements" in cached:
                return cached
        except Exception:
            pass

    evidence_data = evidence_linking_service.link_soap_evidence(
        transcript=consultation.transcription,
        soap_note={
            "subjective": consultation.soap_note.subjective or "",
            "objective": consultation.soap_note.objective or "",
            "assessment": consultation.soap_note.assessment or "",
            "plan": consultation.soap_note.plan or "",
        },
    )
    consultation.soap_note.evidence_links = json.dumps(evidence_data)
    db.commit()
    return evidence_data


@router.post("/{consultation_id}/approve", response_model=schemas.ApproveResponse)
def approve_consultation(
    consultation_id: int,
    payload: schemas.ApproveRequest,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Explicitly approve and finalize a consultation note.
    Prevents approval if required sections are missing or if already approved.
    Notes are NEVER approved automatically.
    """
    consultation = (
        db.query(models.Transcription)
        .options(selectinload(models.Transcription.soap_note))
        .filter(
            models.Transcription.id == consultation_id,
            models.Transcription.user_id == current_user.id,
        )
        .first()
    )

    if not consultation:
        raise HTTPException(status_code=404, detail="Consultation not found.")

    if consultation.review_status == "approved":
        raise HTTPException(status_code=409, detail="Consultation is already approved.")

    if not consultation.soap_note:
        raise HTTPException(
            status_code=422,
            detail="Cannot approve consultation: SOAP note has not been generated.",
        )

    sn = consultation.soap_note
    if not (
        sn.subjective and sn.subjective.strip()
        and sn.objective and sn.objective.strip()
        and sn.assessment and sn.assessment.strip()
        and sn.plan and sn.plan.strip()
    ):
        raise HTTPException(
            status_code=422,
            detail="Cannot approve consultation: All SOAP sections must be non-empty.",
        )

    if not consultation.transcription or not consultation.transcription.strip():
        raise HTTPException(
            status_code=422,
            detail="Cannot approve consultation: Transcript cannot be empty.",
        )

    approver_name = payload.approved_by.strip()
    if not approver_name:
        raise HTTPException(status_code=422, detail="Reviewer identity (approved_by) is required.")

    approval_time = datetime.now(timezone.utc)
    consultation.status = "approved"
    consultation.review_status = "approved"
    consultation.approved_by = approver_name
    consultation.approved_at = approval_time
    consultation.approval_notes = payload.approval_notes

    db.commit()
    db.refresh(consultation)

    logger.info("Consultation id=%s approved by %s", consultation.id, approver_name)
    return {
        "consultation_id": consultation.id,
        "status": "approved",
        "review_status": "approved",
        "approved_by": approver_name,
        "approved_at": approval_time,
        "approval_notes": payload.approval_notes,
    }


@router.get("", response_model=List[schemas.ConsultationOut])
def list_consultations(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    status: Optional[str] = Query(None),
    review_status: Optional[str] = Query(None),
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    List all consultations for the authenticated clinician.
    Supports pagination and filtering by processing/review status.
    """
    query = (
        db.query(models.Transcription)
        .options(
            selectinload(models.Transcription.entities),
            selectinload(models.Transcription.soap_note),
        )
        .filter(models.Transcription.user_id == current_user.id)
    )

    if status:
        query = query.filter(models.Transcription.status == status)
    if review_status:
        query = query.filter(models.Transcription.review_status == review_status)

    records = query.order_by(models.Transcription.created_at.desc()).offset(skip).limit(limit).all()
    return records


@router.get("/{consultation_id}", response_model=schemas.ConsultationOut)
def get_consultation(
    consultation_id: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Retrieve full details of a specific consultation by identifier.
    """
    consultation = (
        db.query(models.Transcription)
        .options(
            selectinload(models.Transcription.entities),
            selectinload(models.Transcription.soap_note),
        )
        .filter(
            models.Transcription.id == consultation_id,
            models.Transcription.user_id == current_user.id,
        )
        .first()
    )

    if not consultation:
        raise HTTPException(status_code=404, detail="Consultation not found.")

    return consultation


@router.delete("/{consultation_id}/audio", status_code=status.HTTP_200_OK)
def delete_consultation_audio(
    consultation_id: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Purge the stored audio recording for a consultation from disk while preserving
    the transcript, clinical entities, and generated SOAP notes.
    """
    consultation = (
        db.query(models.Transcription)
        .filter(
            models.Transcription.id == consultation_id,
            models.Transcription.user_id == current_user.id,
        )
        .first()
    )

    if not consultation:
        raise HTTPException(status_code=404, detail="Consultation not found.")

    if consultation.audio_path:
        safe_delete_audio_file(consultation.audio_path)
        consultation.audio_path = None
        db.commit()

    return {"success": True, "message": "Consultation audio removed."}


@router.delete("/{consultation_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_consultation(
    consultation_id: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Permanently delete a consultation record, including associated transcript,
    entities, SOAP notes, and unlinks the audio file from the storage directory.
    """
    consultation = (
        db.query(models.Transcription)
        .filter(
            models.Transcription.id == consultation_id,
            models.Transcription.user_id == current_user.id,
        )
        .first()
    )

    if not consultation:
        raise HTTPException(status_code=404, detail="Consultation not found.")

    if consultation.audio_path:
        safe_delete_audio_file(consultation.audio_path)

    db.delete(consultation)
    db.commit()

