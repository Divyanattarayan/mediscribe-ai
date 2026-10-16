from dotenv import load_dotenv
load_dotenv()

from console import configure_console

# Before anything else prints: pipeline diagnostics interpolate model output,
# and one unencodable character used to abort a request from inside a print().
configure_console()

from fastapi import FastAPI, File, Header, UploadFile, HTTPException, Request, Depends, status, Form
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload
import logging
import os
import time
import uuid

from transcription import transcribe_audio
from entity_extraction import extract_medical_entities
from clinical_extraction import extract_clinical_representation
from clinical_facts import build_fact_table, fact_table_summary, facts_to_json
from soap_generator import generate_soap_note, format_soap_note_text
from content_validator import validate_medical_content
from spell_correction import correct_medical_spelling
from database import get_db
from decoder_vocabulary import build_vocabulary, specialty_terms
from groq_client import reset_usage, usage_snapshot
from auth import hash_password, verify_password, create_access_token, get_current_user
from documentation_style import normalize_encounter_type, resolve_style_profile
import models
import schemas
from lib.utils import generate_patient_id, format_duration_mmss, safe_delete_audio_file

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("mediscribe")

# Largest audio upload accepted, in bytes. Mirrors `client_max_body_size` in
# nginx.conf so the limit is consistent whether or not traffic passes the proxy.
MAX_UPLOAD_BYTES = 50 * 1024 * 1024

# Audio shorter than this cannot produce a usable clinical note.
MINIMUM_AUDIO_DURATION_SECONDS = 45

ALLOWED_AUDIO_EXTENSIONS = ('.mp3', '.wav', '.m4a', '.webm', '.ogg', '.flac')

# Schema is managed by Alembic. Migrations are applied before this module is
# imported by the start commands in scripts/dev-backend.sh and the Dockerfile.

app = FastAPI(
    title="MediScribe AI API",
    description="Real-time medical transcription and documentation system",
    version="2.0.0"
)

default_cors_origins = [
    "http://localhost",
    "http://127.0.0.1",
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "http://localhost:4173",
    "http://127.0.0.1:4173",
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://localhost:8080",
    "http://127.0.0.1:8080",
]

cors_origins = [
    origin.strip()
    for origin in os.getenv("CORS_ORIGINS", ",".join(default_cors_origins)).split(",")
    if origin.strip()
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=True,
    # Explicit safe-method list — avoids exposing TRACE/CONNECT/OPTIONS-abuse
    # vectors. OPTIONS is included so pre-flight requests continue to work.
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)

UPLOAD_DIR = "uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)


from routers import consultations, live

# ── Health / root ─────────────────────────────────────────────────────────────

@app.get("/")
def read_root():
    return {"message": "Welcome to MediScribe AI", "status": "Server is running", "version": "2.0.0"}


@app.get("/health")
@app.get("/api/health")
def health_check():
    from transcription_service import transcription_service, TRANSCRIPTION_DISCLAIMER
    try:
        model = transcription_service.get_model()
        is_stt_ready = getattr(type(model), "__name__", "") != "_StubWhisperModel"
    except Exception:
        is_stt_ready = False

    return {
        "status": "healthy",
        "service": "MediScribe AI Backend",
        "version": "2.0.0",
        "speech_recognition_configured": is_stt_ready,
        "whisper_model": transcription_service.model_name,
        "llm_configured": bool(os.getenv("GROQ_API_KEY")),
        "nlp_configured": True,
        "disclaimer": TRANSCRIPTION_DISCLAIMER,
    }



app.include_router(consultations.router)
app.include_router(live.router)


# ── Auth ──────────────────────────────────────────────────────────────────────

