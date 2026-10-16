# MediScribe AI — Data Flow Architecture

This document details the complete end-to-end data lifecycle in MediScribe AI, covering audio intake, validation checks, automated intelligence generation, clinician review and edit phases, and permanent approval.

---

## 1. Multi-Step Consultation Workflow (Primary Path)

The primary consultation workflow allows discrete inspection and intervention at each stage of note generation.

```mermaid
sequenceDiagram
    autonumber
    actor Clinician as Clinician (Browser)
    participant API as FastAPI Backend
    participant Storage as File Storage (uploads/)
    participant STT as TranscriptionService (Whisper)
    participant Val as ContentValidator
    participant NLP as MedicalNLPService (scispaCy)
    participant LLM as Groq LLaMA 3.3
    participant Evid as EvidenceLinkingService
    participant DB as Relational Database

    %% Step 1: Upload
    Clinician->>API: POST /api/consultations/upload (Audio file + metadata)
    API->>API: Validate file ext (.wav, .mp3, .m4a, .webm) & size (<50MB)
    alt Invalid Audio
        API-->>Clinician: 400 Bad Request (Invalid file type or size)
    else Valid Audio
        API->>Storage: Save audio to uploads/consultations/{id}
        API->>DB: INSERT Consultation (status="uploaded")
        API-->>Clinician: 201 Created (Consultation ID, status="uploaded")
    end

    %% Step 2: Transcribe
    Clinician->>API: POST /api/consultations/{id}/transcribe
    API->>DB: UPDATE status="transcribing"
    API->>STT: Transcribe audio file locally
    STT-->>API: Raw transcript text + word confidence segments
    API->>DB: UPDATE Consultation (transcript_text, segments, status="transcript_ready")
    API-->>Clinician: 200 OK (Transcript data)

    %% Step 3: Transcript Review & Edit
    Clinician->>Clinician: Review & edit transcript lines in UI
    Clinician->>API: PUT /api/consultations/{id}/transcript (Corrected text)
    API->>DB: UPDATE transcript_text
    API-->>Clinician: 200 OK (Updated transcript)

    %% Step 4: Medical Information Extraction
    Clinician->>API: POST /api/consultations/{id}/extract
    API->>Val: Check medical term density & clinical markers
    alt Non-Medical Content
        Val-->>API: Rejected (Insufficient medical density)
        API-->>Clinician: 422 Unprocessable Entity (Non-clinical recording)
    else Clinical Content Confirmed
        API->>NLP: Extract clinical entities & assertions
        NLP-->>API: Extracted entities (Symptoms, Meds, Conditions, Assertions)
        API->>DB: INSERT MedicalEntity records
        API-->>Clinician: 200 OK (Entity list)
    end

    %% Step 5: SOAP Draft Generation
    Clinician->>API: POST /api/consultations/{id}/soap
    API->>LLM: Prompt LLaMA 3.3 with transcript + extracted entities
    alt LLM API Failure or No Key
        API->>API: Fallback to deterministic rule-based generator
    else LLM Success
        LLM-->>API: Validated JSON {subjective, objective, assessment, plan, review_flags}
    end
    API->>Evid: Compute evidence links between SOAP statements & transcript
    Evid-->>API: EvidenceMap (supported, unsupported, conflicting)
    API->>DB: INSERT SoapNote & UPDATE status="draft_generated", review_status="needs_review"
    API-->>Clinician: 200 OK (SOAP draft + evidence + review warnings)

    %% Step 6: SOAP Review & Edit
    Clinician->>Clinician: Inspect evidence quotes & edit SOAP sections
    Clinician->>API: PUT /api/consultations/{id}/soap (Edited sections)
    API->>DB: UPDATE SoapNote & status="in_review"
    API-->>Clinician: 200 OK (Saved SOAP changes)

    %% Step 7: Explicit Approval
    Clinician->>API: POST /api/consultations/{id}/approve
    API->>API: Check approval criteria (valid SOAP, user ownership)
    API->>DB: UPDATE Consultation (status="approved", review_status="approved", approved_at=now())
    API-->>Clinician: 200 OK (Final approved note confirmation)
```

