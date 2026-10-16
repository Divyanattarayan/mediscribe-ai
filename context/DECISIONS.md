# Decisions

This file records decisions that appear to be active and intentionally locked in based on the current codebase and project memory.

## Locked Decisions

### Product Direction

- The project is being built as a portfolio-quality, production-leaning medical transcription platform rather than a narrow model demo.
- The target outcome is a deployed, end-to-end system with backend, frontend, auth, database, and documentation.

### Backend

- FastAPI is the backend framework.
- PostgreSQL is the primary database.
- SQLAlchemy ORM is the persistence layer.
- JWT bearer auth is the authentication model.
- Passwords are hashed with bcrypt through `passlib`.

### AI / NLP Pipeline

- `faster-whisper` is the primary ASR backend.
- `openai-whisper` is no longer the intended installed backend.
- Transcript normalization is part of the live pipeline.
- Medical entity extraction uses `scispacy` plus a custom dictionary pass.
- SOAP notes are generated from both transcript text and structured clinical extraction.

### Frontend

- React + TypeScript + Vite is the frontend stack.
- Zustand is the client state layer.
- Axios interceptors handle bearer-token attachment and expired-session behavior.
- Tailwind CSS v4 is the active styling approach.

### Design language (locked 2026-08-30)

Full specification in `context/DESIGN_DIRECTION.md`. Headline decisions:

- **Colour is reserved for meaning.** No brand hue. Warm stone neutrals (`#FAFAF9` / `#1C1917`)
  replace the cool slate ramp; primary buttons are ink. One rationed accent — deep teal
  `#14524F` light / `#5EAFA6` dark — for focus rings, active nav, links and the logo only.
- **Typography is semantic by content type.** JetBrains Mono = raw machine output (transcript,
  IDs, numerals); Newsreader = the finished clinical document (SOAP note, headings);
  Instrument Sans = application chrome. Inter is deliberately not used.
- **Tokens live in `@theme`** using Tailwind v4 namespaces, with `.dark` redefining only the
  tokens that change. This replaces the current dual dark-mode system and allows the
  `html.dark main … !important` override block to be deleted.
- **Structure:** the 220px sidebar is removed in favour of a horizontal top nav; the results
  view becomes a three-column session view (transcript │ SOAP │ context).
- **Motion:** one curve `cubic-bezier(0.22, 1, 0.36, 1)`, four durations (150/300/600/900ms),
  all behind `prefers-reduced-motion`.
- **Honesty rules are binding:** no invented metrics, no simulated progress, no fabricated
  testimonials, no non-functional controls. See `DESIGN_DIRECTION.md` §7.

### Development Workflow

- Local hybrid development is the preferred fast iteration path:
- PostgreSQL in Docker
- Backend locally with reload
- Frontend locally with Vite
- Production-style Docker files remain in the repo for full-stack verification later.

### Persistence Model

- Users, transcriptions, medical entities, and SOAP notes are stored in separate relational tables.
- Transcription history is user-scoped and protected by auth.
- Relationship loading for history uses eager loading to avoid lazy-load serialization issues.

## Decisions That Need To Stay Visible

- Model-quality work is tracked in `context/MODEL_ROADMAP.md`, separately from the product phases in `PLAN.md`.
- Condition-specific post-generation rules are not allowed in the pipeline (decided 2026-09-09). The pericarditis and diabetes rule layers in `soap_generator.py`, the hardcoded bundles in `clinical_extraction.py`, and the demo-recording phrase map in `spell_correction.py` were removed because they were fitted to two recordings and degraded every other encounter. Groundedness is detected and routed to regeneration; it is never patched with regex deletion.
- No model-quality claim ships without a number from `python -m eval` behind it.
- Evaluation datasets live outside the repo and outside any cloud-synced folder, at `MEDISCRIBE_EVAL_DATA` (2026-09-09). The project sits under OneDrive, so the default `eval/data/` would sync every byte of a benchmark to the user's cloud storage.
- Benchmark audio is streamed per case and deleted, never stored (2026-09-09). Only transcripts and reference notes are kept locally; they are a few megabytes and are what the metrics compare against.
- Ontology linking uses the NLM's public REST APIs (RxNorm, ICD-10-CM, the SNOMED-backed conditions endpoint) rather than scispaCy's `UMLSEntityLinker` (2026-09-09). The linker needs a ~1 GB local knowledge base; the APIs need no key, no licence and no disk, at the cost of network latency that an on-disk cache absorbs.
- ICD-10 codes are suggestions, never decisions. Mapping a bare diagnosis to a code is a curated-crosswalk problem that search ranking does not solve, so condition results carry `requires_review` and a shortlist, and nothing consumes the code automatically.
- `GROQ_MODEL` is env-configurable and currently `openai/gpt-oss-120b`. The previous hardcoded `llama-3.3-70b-versatile` had been decommissioned by Groq, so the LLM path had been failing to the rule-based generator on every request. Verify a candidate model with an eval run before switching.

- Alembic is the sole source of truth for the database schema. The `create_all()` startup fallback and the ad-hoc `_ensure_user_style_columns()` ALTER-TABLE shim were removed from `backend/main.py` on 2026-05-06 once the baseline migration was verified against PostgreSQL.
- Schema changes must be authored as Alembic revisions. ORM model changes that are not paired with a migration will not reach the database.
- Minimum audio duration is enforced at 45 seconds in both the backend flow and frontend UX.

## Decisions Still Open

- Formal testing strategy and CI expectations beyond the `scripts/smoke-test.sh` end-to-end check
- Future privacy / compliance framing for demo vs production positioning
- Migration strategy for production schema rollouts beyond the baseline (no decisions needed until a second migration is authored)

## Resolved Decisions

- Deployment runbook for Railway backend/Postgres and Vercel frontend is documented in `docs/deployment.md` (2026-05-06). Execution belongs to a later milestone.
