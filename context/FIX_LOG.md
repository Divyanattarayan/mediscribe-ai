# Fix Log

This file captures important fixes and stability changes already reflected in the current codebase.

## Confirmed Fixes / Improvements

### Backend / Data

- Added eager loading with `selectinload` for history endpoints to avoid lazy-load failures during response serialization.
- Kept startup table creation as a safe fallback so first boot does not fail before real migrations exist.
- User-scoped access checks are enforced for history detail and delete routes.

### Auth

- Login returns the same failure shape for missing-user and wrong-password cases to reduce email enumeration risk.
- Session restore is handled through token storage plus `/api/auth/me`.

### Transcription Pipeline

- Switched primary ASR to `faster-whisper`.
- Added transcript normalization / medical spelling correction to the live pipeline.
- Added early return for recordings below the minimum audio duration threshold.
- Validation failures now stop the pipeline cleanly before entity extraction and SOAP generation.

### Entity / SOAP Quality

- Dictionary fallback entity scanning was expanded so categorization is more complete.
- Clinical extraction was added to support better SOAP generation quality.

### Frontend

- Axios timeout was increased to support longer transcription jobs.
- API base URL handling was improved for empty `VITE_API_URL`.
- Token writing responsibilities were narrowed so the store no longer writes tokens directly.
- Session restore behavior in `App.tsx` was adjusted to avoid cancelling its own history fetch.
- Upload flow cleanup improved blob URL lifecycle handling.
- Frontend now passes `X-Audio-Duration-Seconds` so the backend can short-circuit very short uploads.

### Infra / Dev Workflow

- Docker dependency wiring was corrected so frontend waits on backend and backend waits on healthy database.
- Nginx proxy timeout was increased for long-running transcription requests.
- Hybrid local-dev scripts were added to avoid unnecessary container rebuilds during day-to-day work.

### Phase 1 closure (2026-05-06)

- Removed `models.Base.metadata.create_all(bind=engine)` and `_ensure_user_style_columns()` from `backend/main.py`. Alembic is now the sole source of truth.
- Added `backend/tests/fixtures/test11-yt_chest_pain.mp3` plus a fixtures README so the transcription smoke is repeatable.
- Added `scripts/smoke-test.sh` to exercise register → login → /me → transcribe (real audio) → history list → history detail → delete one → delete account → confirm 401 in a single command.
- Added `docs/deployment.md` with the Railway + Vercel runbook, env var matrix, and CORS handshake steps.

### Security & correctness hardening (2026-08-30)

- **Path traversal / collision:** `/api/transcribe` now writes uploads under a generated UUID name; `file.filename` is display-only metadata and never used to build a filesystem path. Temp audio is removed in a `finally` block.
- **Upload size:** `/api/transcribe` rejects bodies over 50 MB (matches `nginx.conf`) with 413, checked before and after reading.
- **Error leakage:** the transcribe 500 handler logs the exception server-side and returns a generic message instead of `str(e)`.
- **Removed `POST /api/download`** — unauthenticated, header-injectable, and unused (the frontend builds download blobs client-side).
- **Password policy** is now enforced server-side (`RegisterRequest.password`, min 8). Frontend check raised to match.
- **Logging:** `backend/main.py` uses the stdlib `logging` module; logs `user_id` not email, counts not transcript text (previews are `DEBUG` only). `transcription.py` no longer prints transcript excerpts.
- **Registration race:** duplicate email now returns 409 via `IntegrityError` handling instead of an unhandled 500.
- **SOAP provenance:** `soap_generator.GROQ_MODEL` is the single source of truth; the persisted `source` field previously mislabelled every note as `llama-3.1`.
- **Real audio duration:** `transcribe_audio_realtime` returns `(text, duration_seconds)` from the ASR backend. The 45-second minimum is enforced against that value (the `X-Audio-Duration-Seconds` header is now only a pre-flight hint). `estimate_duration()` (a file-size guess) was removed.
- **`generate_patient_id()`** uses `secrets` with an 8-digit suffix to make collisions negligible.
- **Shared parsing:** `backend/transcript_facts.py` owns date-of-birth and clinician-intro parsing, previously duplicated (and drifting) across `soap_generator` and `clinical_extraction`.
- **Dead code:** `_regenerate_weak_sections` had two always-true guards that meant the Subjective section was never regenerated regardless of scored issues; it now only skips the "not enough information" placeholder case.
- Dropped the legacy `OPENAI_API_KEY` fallback in the Groq clients.

### Backend test suite (2026-08-30)

