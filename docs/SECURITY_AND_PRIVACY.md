# MediScribe AI — Security, Privacy, and Clinical Limitations

> **NOTICE & DISCLAIMER**
> MediScribe AI is a research, educational, and developer demonstration prototype.
> - **NOT A MEDICAL DEVICE:** This application is not an FDA-cleared or CE-marked medical device and is **not intended or certified for real-world clinical use, diagnosis, or patient management**.
> - **NO COMPLIANCE ATTESTATION:** This prototype has not undergone formal HIPAA, GDPR, SOC 2, or HITRUST regulatory audits. **Do not deploy this software with real, unconsented patient data or Protected Health Information (PHI).**
> - **MANDATORY CLINICIAN OVERSIGHT:** All speech-to-text outputs, extracted entities, and SOAP notes are non-final AI drafts requiring review, verification, and manual sign-off by a licensed clinician.

---

## 1. Security Architecture & Threat Model

### 1.1 Secrets & Credential Management
- **Source Control Hygiene:** Sensitive environment variables (`.env`, `JWT_SECRET_KEY`, `GROQ_API_KEY`, database credentials) are explicitly ignored via [`.gitignore`](file:///c:/Users/divya/OneDrive/Documents/clinnote%20AI/.gitignore).
- **Backend Isolation:** Third-party LLM API keys (`GROQ_API_KEY`) reside exclusively in the backend runtime process and are never bundled, transmitted, or accessible to the browser.
- **Safe Health Probing:** The [`/api/health`](file:///c:/Users/divya/OneDrive/Documents/clinnote%20AI/backend/main.py#L100-L120) endpoint exposes only high-level status flags (e.g. `llm_configured: true`), and never prints secrets, tokens, or configuration strings.

### 1.2 Authentication & Session Management
- **Password Hashing:** Passwords are hashed using industry-standard `bcrypt` via PassLib (`passlib.context.CryptContext(schemes=["bcrypt"])`). Plaintext passwords are never persisted or logged.
- **Password Constraints:** Enforced server-side validation rejects passwords shorter than 8 characters or longer than 128 characters.
- **Token Verification:** Stateless JSON Web Tokens (JWT) using HMAC-SHA256 (`HS256`) identify authenticated users. Protected routes require standard `Authorization: Bearer <token>` headers.
- **No Custom Cryptography:** Standard, peer-reviewed libraries (`python-jose`, `passlib`, `hashlib`, `secrets`) are utilized exclusively.

### 1.3 Authorization & Multi-Tenant Isolation
- **Resource Ownership Scoping:** All consultation records, transcripts, entities, and generated SOAP notes in [`backend/routers/consultations.py`](file:///c:/Users/divya/OneDrive/Documents/clinnote%20AI/backend/routers/consultations.py) and [`backend/main.py`](file:///c:/Users/divya/OneDrive/Documents/clinnote%20AI/backend/main.py) enforce strict user ID matching (`models.Transcription.user_id == current_user.id`).
- **Cross-Account Access Protection:** Accessing or deleting records belonging to another clinician yields HTTP 404 (or 403 Forbidden).

### 1.4 Database Security & Query Parameterization
- **SQL Injection Prevention:** All database operations use the SQLAlchemy Object-Relational Mapper (ORM), ensuring all SQL queries are strictly parameterized. Raw string SQL execution is prohibited.
- **SQLite Foreign Key Enforcement:** In SQLite environments, a database connection listener automatically executes `PRAGMA foreign_keys = ON;` on every connection to enforce relational integrity and orphan cascades.

### 1.5 File Upload Validation & Path Traversal Mitigations
- **Strict Whitelist Validation:** Uploaded audio files are validated for permitted extensions (`.mp3`, `.wav`, `.m4a`, `.webm`, `.ogg`, `.flac`), matching audio MIME types, and non-empty byte streams.
- **Upload Size Ceiling:** Files exceeding 50 MB (`MAX_UPLOAD_BYTES = 50 * 1024 * 1024`) are rejected with HTTP 413.
- **Randomized Server-Side Identifiers:** Filenames from client inputs are treated as untrusted metadata. Storage paths are generated using cryptographic UUID4 values (`uuid.uuid4().hex + ext`), preventing path traversal (`../`) and filename collision attacks.
- **Safe Unlinking Safeguards:** The [`safe_delete_audio_file`](file:///c:/Users/divya/OneDrive/Documents/clinnote%20AI/backend/lib/utils.py#L32-L65) function verifies that any target path strictly resolves inside the designated `uploads/` parent directory before deleting.

---

## 2. Privacy & Data Handling Practices

### 2.1 Logging & Telemetry Safeguards
- **Zero Raw Transcript Logging:** Application loggers log structured metrics (audio length, transcript character count, entity counts) instead of raw conversational dialogue or patient symptom text.
- **No Password or Key Logging:** Request logs redact authentication secrets and password fields.

### 2.2 Audio Retention & Deletion Policy
Consultation audio recordings represent sensitive biometric data. The following deletion controls are implemented:
1. **Single Consultation Deletion:**
   - Calling `DELETE /api/consultations/{consultation_id}` (or `DELETE /api/history/{id}`) removes the consultation, its entities, its SOAP note, and automatically unlinks the audio file from the filesystem.
2. **Audio-Only Purging:**
   - Calling `DELETE /api/consultations/{consultation_id}/audio` removes the audio file from disk while preserving the transcribed text and approved SOAP notes for clinical auditing.
3. **Bulk History Deletion:**
   - Calling `DELETE /api/history` unlinks all audio files owned by the clinician and clears all records.
4. **Account Purge:**
   - Calling `DELETE /api/auth/me` deletes the clinician's user account and permanently cleans up all associated audio recordings and consultation drafts.

---

## 3. How to Clean Up Synthetic & Uploaded Demonstration Data

### 3.1 Through the Application Interface
- **Delete Single Consultation:** Open **Consultation History**, click the trash icon on the consultation card, and confirm deletion.
- **Delete All History:** On the **Consultation History** page, click **Clear All History** and confirm.
- **Delete Account:** In **Account Settings**, click **Delete My Account**.

### 3.2 Manual Cleanup via Terminal
To purge all uploaded audio files locally:
```bash
# In the repository root
rm -rf backend/uploads/consultations/*
rm -rf backend/uploads/*.wav backend/uploads/*.mp3
```

To purge the SQLite development database:
```bash
rm backend/mediscribe_dev.db
```

---

## 4. Known Security & Privacy Limitations

1. **Third-Party Model Invocations:** When using cloud LLM providers (e.g. Groq), transcripts and entity summaries are transmitted via TLS to external APIs for inference. In production or clinical settings, a Business Associate Agreement (BAA) and dedicated HIPAA-compliant enterprise endpoint are mandatory.
2. **Local Unencrypted File Storage:** Audio recordings and SQLite databases are stored in plaintext on the server filesystem. Production systems require disk-level encryption (LUKS / BitLocker) and encrypted object storage (e.g., S3 with SSE-KMS).
3. **Session Revocation & Refresh Tokens:** Access tokens are stateless JWTs with a 7-day expiration. Blacklisting revoked tokens before expiration is not implemented; token revocation requires changing `JWT_SECRET_KEY` (which invalidates all tokens).
4. **Rate Limiting:** IP/User-level rate limiting is not implemented at the application tier and should be managed via an API gateway or reverse proxy (e.g., NGINX `limit_req_zone`, Cloudflare).
5. **Multi-Factor Authentication (MFA):** Clinician accounts use single-factor password authentication. MFA/OAuth2/SAML SSO must be added before considering production use.
