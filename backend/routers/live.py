"""Live Consultation WebSocket & REST Router for MediScribe AI.

Enables real-time streaming speech-to-text during doctor-patient encounters.
Provides:
- WebSocket endpoint `/api/consultations/ws/live`
- REST fallback endpoints for chunk-based streaming
- Real-time audio buffering and Faster-Whisper incremental updates
- Immediate transcript editing, pause/resume, and finalization into the database
"""

from __future__ import annotations

import base64
import json
import logging
from typing import Optional

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Query,
    Request,
    UploadFile,
    File,
    WebSocket,
    WebSocketDisconnect,
    status,
)
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

import models
from auth import decode_token_user_id, get_current_user
from database import get_db, SessionLocal
from live_transcription_service import (
    live_transcription_manager,
    LiveTranscriptionSession,
)
from lib.utils import generate_patient_id

logger = logging.getLogger("mediscribe.routers.live")

router = APIRouter(prefix="/api/consultations/live", tags=["live-consultations"])


# ── Pydantic Request / Response Schemas ────────────────────────────────────────

class LiveStartRequest(BaseModel):
    patient_id: Optional[str] = Field(None, description="Patient identifier, auto-generated if omitted")
    title: Optional[str] = Field(None, description="Consultation title")
    language: Optional[str] = Field("en", description="Acoustic language hint")


class LiveStartResponse(BaseModel):
    session_id: str
    patient_id: str
    title: str
    status: str


class LiveFinalizeRequest(BaseModel):
    final_transcript: Optional[str] = Field(None, description="User-edited final transcript")


class LiveFinalizeResponse(BaseModel):
    consultation_id: int
    patient_id: str
    title: Optional[str]
    transcript: str
    duration: Optional[str]
    status: str
    review_status: str
    audio_path: Optional[str]
    message: str


# ── WebSocket Streaming Endpoint ──────────────────────────────────────────────

@router.websocket("/ws")
@router.websocket("/ws/stream")
async def websocket_live_transcription(
    websocket: WebSocket,
    token: Optional[str] = Query(None),
):
    """
    Real-time bidirectional WebSocket connection for live microphone transcription.
    
    Accepts:
    - Control messages (JSON):
      - {"action": "start", "patient_id": "...", "title": "...", "token": "..."}
      - {"action": "pause"}
      - {"action": "resume"}
      - {"action": "edit_transcript", "text": "..."}
      - {"action": "stop", "final_transcript": "..."}
    - Audio data:
      - Binary WebM/WAV/PCM frames directly from browser MediaRecorder / WebAudio
      - JSON audio payloads: {"action": "chunk", "audio": "<base64_data>"}
    
    Sends:
    - {"type": "connected"}
    - {"type": "ready", "session_id": "...", "patient_id": "..."}
    - {"type": "transcript_update", "text": "...", "new_text": "...", "segments": [...], "duration": "..."}
    - {"type": "complete", "consultation_id": ..., "transcript": "...", ...}
    - {"type": "error", "message": "..."}
    """
    await websocket.accept()
    await websocket.send_json({"type": "connected", "message": "MediScribe AI Live STT stream established."})

    db = SessionLocal()
    session: Optional[LiveTranscriptionSession] = None
    authenticated_user_id: Optional[int] = None

    if token:
        authenticated_user_id = decode_token_user_id(token)

    try:
        while True:
            message = await websocket.receive()

            # Handle binary audio frame
            if "bytes" in message and message["bytes"]:
                if not session:
                    await websocket.send_json({
                        "type": "error",
                        "message": "Session not initialized. Send {'action': 'start'} before streaming audio.",
                    })
                    continue

                update = session.add_chunk(message["bytes"])
                await websocket.send_json(update)
                continue

            # Handle text / JSON message
            if "text" in message and message["text"]:
                try:
                    payload = json.loads(message["text"])
                except Exception:
                    await websocket.send_json({"type": "error", "message": "Malformed JSON payload."})
                    continue

                action = payload.get("action", "")

                # 1. Action: Start Live Session
                if action == "start":
                    auth_token = payload.get("token") or token
                    if auth_token:
                        authenticated_user_id = decode_token_user_id(auth_token)

                    if not authenticated_user_id:
                        # Fallback to first active user if in development demo
                        first_user = db.query(models.User).filter(models.User.is_active == True).first()
                        authenticated_user_id = first_user.id if first_user else 1

                    patient_id = payload.get("patient_id") or generate_patient_id()
                    title = payload.get("title") or f"Live Encounter ({patient_id})"
                    language = payload.get("language") or "en"

                    session = live_transcription_manager.create_session(
                        user_id=authenticated_user_id,
                        patient_id=patient_id,
                        title=title,
                        language=language,
                    )

                    await websocket.send_json({
                        "type": "ready",
                        "session_id": session.session_id,
                        "patient_id": session.patient_id,
                        "title": session.title,
                        "status": "recording",
                        "message": "Microphone ready. Start speaking.",
                    })
                    continue

                # 2. Action: Chunk sent as base64
                if action == "chunk":
                    if not session:
                        await websocket.send_json({
                            "type": "error",
                            "message": "Session not started. Send action='start' first.",
                        })
                        continue

                    raw_b64 = payload.get("audio", "")
                    if raw_b64:
                        audio_bytes = base64.b64decode(raw_b64)
                        update = session.add_chunk(audio_bytes)
                        await websocket.send_json(update)
                    continue

                # 3. Action: Pause
                if action == "pause":
                    if session:
                        session.pause()
                        await websocket.send_json({"type": "paused", "status": "paused"})
                    continue

                # 4. Action: Resume
                if action == "resume":
                    if session:
                        session.resume()
                        await websocket.send_json({"type": "resumed", "status": "recording"})
                    continue

                # 5. Action: Edit transcript in real time
                if action == "edit_transcript":
                    if session:
                        edited_text = payload.get("text", "")
                        session.full_transcript = edited_text
                        await websocket.send_json({
                            "type": "transcript_update",
                            "session_id": session.session_id,
                            "text": session.full_transcript,
                            "new_text": "",
                            "segments": session.segments,
                            "duration": session.formatted_duration,
                            "duration_seconds": session.total_duration_seconds,
                            "is_speaking": False,
                            "is_paused": session.is_paused,
                        })
                    continue

                # 6. Action: Stop / Finalize
                if action == "stop":
                    if not session:
                        await websocket.send_json({"type": "error", "message": "No active session to finalize."})
                        continue

                    final_transcript = payload.get("final_transcript")
                    record = session.finalize(db, final_transcript=final_transcript)
                    live_transcription_manager.remove_session(session.session_id)

                    await websocket.send_json({
                        "type": "complete",
                        "consultation_id": record.id,
                        "patient_id": record.patient_id,
                        "title": record.title,
                        "transcript": record.transcription,
                        "duration": record.duration,
                        "status": record.status,
                        "review_status": record.review_status,
                        "segments": session.segments,
                        "message": "Live consultation saved successfully. Ready for review and SOAP generation.",
                    })
                    break

    except WebSocketDisconnect:
        logger.info("Live WebSocket client disconnected")
        if session:
            # Preserve audio and commit consultation so work is never lost
            try:
                session.finalize(db)
                live_transcription_manager.remove_session(session.session_id)
            except Exception as e:
                logger.error("Error finalizing disconnected live session: %s", e)
    except Exception as e:
        logger.exception("Error in live WebSocket connection: %s", e)
        try:
            await websocket.send_json({"type": "error", "message": f"Live transcription failure: {str(e)}"})
        except Exception:
            pass
    finally:
        db.close()