@app.post("/api/auth/register", response_model=schemas.TokenResponse, status_code=status.HTTP_201_CREATED)
def register(payload: schemas.RegisterRequest, db: Session = Depends(get_db)):
    """
    Register a new user. Returns a JWT token immediately so the frontend
    can log the user in without a separate login step after registration.
    """
    existing = db.query(models.User).filter(models.User.email == payload.email).first()
    if existing:
        raise HTTPException(status_code=409, detail="An account with this email already exists")

    user = models.User(
        email           = payload.email,
        hashed_password = hash_password(payload.password),
        first_name      = payload.first_name,
        last_name       = payload.last_name,
        specialty       = payload.specialty,
    )
    db.add(user)
    try:
        db.commit()
    except IntegrityError:
        # Two concurrent registrations for the same email can both pass the
        # check above; the unique index rejects the loser here.
        db.rollback()
        raise HTTPException(status_code=409, detail="An account with this email already exists")
    db.refresh(user)

    token = create_access_token(user.id)
    return schemas.TokenResponse(access_token=token, user=schemas.UserPublic.model_validate(user))


@app.post("/api/auth/login", response_model=schemas.TokenResponse)
def login(payload: schemas.LoginRequest, db: Session = Depends(get_db)):
    """
    Authenticate an existing user. Returns a JWT token on success.
    Returns 401 for both "email not found" and "wrong password" — deliberately
    vague to prevent email enumeration attacks.
    """
    user = db.query(models.User).filter(models.User.email == payload.email).first()
    if not user or not verify_password(payload.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password"
        )

    token = create_access_token(user.id)
    return schemas.TokenResponse(access_token=token, user=schemas.UserPublic.model_validate(user))


@app.get("/api/auth/me", response_model=schemas.UserPublic)
def get_me(current_user: models.User = Depends(get_current_user)):
    """
    Returns the profile of the currently authenticated user.
    Used by the frontend on app load to restore the user session from a stored token.
    """
    return current_user


