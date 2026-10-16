# schemas.py
# Pydantic models used for request validation and response serialisation.
#
# Why separate schemas from ORM models?
# SQLAlchemy models describe the database structure. Pydantic schemas describe
# what comes in over HTTP and what goes out. Keeping them separate means you
# can return a subset of fields (e.g. never return hashed_password), validate
# incoming data before it touches the database, and evolve the API shape
# independently from the schema.

from pydantic import BaseModel, EmailStr, Field, field_validator
from typing import Optional, List, Literal
from datetime import datetime


# ── Auth ──────────────────────────────────────────────────────────────────────

# Enforced server-side — the frontend length check is a UX affordance, not a
# security control.
PASSWORD_MIN_LENGTH = 8
PASSWORD_MAX_LENGTH = 128


class RegisterRequest(BaseModel):
    email:      EmailStr
    password:   str = Field(min_length=PASSWORD_MIN_LENGTH, max_length=PASSWORD_MAX_LENGTH)
    first_name: str = Field(min_length=1, max_length=100)
    last_name:  str = Field(min_length=1, max_length=100)
    specialty:  Optional[str] = None


class LoginRequest(BaseModel):
    email:    EmailStr
    # max_length matches RegisterRequest so that the same bcrypt cost applies.
    # Omitting this allows an attacker to send an arbitrarily large string and
    # make bcrypt (which is O(n) in input length) consume all available CPU.
    password: str = Field(max_length=PASSWORD_MAX_LENGTH)


class TokenResponse(BaseModel):
    access_token: str
    token_type:   str = "bearer"
    user: "UserPublic"


class NoteStyleProfile(BaseModel):
    note_style_preset: Literal["balanced", "concise", "detailed"] = "balanced"
    preferred_focus: Literal["general", "symptom_driven", "assessment_driven", "plan_driven"] = "general"
    include_bullets_in_plan: bool = False
    include_patient_friendly_language: bool = False


class UserPublic(BaseModel):
    id:         int
    email:      str
    first_name: str
    last_name:  str
    specialty:  Optional[str]
    hospital:   Optional[str]
    license_no: Optional[str]
    note_style_preset: Literal["balanced", "concise", "detailed"] = "balanced"
    preferred_focus: Literal["general", "symptom_driven", "assessment_driven", "plan_driven"] = "general"
    include_bullets_in_plan: bool = False
    include_patient_friendly_language: bool = False

    class Config:
        from_attributes = True


# Required for forward reference in TokenResponse
TokenResponse.model_rebuild()


class UpdateProfileRequest(BaseModel):
    first_name: Optional[str] = Field(default=None, max_length=100)
    last_name:  Optional[str] = Field(default=None, max_length=100)
    specialty:  Optional[str] = Field(default=None, max_length=200)
    hospital:   Optional[str] = Field(default=None, max_length=200)
    license_no: Optional[str] = Field(default=None, max_length=80)
    note_style_preset: Optional[Literal["balanced", "concise", "detailed"]] = None
    preferred_focus: Optional[Literal["general", "symptom_driven", "assessment_driven", "plan_driven"]] = None
    include_bullets_in_plan: Optional[bool] = None
    include_patient_friendly_language: Optional[bool] = None


# ── History ───────────────────────────────────────────────────────────────────

class EntityOut(BaseModel):
    text:       str
    label:      str
    confidence: float
    start:      int
    end:        int

    class Config:
        from_attributes = True


class EvidenceStatementOut(BaseModel):
    id:             str
    section:        str
    statement:      str
    status:         str  # "supported" | "unsupported" | "conflicting" | "ambiguous"
    evidence_quote: Optional[str] = None
    evidence_start: Optional[int] = None
    evidence_end:   Optional[int] = None
    similarity:     float = 0.0
    review_message: Optional[str] = None


class EvidenceLinksOut(BaseModel):
    disclaimer:        str
    supported_count:   int = 0
    unsupported_count: int = 0
    conflicting_count: int = 0
    ambiguous_count:   int = 0
    total_statements:  int = 0
    statements:        List[EvidenceStatementOut] = []


