# Spec: upload-safety

> Auto-extracted by spec-miner. Last mined: 2026-09-17.
> Source: backend/main.py (POST /api/transcribe upload handling), nginx.conf
> Last verified: 2026-09-17 (commit 89807ef)

Scope: what the transcribe endpoint accepts before it spends any compute — size
cap, duration floor, extension allowlist — and the filesystem contract for the
audio it writes: random name, no client-controlled path component, always
deleted.

---

### Requirement: Oversized uploads are rejected, twice
<!-- id: main.transcribe_audio_endpoint -->
<!-- entities: Transcription -->
<!-- enforced: main.transcribe_audio_endpoint(), main.MAX_UPLOAD_BYTES -->

The endpoint SHALL reject with 413 when the declared `Content-Length` exceeds
`MAX_UPLOAD_BYTES` (50 MB) plus a 1 MB multipart-envelope margin, before reading
the body into memory, and SHALL reject again with 413 on the exact byte length
once the body is in hand. An unparseable `Content-Length` SHALL be ignored
rather than fatal. The cap mirrors `client_max_body_size` in nginx.conf so the
limit is the same whether or not traffic passes the proxy.

#### Scenario: an oversize upload
<!-- test: tests/test_upload_validation.py::test_oversize_upload_is_rejected -->
- **WHEN** the file exceeds 50 MB
- **THEN** 413 is returned with "Audio file exceeds the 50 MB limit."

#### Scenario: a malformed Content-Length header
- **WHEN** `Content-Length` is not an integer
- **THEN** the pre-flight check is skipped and the exact check still applies

---

### Requirement: The extension allowlist gates the file type
<!-- id: main.transcribe_audio_endpoint -->
<!-- entities: Transcription -->
<!-- enforced: main.transcribe_audio_endpoint(), main.ALLOWED_AUDIO_EXTENSIONS -->

Only `.mp3`, `.wav`, `.m4a`, `.webm`, `.ogg` and `.flac` SHALL be accepted,
matched case-insensitively on the extension of the client-supplied filename. A
missing filename defaults to `"recording"`, which has no extension and is
therefore rejected.

#### Scenario: an unsupported type
<!-- test: tests/test_upload_validation.py::test_unsupported_extension_is_rejected -->
- **WHEN** the filename ends in an extension outside the allowlist
- **THEN** 400 is returned naming the extension and the allowed list

---

### Requirement: Audio shorter than the minimum is refused without generating a note
<!-- id: main.transcribe_audio_endpoint -->
<!-- entities: Transcription -->
<!-- enforced: main.transcribe_audio_endpoint(), main.MINIMUM_AUDIO_DURATION_SECONDS -->

Audio under `MINIMUM_AUDIO_DURATION_SECONDS` (45) cannot produce a usable
clinical note. The endpoint SHALL check the client's
`X-Audio-Duration-Seconds` header as a cheap pre-flight that only saves work,
and SHALL check the decoded audio length after transcription as the
authoritative guard. Both return `success=False` with a `validation` block
naming `audio_duration_seconds` and `minimum_audio_duration_seconds`, and
neither persists anything.

#### Scenario: the client declares a short recording
- **WHEN** the header is below 45 seconds
- **THEN** the too-short response is returned before any ASR work

#### Scenario: the client's header is wrong
<!-- test: tests/test_transcribe_flow.py::test_short_real_audio_is_rejected_even_if_header_lies -->
- **WHEN** the header claims a long recording but the decoded audio is under 45
  seconds
- **THEN** the request is still rejected, because the decoded duration is
  authoritative

---

### Requirement: Uploads are stored under a server-generated random name
<!-- id: main.transcribe_audio_endpoint -->
<!-- entities: Transcription -->
<!-- enforced: main.transcribe_audio_endpoint(), main.UPLOAD_DIR -->

The stored filename SHALL be `f"{uuid4().hex}{validated_extension}"` inside
`UPLOAD_DIR`. The client filename SHALL be used only for the allowlist check and
as display-only metadata persisted to `transcriptions.filename` and echoed in
the response.