---

## 2. Monolithic Legacy Pipeline (`POST /api/transcribe`)

For rapid synchronous drafting, the legacy route coordinates transcription, extraction, and SOAP generation in a single HTTP request:

```mermaid
flowchart TD
    Start([Audio Upload Received]) --> ValFile{Audio Valid?<br/>Extension, MIME, Size}
    ValFile -- No --> Err400[400 Bad Request]
    ValFile -- Yes --> SaveTemp[Save file to temp directory]

    SaveTemp --> STT[Whisper Local Transcription]
    STT --> ValContent{ContentValidator<br/>Medical Density Gate}

    ValContent -- Failed --> Err422[422 Unprocessable Entity<br/>Non-clinical Content]
    ValContent -- Passed --> NLP[scispaCy + medspaCy Entity Extraction]

    NLP --> GroqCheck{Groq API Key<br/>Available?}
    GroqCheck -- Yes --> GroqCall[Call Groq LLaMA 3.3]
    GroqCheck -- No --> FallbackGen[Rule-Based Fallback Generator]
    GroqCall -- API Error --> FallbackGen
    GroqCall -- Success --> EvidLink[Evidence Linking rapidfuzz]
    FallbackGen --> EvidLink

    EvidLink --> Persist[Persist to DB: Transcription, Entities, SoapNote]
    Persist --> Cleanup[Finally Block: Delete temp audio file]
    Cleanup --> Resp[200 OK: Return Complete Clinical Package]
```

---

## 3. Validation Gates & Error Handling

| Phase | Gate / Check | Failure Mode | Mitigation / Response |
|---|---|---|---|
| **Intake** | File extension whitelist (`.mp3`, `.wav`, `.m4a`, `.ogg`, `.webm`) | Invalid extension | Returns `400 Bad Request` with acceptable format list. |
| **Intake** | File size boundary (Max 50MB) | Payload exceeds 50MB | Returns `400 Bad Request` preventing server memory exhaustion. |
| **Intake** | MIME type inspection via file headers | Spoofed file extension | Rejects stream before disk persistence. |
| **Transcription** | CTranslate2 inference exception | Corrupt audio stream | Returns `500 Internal Server Error`, logs diagnostic trace. |
| **Content Gate** | `ContentValidator` medical density | Non-medical dialogue | Returns `422 Unprocessable Entity` ("Transcript does not meet clinical threshold"). |
| **NER / NLP** | Assertion parsing failure | Unparseable syntax | Defaults entity assertion to `PRESENT` and logs warning. |
| **SOAP Gen** | Missing `GROQ_API_KEY` | Environment unconfigured | Transparently activates `_generate_fallback_soap` without breaking pipeline. |
| **SOAP Gen** | Groq rate limit / timeout / connection | External network fault | Catches `GroqRateLimitError` / `GroqTimeoutError`, falls back to rule-based engine. |
| **Evidence** | Fuzzy matching threshold (<50%) | Unverifiable claim | Flags statement as `"Evidence not found — review required."` |
| **Approval** | Clinician authorization & note completeness | Missing required sections | Blocks transition to `approved`, keeps status in `in_review`. |

---

## 4. Clinician Review & Edit State Transitions

The consultation state machine enforces strict governance over document status:

```
[ Uploaded ]
     │
     ▼
[ Transcribing ]
     │
     ▼
[ Transcript Ready ]  <───────────┐ (Clinician edits transcript text)
     │                            │
     ▼                            │
[ Draft Generated ]               │
     │                            │
     ▼                            │
[ In Review ]  ───────────────────┘ (Clinician reviews evidence & modifies sections)
     │
     ▼ (Explicit Clinician Approval Action)
[ Approved ]  ──> Final locked clinical note (Audit timestamp & Clinician ID recorded)
```

1. **Explicit Sign-off**: A consultation note is never automatically set to `approved` by automated processes; it requires an intentional action from an authenticated clinician.
2. **Post-Approval Immutability**: Approved notes preserve historical audit trails and cannot be overwritten without generating a revision entry.