class SoapNoteOut(BaseModel):
    subjective:     Optional[str] = None
    objective:      Optional[str] = None
    assessment:     Optional[str] = None
    plan:           Optional[str] = None
    source:         Optional[str] = None
    review_flags:   List[str] = []
    evidence_links: Optional[EvidenceLinksOut] = None

    @field_validator("review_flags", mode="before")
    @classmethod
    def parse_review_flags(cls, v):
        if isinstance(v, str):
            try:
                import json
                parsed = json.loads(v)
                return parsed if isinstance(parsed, list) else []
            except Exception:
                return [v] if v.strip() else []
        elif isinstance(v, list):
            return v
        return []

    @field_validator("evidence_links", mode="before")
    @classmethod
    def parse_evidence_links(cls, v):
        if isinstance(v, str):
            try:
                import json
                parsed = json.loads(v)
                return parsed if isinstance(parsed, dict) else None
            except Exception:
                return None
        return v

    class Config:
        from_attributes = True


class HistoryEntryOut(BaseModel):
    id:                    int
    patient_id:            str
    filename:              str
    transcription:         str
    medical_content_score: float
    duration:              Optional[str]
    status:                str
    review_status:         str = "draft"
    approved_by:           Optional[str] = None
    approved_at:           Optional[datetime] = None
    approval_notes:        Optional[str] = None
    created_at:            datetime
    entities:              List[EntityOut]
    soap_note:             Optional[SoapNoteOut]

    class Config:
        from_attributes = True


# ── Consultations ─────────────────────────────────────────────────────────────

class ConsultationUploadResponse(BaseModel):
    id:            int
    patient_id:    str
    title:         Optional[str] = None
    filename:      str
    status:        str
    review_status: str
    created_at:    datetime

    class Config:
        from_attributes = True


class TranscriptResponse(BaseModel):
    id:            int
    patient_id:    str
    title:         Optional[str] = None
    transcription: str
    review_status: str
    entities:      List[EntityOut] = []

    class Config:
        from_attributes = True


class TranscriptUpdateRequest(BaseModel):
    transcription: str = Field(min_length=1, description="Clinician-edited transcript text")


class SoapResponse(BaseModel):
    subjective:     Optional[str] = None
    objective:      Optional[str] = None
    assessment:     Optional[str] = None
    plan:           Optional[str] = None
    source:         Optional[str] = None
    review_flags:   List[str] = []
    evidence_links: Optional[EvidenceLinksOut] = None
    status:         Optional[str] = None
    review_status:  str
    is_draft:       bool = True
    disclaimer:     Optional[str] = "AI-generated clinical draft. Requires clinician review, editing, and approval before signing."
    updated_at:     Optional[datetime] = None

    class Config:
        from_attributes = True


class SoapUpdateRequest(BaseModel):
    subjective: str = Field(min_length=1, description="Subjective section")
    objective:  str = Field(min_length=1, description="Objective section")
    assessment: str = Field(min_length=1, description="Assessment section")
    plan:       str = Field(min_length=1, description="Plan section")


class ApproveRequest(BaseModel):
    approved_by:    str = Field(min_length=1, max_length=150, description="Reviewing clinician name or license")
    approval_notes: Optional[str] = None


class ApproveResponse(BaseModel):
    consultation_id: int
    status:          str = "approved"
    review_status:   str
    approved_by:     str
    approved_at:     datetime
    approval_notes:  Optional[str] = None



class ConsultationOut(BaseModel):
    id:                    int
    patient_id:            str
    title:                 Optional[str] = None
    filename:              str
    transcription:         str
    medical_content_score: float
    asr_confidence:        Optional[float] = None
    duration:              Optional[str] = None
    status:                str
    review_status:         str
    approved_by:           Optional[str] = None
    approved_at:           Optional[datetime] = None
    approval_notes:        Optional[str] = None
    created_at:            datetime
    entities:              List[EntityOut] = []
    soap_note:             Optional[SoapNoteOut] = None

    class Config:
        from_attributes = True

