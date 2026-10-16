# MediScribe AI — Component Responsibilities

This document provides a technical inventory of the components across MediScribe AI, detailing their purpose, inputs, outputs, and interactions with adjacent modules.

---

## 1. Backend Service Components

### 1.1 TranscriptionService (`transcription_service.py`)
- **Purpose**: Manages speech-to-text inference on consultation audio recordings locally using Faster-Whisper.
- **Inputs**:
  - `audio_path` (str / Path): Path to the validated audio file.
  - Optional `language` code (str): Target language hint (default: "en").
- **Outputs**:
  - `TranscriptionResult`: Dataclass containing `text` (str), `segments` (list of `TranscriptSegment` objects with `start`, `end`, `text`, `confidence`), `language` (str), and `duration` (float).
- **Interactions**:
  - Invoked by `routers/consultations.py` during `POST /api/consultations/{id}/transcribe` and by `main.py` in the legacy `POST /api/transcribe` flow.
  - Implements thread-safe singleton initialization with lazy model loading to minimize memory footprint on cold boot.
  - Delegates file validation (extension, MIME, size up to 50MB) to helper validation logic.

### 1.2 ContentValidator (`content_validator.py`)
- **Purpose**: Pre-NLP gatekeeper that inspects raw transcripts to ensure the recording contains genuine clinical dialogue before committing computation to medical entity extraction.
- **Inputs**:
  - `transcript_text` (str): Raw or edited consultation transcript text.
- **Outputs**:
  - `ValidationResult`: Contains `is_valid` (bool), `medical_term_density` (float), `detected_markers` (list of matching terms), and `rejection_reason` (optional str).
- **Interactions**:
  - Evaluates against two gating criteria: minimum medical keyword density threshold (e.g., symptoms, body parts, clinical actions) and absence of disqualifying patterns.
  - Prevents extraneous audio (music, casual chatter, non-medical meetings) from triggering erroneous clinical entity extraction or LLM hallucinations.

### 1.3 MedicalNLPService (`medical_nlp_service.py` & `entity_extraction.py`)
- **Purpose**: Extracts, categorizes, and asserts medical entities from clinical narrative transcripts.
- **Inputs**:
  - `transcript_text` (str): Clean transcript string.
- **Outputs**:
  - `List[ExtractedEntity]`: Typed list containing `text`, `category` (SYMPTOM, MEDICATION, CONDITION, PROCEDURE, TEST), `start_char`, `end_char`, `assertion` (PRESENT, ABSENT, CONDITIONAL, HYPOTHETICAL, ASSOCIATED_WITH_SOMEONE_ELSE), and `confidence`.
- **Interactions**:
  - Employs `scispaCy` model `en_ner_bc5cdr_md` for chemical and disease boundary identification.
  - Cross-references extracted spans against an 843-term clinical gazetteer (`medical_categories.py`) to assign granular categories.
  - Applies `medspaCy` ConText rule algorithms (`clinical_assertions.py`) to tag modifier assertions (negations such as "patient denies cough", temporality, and familial relations).
  - Supplies structured entity lists to database persistence and to `SoapGenerationService`.

### 1.4 SoapGenerationService (`soap_generation_service.py`)
- **Purpose**: Synthesizes a four-section SOAP clinical note (Subjective, Objective, Assessment, Plan) with clinical review flags.
- **Inputs**:
  - `transcript` (str): Full consultation transcript.
  - `entities` (list): Structured medical entities extracted by `MedicalNLPService`.
  - Optional `consultation_metadata` (dict): Date, clinician specialty, patient demographics.
- **Outputs**:
  - `SoapNoteResponse`: Validated Pydantic schema containing `subjective` (str), `objective` (str), `assessment` (str), `plan` (str), and `review_flags` (list of strings highlighting unconfirmed statements or missing details).
- **Interactions**:
  - Connects to Groq Cloud API using official `groq.Groq` client, targeting `llama-3.3-70b-versatile`.
  - Enforces strict generation constraints: vitals are never invented; undocumented findings are omitted.
  - Handles explicit exceptions: `MissingApiKeyError`, `GroqRateLimitError`, `GroqTimeoutError`, `GroqConnectionError`, and `InvalidResponseError`.
  - Provides deterministic, rule-based fallback generation (`_generate_fallback_soap`) if the API key is unconfigured or upstream calls fail.

### 1.5 EvidenceLinkingService (`evidence_linking_service.py`)
- **Purpose**: Links individual claims in the generated SOAP note to verbatim supporting sentences in the transcript to enable transparent clinician auditability.
- **Inputs**:
  - `soap_sections` (dict or object): SOAP text partitioned by section.
  - `transcript` (str): Original consultation transcript.