- Added a fast `pytest` suite in `backend/tests/` (in-memory SQLite, ML models stubbed, runs in seconds): auth, per-user history isolation, upload guards (including the traversal case), content validation, style normalisation, and the shared transcript parser. `pytest` / `httpx` added to `requirements.txt`.

### UI redesign — token layer, shell and screens (2026-09-09)

Implements `context/DESIGN_DIRECTION.md`.

- **The token layer that never existed.** `frontend/src/index.css` now defines `--font-sans`,
  `--font-serif`, `--font-head` and `--font-mono` in `@theme`. These were referenced across ~10
  components and never declared, so Sora and IBM Plex Mono had never rendered a single glyph —
  the app had been running in the OS system font stack the whole time. Fonts are now
  Instrument Sans (chrome), Newsreader (the clinical document), JetBrains Mono (machine output).
- **Dark mode is now token-driven.** `.dark` redefines only the `--color-*` variables that
  change; utilities resolve through `var()`, so components no longer branch on theme at all.
  **52 `dark ? … : …` ternaries were removed** and the `html.dark main … !important` override
  block in `index.css` is gone. That ends the four competing dark-mode conventions.
- **Shared primitives** in `frontend/src/components/ui/` — `Button`, `Card`, `Badge`, `Field`,
  `Modal` — replacing the card shell re-implemented 7x, the primary button 9x, the modal 3x and
  the form field 3x. `Sidebar.tsx`, `TopBar.tsx`, `ResultsPanel.tsx`, `TranscriptionCard.tsx`,
  `EntitiesCard.tsx`, `SOAPNoteCard.tsx` and `StatsBar.tsx` were deleted.
- **Shell:** the 220px sidebar is replaced by `TopNav.tsx`. Nav items are real buttons, so they
  are keyboard reachable for the first time. `App.tsx` shows a skeleton during session restore
  instead of returning `null` to a blank screen.
- **Session view (new):** `SessionView.tsx` composes three columns — transcript, SOAP note,
  context. `TranscriptCard` highlights entities inline using the `start`/`end` character
  offsets the backend has always persisted and the UI had never used; this is the substance of
  PLAN.md Phase 4, delivered as a layout change.
- **Quality report surfaced.** `ContextCard` renders `quality_report.section_issues`, computed
  on every request and previously discarded, with the machine codes phrased for a reader.
- **Honesty fixes.** `startFakeProgress()` and its six simulated stage messages and invented
  countdown are replaced by an honest indeterminate state with a truthful elapsed timer. The
  fabricated login testimonial and the "8→3 min / 700+ / 87%" statistics are removed, as is the
  entirely static Settings "API" tab, the non-functional notifications save, the dead Google SSO
  and password-reset buttons, and the misleading "Save to Record" (which only ever downloaded a
  `.txt`). The history Status column now reads `entry.status` instead of a hardcoded "Complete".
- **Motion:** one curve (`cubic-bezier(0.22, 1, 0.36, 1)`) and four durations. The SOAP note
  reveals line by line from behind a mask; entity chips stagger in. All of it collapses under
  `prefers-reduced-motion`.
- Every colour pair in the new palette was contrast-measured. Two of the first-pass values
  failed and were corrected: `#A8A29E` for tertiary text (2.41:1) and the dark status tints,
  which were invisible as fills against the surface.

### SOAP fallback rendered as a Python dict (2026-09-09)

Found while reviewing the new session view, which sets the note in a reading serif and made
this impossible to miss.

`_fallback_assessment` and `_fallback_plan` build sections as dicts. `_normalize_soap_sections`
passed dicts straight through, and `_apply_clinical_consistency_rules` then coerced them with
`str()` — so whenever Groq was unavailable and the rule-based fallback ran, the note was
persisted and displayed as a raw Python repr, e.g.
`{'primary_diagnosis': 'heart attack', 'condition_count': 2}`.

`_flatten_section()` now renders dicts, lists and scalars as prose inside
`_normalize_soap_sections`, before any rule touches a section. Covered by
`backend/tests/test_soap_sections.py`. Records written before this fix still hold the old
string; only new transcriptions are corrected.

## Still Open

- Deployment execution against Railway + Vercel remains a later milestone.
- `frontend/src/lib/utils.ts` is missing from the repo — it was caught by an over-broad `.gitignore` `lib/` rule (now fixed) and needs to be reconstructed before the frontend can build from a clean checkout.
- A full logging migration of the remaining pipeline modules (`entity_extraction`, `soap_generator`, `spell_correction`) is a follow-up; the PHI-carrying paths (email, transcript text) are already covered.
- `project_memory.md` is a Week-14-era record; `context/` is the canonical source.