#### Scenario: a crafted traversal filename
<!-- test: tests/test_upload_validation.py::test_path_traversal_filename_cannot_escape_upload_dir -->
- **WHEN** the client sends a filename like `../../main.py`
- **THEN** nothing is written outside the upload directory — the name never
  becomes a path component

#### Scenario: two users upload the same name
- **WHEN** both send "recording.mp3"
- **THEN** the stored files do not collide, because each gets its own UUID

---

### Requirement: Authentication is required before any upload work
<!-- id: main.transcribe_audio_endpoint -->
<!-- entities: User, Transcription -->
<!-- enforced: main.transcribe_audio_endpoint() -->
<!-- depends_on: A bearer token identifies the caller on every protected route -->

`POST /api/transcribe` SHALL declare `Depends(get_current_user)`, so an
unauthenticated request never reaches the size, extension or duration checks.

#### Scenario: no token
<!-- test: tests/test_upload_validation.py::test_transcribe_requires_authentication -->
- **WHEN** the request carries no bearer token
- **THEN** it is rejected as unauthenticated

---

### Requirement: Unhandled pipeline errors return a generic 500
<!-- id: main.transcribe_audio_endpoint -->
<!-- entities: Transcription -->
<!-- enforced: main.transcribe_audio_endpoint() -->

`HTTPException`s raised deliberately SHALL propagate unchanged. Any other
exception SHALL be logged with a traceback and converted to 500 "Transcription
failed. Please try again." — internal detail is not leaked to the client.

#### Scenario: an unexpected failure mid-pipeline
- **WHEN** any stage raises a non-HTTP exception
- **THEN** the client receives 500 with the generic message and the server log
  carries the traceback

---

### Invariant: The client filename is display-only metadata, never a path component
<!-- entities: Transcription -->
<!-- enforced: main.transcribe_audio_endpoint() -->
<!-- verified_by: tests/test_upload_validation.py::test_path_traversal_filename_cannot_escape_upload_dir -->

`original_filename` SHALL only ever be read for its extension, persisted to
`transcriptions.filename`, and echoed in the response. It SHALL NOT be joined
into a filesystem path.

> Last verified: 2026-09-17 (commit 89807ef)

---

### Invariant: Uploaded audio is always deleted
<!-- entities: Transcription -->
<!-- enforced: main.transcribe_audio_endpoint() -->
<!-- verified_by: tests/test_upload_validation.py::test_upload_dir_is_empty_after_a_request -->

The endpoint's `finally` block SHALL remove the stored file if it exists — on
success, on rejection, on early return and on exception alike. Clinical audio
does not persist beyond the request.

> Last verified: 2026-09-17 (commit 89807ef)

---

### Invariant: There is no endpoint that serves uploaded audio back
<!-- entities: Transcription -->
<!-- enforced: main (route table) -->
<!-- verified_by: tests/test_upload_validation.py::test_removed_download_endpoint_is_gone -->

No route exposes files from `UPLOAD_DIR`. A download endpoint that once existed
has been removed and a test asserts it stays removed.

> Last verified: 2026-09-17 (commit 89807ef)

---

### Invariant: patient_id is a generated label, not a real identifier
<!-- entities: Transcription -->
<!-- enforced: lib.utils.generate_patient_id(), models.Transcription.patient_id -->

`patient_id` SHALL be a `PT-#####` value generated per row. It identifies
nothing outside this database and carries no linkage to a real patient record.

> Last verified: 2026-09-17 (commit 89807ef)

---

<!-- uncertainty: The 50 MB cap is enforced after the full body has been read into memory (`content = await file.read()`), so the second check cannot prevent the memory cost it guards against — only the Content-Length pre-flight and nginx can. Flagged, not fixed. -->
<!-- uncertainty: generate_patient_id is in backend/lib/utils.py, which per the memory index has a frontend counterpart that was lost to gitignore. The backend file exists and is imported; no test anchors it. -->
