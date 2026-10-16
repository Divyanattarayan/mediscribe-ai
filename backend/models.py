# models.py
# SQLAlchemy ORM models. Each class maps to one database table.
#
# Why store entities and soap_notes in separate tables rather than as JSON
# columns on transcriptions?
# Separate tables allow querying — e.g. "show all transcriptions where
# ibuprofen was mentioned" or "fetch only the SOAP note without loading
# the full entity list". JSON columns make queries like these impossible
# without scanning every row. For a portfolio project this also demonstrates
# proper relational design.

from sqlalchemy import Column, Integer, String, Float, Boolean, DateTime, ForeignKey, Text
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from database import Base


class User(Base):
    __tablename__ = "users"

    id            = Column(Integer, primary_key=True, index=True)
    email         = Column(String, unique=True, index=True, nullable=False)
    hashed_password = Column(String, nullable=False)
    first_name    = Column(String, nullable=False)
    last_name     = Column(String, nullable=False)
    specialty     = Column(String, nullable=True)
    hospital      = Column(String, nullable=True)
    license_no    = Column(String, nullable=True)
    note_style_preset = Column(String, nullable=False, default="balanced", server_default="balanced")
    preferred_focus = Column(String, nullable=False, default="general", server_default="general")
    include_bullets_in_plan = Column(Boolean, nullable=False, default=False, server_default="false")
    include_patient_friendly_language = Column(Boolean, nullable=False, default=False, server_default="false")
    is_active     = Column(Boolean, default=True)
    created_at    = Column(DateTime(timezone=True), server_default=func.now())

    # One user has many transcriptions
    transcriptions = relationship("Transcription", back_populates="user", cascade="all, delete-orphan")


class Transcription(Base):
    __tablename__ = "transcriptions"

    id               = Column(Integer, primary_key=True, index=True)
    user_id          = Column(Integer, ForeignKey("users.id"), nullable=False)
    patient_id       = Column(String, nullable=False)       # PT-##### generated ID
    filename         = Column(String, nullable=False)
    transcription    = Column(Text, nullable=False)
    # `validate_medical_content`'s term-density score, 0-100. NOT a confidence
    # in the note: it is computed from the transcript before a note exists, and
    # gates non-clinical audio. Renamed in 20260911_0004 because the UI was
    # presenting it as the system's confidence in its own output.
    medical_content_score = Column(Float, nullable=False, default=0.0)

    # Mean per-word probability from the acoustic model — the first genuine
    # confidence in the schema. Nullable because only the faster-whisper path
    # with word timestamps produces one; a row without it has no value rather
    # than a zero.
    asr_confidence = Column(Float, nullable=True)
    duration         = Column(String, nullable=True)
    status           = Column(String, default="complete")
    title            = Column(String, nullable=True)
    review_status    = Column(String, nullable=False, default="draft", server_default="draft")   # draft | needs_review | approved
    approved_by      = Column(String, nullable=True)
    approved_at      = Column(DateTime(timezone=True), nullable=True)
    approval_notes   = Column(Text, nullable=True)
    audio_path       = Column(String, nullable=True)
    created_at       = Column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    user        = relationship("User", back_populates="transcriptions")
    entities    = relationship("MedicalEntity", back_populates="transcription", cascade="all, delete-orphan")
    soap_note   = relationship("SoapNote", back_populates="transcription", uselist=False, cascade="all, delete-orphan")


class MedicalEntity(Base):
    __tablename__ = "medical_entities"

    id               = Column(Integer, primary_key=True, index=True)
    transcription_id = Column(Integer, ForeignKey("transcriptions.id"), nullable=False)
    text             = Column(String, nullable=False)
    label            = Column(String, nullable=False)   # CHEMICAL, DISEASE, SYMPTOM, TEST, PROCEDURE
    confidence       = Column(Float, default=0.0)
    start            = Column(Integer, default=0)
    end              = Column(Integer, default=0)

    # Assertion attributes (see clinical_assertions.py). Without these, a
    # denied symptom and a reported one are the same row.
    negated          = Column(Boolean, nullable=False, default=False, server_default="false")
    temporality      = Column(String, nullable=False, default="current", server_default="current")   # current | historical | hypothetical
    experiencer      = Column(String, nullable=False, default="patient", server_default="patient")   # patient | family
    uncertain        = Column(Boolean, nullable=False, default=False, server_default="false")
    assertion_source = Column(String, nullable=False, default="default", server_default="default")

    # Ontology linkage (see ontology.py). An RxNorm medication code is a
    # resolution; an ICD-10 condition code is a ranked suggestion, which is why
    # the review flag is stored alongside rather than inferred from the system.
    ontology_system  = Column(String, nullable=True)   # RXNORM | ICD10CM
    ontology_code    = Column(String, nullable=True)
    ontology_display = Column(String, nullable=True)
    ontology_requires_review = Column(Boolean, nullable=False, default=False, server_default="false")

    transcription = relationship("Transcription", back_populates="entities")


class SoapNote(Base):
    __tablename__ = "soap_notes"

    id               = Column(Integer, primary_key=True, index=True)
    transcription_id = Column(Integer, ForeignKey("transcriptions.id"), nullable=False, unique=True)
    subjective       = Column(Text, nullable=True)
    objective        = Column(Text, nullable=True)
    assessment       = Column(Text, nullable=True)
    plan             = Column(Text, nullable=True)
    source           = Column(String, nullable=True)   # "groq-llama-3.3-70b-versatile" or "rule-based-fallback"
    review_flags     = Column(Text, nullable=True)     # JSON encoded list of clinical review flags
    evidence_links   = Column(Text, nullable=True)     # JSON encoded evidence linking mappings
    created_at       = Column(DateTime(timezone=True), server_default=func.now())
    updated_at       = Column(DateTime(timezone=True), nullable=True, onupdate=func.now())

    transcription = relationship("Transcription", back_populates="soap_note")

    @property
    def parsed_review_flags(self) -> list:
        if not self.review_flags:
            return []
        try:
            import json
            val = json.loads(self.review_flags)
            return val if isinstance(val, list) else []
        except Exception:
            return []

    @property
    def parsed_evidence_links(self) -> dict | None:
        if not self.evidence_links:
            return None
        try:
            import json
            val = json.loads(self.evidence_links)
            return val if isinstance(val, dict) else None
        except Exception:
            return None
