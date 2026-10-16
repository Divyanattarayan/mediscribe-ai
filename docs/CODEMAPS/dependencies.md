<!-- Generated: 2026-09-17 | Files scanned: requirements×2, package.json, compose, .env.example | Token estimate: ~700 -->

# Dependencies

## External services

| Service | Used by | Auth | Failure mode |
|---|---|---|---|
| Groq | `groq_client.py` — pipeline default (`openai/gpt-oss-120b`) | `GROQ_API_KEY` | SOAP falls back to rule-based generation; still returns a note |
| Gemini | eval judge (`gemini-3.5-flash-lite`) | `GEMINI_API_KEY` | judge stage unavailable; other eval stages unaffected |
| Cerebras | alternative provider | `CEREBRAS_API_KEY` | — |
| RxNav / RxNorm (NLM) | `ontology.py` medications | none | entity keeps no code; cached in `.ontology_cache.json` |
| NLM Clinical Tables (ICD-10-CM) | `ontology.py` conditions | none | same |
| PriMock57 audio | `eval/audio_source.py` | none | eval only, streamed per file |

No local UMLS knowledge base — the NLM REST services replace scispaCy's ~1 GB
`UMLSEntityLinker` download.

**Judge is deliberately off-provider**: it stops evaluation competing with the
pipeline for one 200k-token/day quota and stops the pipeline grading itself.
Pin the judge model (no `-latest`, no `-preview`) or scores stop being comparable.

## Backend — `backend/requirements.txt`

```
web        fastapi 0.104.1 · uvicorn 0.24.0 · python-multipart · websockets 12
ASR        faster-whisper                (WHISPER_MODEL=small.en, int8, beam 3)
NLP        spacy · scispacy · en_ner_bc5cdr_md 0.5.4 (pinned tarball URL)
           medspacy >=1.3,<2             ConText; held below spacy 3.8 to match the model
fuzzy      rapidfuzz 3.6.1
LLM        groq >=0.9 · openai >=1.0     (openai SDK also fronts Gemini/Cerebras)
db         sqlalchemy 2.0.23 · alembic 1.13.1 · psycopg2-binary 2.9.9
auth       python-jose[cryptography] · passlib[bcrypt] · bcrypt 4.0.1 · pydantic[email]
test       pytest >=8 · httpx >=0.24,<0.28
```
`requirements-ci.txt` is the slim CI set — CI runs pytest without the ASR/NLP
model weights.

## Frontend — `frontend/package.json`

```
runtime  react 19.2 · react-dom · axios 1.13 · zustand 5 · lucide-react
         sonner (toasts) · clsx · tailwind-merge · class-variance-authority
build    vite 7.3 · @vitejs/plugin-react · typescript 5.8 · tailwindcss 4.2
         @tailwindcss/vite · postcss · autoprefixer · tw-animate-css · shadcn 3.8
lint     eslint 9 flat config · typescript-eslint · react-hooks · react-refresh
```

## Shared internal libraries

```
backend/lib/utils.py        generate_patient_id, format_duration_mmss
backend/transcript_facts.py DOB/clinician parsing shared by soap_generator + clinical_extraction
backend/medical_categories.py  vocabularies shared by entity_extraction + content_validator
frontend/src/lib/utils.ts   cn() + formatters
frontend/src/components/ui/ Button, Card, Badge, Field, Modal
```

## Infrastructure

```
docker-compose.yml   backend (:8000, healthcheck /health) · frontend nginx (:80)
                     db postgres:16-alpine (:5432) · volumes whisper-cache, postgres-data
Dockerfile           backend, pre-downloads Whisper weights into the image
Dockerfile.frontend  vite build → nginx
nginx.conf           serves dist, proxies /api/, client_max_body_size mirrors 50MB cap
.github/workflows/backend.yml   pytest · migration up+down · schema-drift check
scripts/             dev-backend.sh · dev-frontend.sh · dev-db.sh · smoke-test.sh
```

## Environment variables — `.env.example`

```
required  DATABASE_URL · JWT_SECRET_KEY · GROQ_API_KEY
optional  CORS_ORIGINS · LOG_LEVEL
ASR       WHISPER_BACKEND · WHISPER_MODEL · WHISPER_COMPUTE_TYPE · WHISPER_BEAM_SIZE
models    LLM_PROVIDER · GROQ_MODEL · GROQ_REASONING_EFFORT
judge     EVAL_JUDGE_PROVIDER · EVAL_JUDGE_MODEL · GEMINI_API_KEY · CEREBRAS_API_KEY
```
Every ASR variable is a hypothesis the eval harness can test; the defaults are
the ones that measurably improved `medical_term_recall`.

⚠ `.env` exists in the working tree with live values. Rotating `JWT_SECRET_KEY`
invalidates every issued session token.