- **Outputs**:
  - `EvidenceMap`: Mappings of each SOAP statement to `quote` (transcript excerpt), `similarity_score` (0-100 float), `status` (`supported`, `unsupported`, `conflicting`, `ambiguous`), and `char_range` (`[start, end]`).
- **Interactions**:
  - Uses `rapidfuzz` string similarity with a support threshold (`MIN_SUPPORT_SIMILARITY = 50.0`).
  - Flags unsupported statements with `"Evidence not found — review required."` without fabricating transcript quotes.

### 1.6 Authentication & Authorization (`auth.py`)
- **Purpose**: Issues, verifies, and extracts user identity from JSON Web Tokens (JWT).
- **Inputs**:
  - User credentials (email, password) or incoming HTTP `Authorization: Bearer <token>` header.
- **Outputs**:
  - Signed HS256 JWT access tokens; authenticated `User` database models.
- **Interactions**:
  - Uses `passlib` with `bcrypt` for one-way password hashing and verification.
  - Protects private routes via FastAPI dependency `get_current_user`.
  - Warns in server logs when insecure default secret keys are detected.

### 1.7 Database & ORM Layer (`database.py` & `models.py`)
- **Purpose**: Manages relational schema definition, connection pools, and database transactions.
- **Models**:
  - `User`: Clinician account credentials, full name, role, created timestamp.
  - `Transcription`: Consultation session record, audio file path, transcript text, status (`uploaded`, `transcribing`, `transcript_ready`, `draft_generated`, `in_review`, `approved`, `failed`), review status, approval timestamp, approved_by_id.
  - `MedicalEntity`: Persisted clinical terms, character offsets, categories, assertions, and foreign key to parent transcription.
  - `SoapNote`: Sectioned SOAP text, review warnings, evidence mappings, and version tracking.

---

## 2. Frontend Interface Components

### 2.1 Router & Page Structure (`App.tsx`)
- **`LoginPage` (`pages/LoginPage.tsx`)**: Accepts clinician credentials, validates input formats, handles error toasts, and stores access tokens in local storage and Zustand auth store.
- **`DashboardPage` (`pages/DashboardPage.tsx`)**: Displays aggregate statistics (total consultations, pending drafts, approval rate), recent sessions, and direct action buttons for new encounters.
- **`NewConsultationPage` (`pages/NewConsultationPage.tsx`)**: Multi-functional interface supporting drag-and-drop audio file upload (.mp3, .wav, .m4a, .ogg, .webm up to 50MB) and live in-browser microphone capture with audio waveform visualization.
- **`ConsultationDetailsPage` (`pages/ConsultationDetailsPage.tsx`)**: Master consultation view tracking progress across pipeline stages with direct deep-links to transcript editing and SOAP review.
- **`TranscriptReviewPage` (`pages/TranscriptReviewPage.tsx`)**: Interactive transcript inspector. Allows line-by-line correction of automated speech recognition errors, word-level confidence reviews, and triggers re-extraction of medical entities.
- **`SoapReviewPage` (`pages/SoapReviewPage.tsx`)**: Clinician review hub. Features side-by-side SOAP text editing, review warnings banner, and interactive evidence highlighting that scrolls to the supporting transcript citation upon clicking a claim.
- **`ConsultationHistoryPage` (`pages/ConsultationHistoryPage.tsx`)**: Searchable, filterable table of past patient encounters with status badges and deletion actions.
- **`SettingsPage` (`pages/SettingsPage.tsx`)**: Configuration for clinician display preferences, theme toggling, and data management.

### 2.2 State Management Stores
- **`useAuthStore` (`stores/authStore.ts`)**: Manages current user state, access tokens, login/logout transitions, and authentication hydration on page reload.
- **`useConsultationStore` (`stores/consultationStore.ts`)**: Tracks active consultation metadata, upload progress, transcript segments, entity tags, SOAP draft sections, evidence citations, and saving/approval states.

---

## 3. Data Transfer Objects & Schemas (`schemas.py`)

- **`UserRegister` / `UserLogin` / `UserResponse`**: Secure payload validation ensuring email format and maximum password length boundaries (128 characters).
- **`ConsultationCreate` / `ConsultationResponse`**: Metadata exchange for consultation creation and retrieval.
- **`TranscriptUpdate`**: Schema for submitting manual corrections to consultation transcripts.
- **`SoapNoteCreate` / `SoapNoteUpdate` / `SoapNoteResponse`**: Structured container for SOAP sections and clinical flags.
- **`ApprovalRequest` / `ApprovalResponse`**: Schema enforcing explicit clinician approval actions and recording timestamps.