@app.put("/api/auth/me", response_model=schemas.UserPublic)
def update_me(
    payload: schemas.UpdateProfileRequest,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    updates = payload.model_dump(exclude_unset=True)
    for field, value in updates.items():
        setattr(current_user, field, value)
    db.add(current_user)
    db.commit()
    db.refresh(current_user)
    return current_user


# ── History ───────────────────────────────────────────────────────────────────

@app.get("/api/history", response_model=list[schemas.HistoryEntryOut])
def get_history(
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Returns all transcriptions for the authenticated user, newest first.
    """
    return (
        db.query(models.Transcription)
        .options(
            selectinload(models.Transcription.entities),
            selectinload(models.Transcription.soap_note),
        )
        .filter(models.Transcription.user_id == current_user.id)
        .order_by(models.Transcription.created_at.desc())
        .all()
    )

@app.get("/api/history/{transcription_id}", response_model=schemas.HistoryEntryOut)
def get_transcription(
    transcription_id: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    record = (
        db.query(models.Transcription)
        .options(
            selectinload(models.Transcription.entities),
            selectinload(models.Transcription.soap_note),
        )
        # Ownership enforced in the WHERE clause — not in a Python guard
        # after loading, which would be a TOCTOU window on high-throughput
        # servers where two requests can interleave between the fetch and check.
        .filter(
            models.Transcription.id == transcription_id,
            models.Transcription.user_id == current_user.id,
        )
        .first()
    )
    if not record:
        raise HTTPException(status_code=404, detail="Transcription not found")
    return record


@app.delete("/api/history/{transcription_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_history_item(
    transcription_id: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Deletes a transcription owned by the authenticated user and cleans up any stored audio file.
    Returns 404 if not found, 403 if it belongs to a different user.
    """
    record = db.query(models.Transcription).filter(models.Transcription.id == transcription_id).first()
    if not record:
        raise HTTPException(status_code=404, detail="Transcription not found")
    if record.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorised")
    if record.audio_path:
        safe_delete_audio_file(record.audio_path)
    db.delete(record)
    db.commit()


@app.delete("/api/history", status_code=status.HTTP_204_NO_CONTENT)
def delete_all_history(
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Deletes all transcriptions owned by the authenticated user and cleans up their audio files.
    """
    records = (
        db.query(models.Transcription)
        .filter(models.Transcription.user_id == current_user.id)
        .all()
    )
    for record in records:
        if record.audio_path:
            safe_delete_audio_file(record.audio_path)
        db.delete(record)
    db.commit()


@app.delete("/api/auth/me", status_code=status.HTTP_204_NO_CONTENT)
def delete_my_account(
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Permanently deletes the authenticated user's account and all related data (including stored audio files).
    """
    for record in current_user.transcriptions:
        if record.audio_path:
            safe_delete_audio_file(record.audio_path)
    db.delete(current_user)
    db.commit()


# ── Transcription ─────────────────────────────────────────────────────────────

@app.post("/api/transcribe")
async def transcribe_audio_endpoint(
    request: Request,
    file: UploadFile = File(...),
    encounter_type: str = Form(...),
    note_style_preset: str | None = Form(default=None),
    preferred_focus: str | None = Form(default=None),
    include_bullets_in_plan: bool | None = Form(default=None),
    include_patient_friendly_language: bool | None = Form(default=None),
    audio_duration_seconds: float | None = Header(default=None, alias="X-Audio-Duration-Seconds"),
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Transcribe uploaded audio, extract entities, generate SOAP note, and
    persist the full result to the database linked to the authenticated user.
    """
    logger.info("Transcription request from user id=%s", current_user.id)

    # Reject oversized uploads before reading the body into memory. The
    # multipart envelope adds a little overhead, so allow a small margin.
    declared_length = request.headers.get("content-length")
    if declared_length is not None:
        try:
            if int(declared_length) > MAX_UPLOAD_BYTES + 1024 * 1024:
                raise HTTPException(status_code=413, detail="Audio file exceeds the 50 MB limit.")
        except ValueError:
            pass

    resolved_encounter_type = normalize_encounter_type(encounter_type)
    resolved_style_profile = resolve_style_profile(
        user=current_user,
        overrides={
            "note_style_preset": note_style_preset,
            "preferred_focus": preferred_focus,
            "include_bullets_in_plan": include_bullets_in_plan,
            "include_patient_friendly_language": include_patient_friendly_language,
        },
    )

    # The original filename is display-only metadata. It is never used to build a
    # filesystem path — a crafted name like "../../main.py" must not escape the
    # upload directory, and two users uploading "recording.mp3" must not collide.
    original_filename = file.filename or "recording"
    file_ext = os.path.splitext(original_filename)[1].lower()
    if file_ext not in ALLOWED_AUDIO_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"File type {file_ext or '(none)'} not supported. Allowed: {list(ALLOWED_AUDIO_EXTENSIONS)}"
        )

    # Per-request token accounting. The pipeline makes several model calls, and
    # without this the only signal that a change made it more expensive is a
    # rate-limit error days later.
    reset_usage()

    stored_name = f"{uuid.uuid4().hex}{file_ext}"
    file_path = os.path.join(UPLOAD_DIR, stored_name)
    request_started_at = time.perf_counter()

    def _too_short_response(duration_seconds: float | None) -> dict:
        return {
            "success": False,
            "filename": original_filename,
            "transcription": "",
            "validation": {
                "is_valid": False,
                "confidence_score": 0.0,
                "reason": "Recording is too short to process. Please upload a longer clinical audio clip.",
                "details": {
                    "audio_duration_seconds": round(duration_seconds, 3) if duration_seconds is not None else None,
                    "minimum_audio_duration_seconds": MINIMUM_AUDIO_DURATION_SECONDS,
                },
            },
            "processing_time": round(time.perf_counter() - request_started_at, 3),
            "message": "Recording is too short to process. Please upload a longer clinical audio clip.",
        }

    try:
        content = await file.read()

        # Exact size check now that the body is in hand.
        if len(content) > MAX_UPLOAD_BYTES:
            raise HTTPException(status_code=413, detail="Audio file exceeds the 50 MB limit.")

        with open(file_path, "wb") as buffer:
            buffer.write(content)

        # Cheap pre-flight using the client-supplied hint. This only saves work;
        # the authoritative check is against the real duration below.
        if audio_duration_seconds is not None and audio_duration_seconds < MINIMUM_AUDIO_DURATION_SECONDS:
            return _too_short_response(audio_duration_seconds)

        # Step 1: Transcribe
        #
        # Every ML stage below is blocking CPU work. This route is `async def`,
        # so calling them inline would hold the event loop for the whole job and
        # stall every other request. They run on the threadpool instead.
        logger.info("Step 1: transcription")
        # Bias decoding toward terms this clinician's own previous encounters
        # contained, rather than the fixed demo-recording list this replaced.
        # Empty for a new user, which leaves the decoder unbiased.
        vocabulary = specialty_terms(current_user) + build_vocabulary(db, current_user.id)
        if vocabulary:
            logger.info("Decoder vocabulary: %d terms from prior encounters", len(vocabulary))

        asr_result = await run_in_threadpool(transcribe_audio, file_path, vocabulary)
        if not asr_result["success"]:
            raise RuntimeError(f"Transcription failed: {asr_result['error']}")
        transcription_result = asr_result["text"]
        audio_duration = asr_result["duration"]
        asr_confidence = asr_result.get("confidence")
        logger.debug("Transcript processed: length=%d characters", len(transcription_result))

        # Authoritative minimum-duration guard, using the decoded audio length.
        if audio_duration is not None and audio_duration < MINIMUM_AUDIO_DURATION_SECONDS:
            return _too_short_response(audio_duration)

        logger.info("Step 1b: transcript normalisation")
        transcription_result, corrections = await run_in_threadpool(
            correct_medical_spelling, transcription_result, verbose=False
        )
        logger.info("Normalisation: %d word corrections", len(corrections))

        # Step 2: Validate
        logger.info("Step 2: content validation")
        validation_result = await run_in_threadpool(validate_medical_content, transcription_result)
        logger.info(
            "Validation valid=%s confidence=%s",
            validation_result["is_valid"],
            validation_result["confidence_score"],
        )

        if not validation_result['is_valid']:
            return {
                "success": False,
                "filename": original_filename,
                "transcription": transcription_result,
                "validation": validation_result,
                "processing_time": round(time.perf_counter() - request_started_at, 3),
                "message": validation_result["reason"],
            }

        # Step 3: Extract entities
        logger.info("Step 3: entity extraction")
        entities_result = await run_in_threadpool(extract_medical_entities, transcription_result)
        logger.info(
            "Extracted %d entities; assertions: %s; ontology: %s",
            entities_result["total_entities"],
            entities_result.get("assertion_counts", {}),
            entities_result.get("ontology_counts", {}),
        )

        # Step 4: Build structured clinical representation
        logger.info("Step 4: structured clinical extraction")
        clinical_representation = await run_in_threadpool(
            extract_clinical_representation,
            transcription_result,
            entities_result["categorized"],
            resolved_encounter_type,
        )

        # Step 5: Build the fact table
        #
        # Every row carries the transcript span that supports it, so the note
        # generated from them has provenance by construction rather than by
        # inspection afterwards.
        logger.info("Step 5: fact table")
        fact_table = await run_in_threadpool(
            build_fact_table, transcription_result, entities_result["entities"]
        )
        facts_summary = fact_table_summary(fact_table)
        logger.info("Fact table: %s", facts_summary)

        # Step 6: Generate SOAP note
        logger.info("Step 6: SOAP note generation")
        soap_note = await run_in_threadpool(
            generate_soap_note,
            transcription_result,
            entities_result['categorized'],
            clinical_representation,
            resolved_style_profile,
            fact_table,
        )
        soap_text = format_soap_note_text(soap_note)

        # Step 7: Persist to database
        logger.info("Step 7: persisting to database")
        medical_content_score = float(validation_result['confidence_score']) * 100

        db_transcription = models.Transcription(
            user_id          = current_user.id,
            patient_id       = generate_patient_id(),
            filename         = original_filename,
            transcription    = transcription_result,
            medical_content_score = medical_content_score,
            duration         = format_duration_mmss(audio_duration),
            asr_confidence   = asr_confidence,
            status           = "complete",
        )
        db.add(db_transcription)
        db.flush()  # get db_transcription.id before committing

        for ent in entities_result['entities']:
            ontology = ent.get('ontology') or {}
            db.add(models.MedicalEntity(
                transcription_id = db_transcription.id,
                text             = ent.get('text', ''),
                label            = ent.get('label', ''),
                confidence       = float(ent.get('confidence', 0.0)),
                start            = int(ent.get('start', 0)),
                end              = int(ent.get('end', 0)),
                negated          = bool(ent.get('negated', False)),
                temporality      = str(ent.get('temporality', 'current')),
                experiencer      = str(ent.get('experiencer', 'patient')),
                uncertain        = bool(ent.get('uncertain', False)),
                assertion_source = str(ent.get('assertion_source', 'default')),
                ontology_system  = ontology.get('system'),
                ontology_code    = ontology.get('code'),
                ontology_display = ontology.get('display'),
                ontology_requires_review = bool(ontology.get('requires_review', False)),
            ))

        # soap_note sections may be strings (Groq) or dicts (fallback)
        def _to_str(val) -> str:
            if isinstance(val, str):
                return val
            if isinstance(val, dict):
                return "\n".join(f"{k}: {v}" for k, v in val.items())
            return str(val) if val is not None else ""

        db.add(models.SoapNote(
            transcription_id = db_transcription.id,
            subjective       = _to_str(soap_note.get('subjective')),
            objective        = _to_str(soap_note.get('objective')),
            assessment       = _to_str(soap_note.get('assessment')),
            plan             = _to_str(soap_note.get('plan')),
            source           = soap_note.get('source', ''),
        ))

        db.commit()
        db.refresh(db_transcription)
        processing_time = round(time.perf_counter() - request_started_at, 3)
        token_usage = usage_snapshot()
        logger.info(
            "Persisted transcription id=%s in %ss (%d model calls, %d tokens)",
            db_transcription.id, processing_time,
            token_usage["calls"], token_usage["total_tokens"],
        )

        return {
            "success": True,
            "filename": original_filename,
            "transcription": transcription_result,
            "validation": validation_result,
            "entities": {
                "total":       entities_result["total_entities"],
                "breakdown":   entities_result["category_counts"],
                "assertions":  entities_result.get("assertion_counts", {}),
                "ontology":    entities_result.get("ontology_counts", {}),
                "categorized": entities_result["categorized"],
                "all_entities": entities_result["entities"],
            },
            "soap_note":      soap_note,
            "soap_note_text": soap_text,
            "clinical_representation": clinical_representation,
            "fact_table": facts_to_json(fact_table),
            "fact_table_summary": facts_summary,
            "verification": soap_note.get("verification"),
            "quality_report": soap_note.get("quality_report"),
            "quality_score": soap_note.get("quality_score"),
            "resolved_encounter_type": resolved_encounter_type,
            "resolved_style_profile": resolved_style_profile,
            "processing_time": processing_time,
            "asr_confidence": asr_confidence,
            "token_usage":    token_usage,
            "db_id":          db_transcription.id,
        }

    except HTTPException:
        raise
    except Exception:
        logger.exception("Unhandled error in /api/transcribe")
        raise HTTPException(status_code=500, detail="Transcription failed. Please try again.")
    finally:
        if os.path.exists(file_path):
            os.remove(file_path)