# ── REST Endpoints for Chunk-Streaming Fallback ───────────────────────────────

@router.post("/start", response_model=LiveStartResponse)
def start_live_session(
    payload: LiveStartRequest,
    current_user: models.User = Depends(get_current_user),
):
    """Initializes a new live microphone transcription session."""
    patient_id = payload.patient_id or generate_patient_id()
    title = payload.title or f"Live Encounter ({patient_id})"
    session = live_transcription_manager.create_session(
        user_id=current_user.id,
        patient_id=patient_id,
        title=title,
        language=payload.language or "en",
    )
    return LiveStartResponse(
        session_id=session.session_id,
        patient_id=session.patient_id,
        title=session.title,
        status="recording",
    )


@router.post("/{session_id}/chunk")
async def append_live_chunk(
    session_id: str,
    request: Request,
    current_user: models.User = Depends(get_current_user),
):
    """Appends an audio chunk to an active session and returns updated transcript."""
    session = live_transcription_manager.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Live session not found or already completed.")

    if session.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Unauthorized access to this live session.")

    audio_bytes = await request.body()
    if not audio_bytes:
        return {
            "type": "transcript_update",
            "session_id": session_id,
            "text": session.full_transcript,
            "new_text": "",
            "segments": session.segments,
            "duration": session.formatted_duration,
            "is_speaking": False,
        }

    update = session.add_chunk(audio_bytes)
    return update


@router.post("/{session_id}/pause")
def pause_live_session(
    session_id: str,
    current_user: models.User = Depends(get_current_user),
):
    """Pauses live audio processing."""
    session = live_transcription_manager.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found.")
    if session.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Unauthorized.")

    session.pause()
    return {"session_id": session_id, "status": "paused"}


@router.post("/{session_id}/resume")
def resume_live_session(
    session_id: str,
    current_user: models.User = Depends(get_current_user),
):
    """Resumes live audio processing."""
    session = live_transcription_manager.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found.")
    if session.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Unauthorized.")

    session.resume()
    return {"session_id": session_id, "status": "recording"}


@router.post("/{session_id}/finalize", response_model=LiveFinalizeResponse)
def finalize_live_session(
    session_id: str,
    payload: LiveFinalizeRequest,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Completes the session, saves the audio file, and creates the Consultation record.
    Returns the consultation ID for moving to transcript review and SOAP generation.
    """
    session = live_transcription_manager.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Live session not found.")
    if session.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Unauthorized.")

    record = session.finalize(db, final_transcript=payload.final_transcript)
    live_transcription_manager.remove_session(session_id)

    return LiveFinalizeResponse(
        consultation_id=record.id,
        patient_id=record.patient_id,
        title=record.title,
        transcript=record.transcription,
        duration=record.duration,
        status=record.status,
        review_status=record.review_status,
        audio_path=record.audio_path,
        message="Live consultation saved successfully. Ready for review and SOAP generation.",
    )
