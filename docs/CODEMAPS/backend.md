<!-- Generated: 2026-09-17 | Files scanned: 62 py (12,890 LOC) | Token estimate: ~950 -->

# Backend

FastAPI monolith. No router modules — every route is declared in `main.py`.
Auth is JWT bearer via the `get_current_user` dependency.

## Routes → handler → collaborators

```
GET    /                      root banner
GET    /health                liveness (docker healthcheck)

POST   /api/auth/register  →  hash_password, create_access_token        auth.py
POST   /api/auth/login     →  verify_password, create_access_token      auth.py
GET    /api/auth/me        →  get_current_user                          auth.py
PUT    /api/auth/me        →  style-profile fields                      documentation_style.py
DELETE /api/auth/me        →  cascade delete user + all data            models.py

GET    /api/history                     list own transcriptions (selectinload)
GET    /api/history/{transcription_id}  ownership-checked detail
DELETE /api/history/{transcription_id}  ownership-checked delete
DELETE /api/history                     delete all own history

POST   /api/transcribe     →  7-stage pipeline (see architecture.md)
```

All `/api/*` except register/login require `Depends(get_current_user)`.
History routes filter by `user_id` — ownership is enforced, not assumed
(`tests/test_history_ownership.py`).

## Middleware / cross-cutting

```
CORSMiddleware            main.py:78   origins from CORS_ORIGINS, localhost defaults
configure_console()       console.py   forces UTF-8 before any import that prints
get_db()                  database.py  per-request session, closed in finally
reset_usage/usage_snapshot groq_client  per-request token accounting → response
MAX_UPLOAD_BYTES 50MB     main.py:46   mirrors nginx client_max_body_size
MIN_AUDIO_DURATION 45s    main.py:49   hint-based pre-flight + authoritative check
```

## Pipeline modules

| File | LOC | Role |
|---|---|---|
| `soap_generator.py` | 1430 | LLM note generation + rule-based fallback, section repair, style enforcement |
| `medical_categories.py` | 568 | keyword vocabularies: SYMPTOMS/MEDICATIONS/CONDITIONS/PROCEDURES/… |
| `main.py` | 558 | app, routes, the 7-stage orchestration |
| `clinical_facts.py` | 525 | fact table — one row per claim + supporting transcript span |
| `clinical_extraction.py` | 476 | LLM → structured clinical IR before generation |
| `groq_client.py` | 418 | single model access point: providers, retry, pacing, usage |
| `entity_extraction.py` | 399 | spaCy `en_ner_bc5cdr_md` NER + dictionary second pass |
| `content_validator.py` | 390 | term-density gate — rejects non-clinical audio |
| `ontology.py` | 347 | RxNorm (resolution) / ICD-10-CM (ranked suggestion, review-flagged) |
| `transcription.py` | 329 | faster-whisper; every decoding knob is an env var |
| `clinical_assertions.py` | 296 | medspaCy ConText: negated / historical / family / uncertain |
| `spell_correction.py` | 270 | off by default — measured to invert clinical meaning |
| `claim_verification.py` | 207 | per-claim entailment vs transcript (replaced lexical proxy) |
| `transcript_facts.py` | 118 | shared DOB/clinician parsing + fallback encounter classifier |
| `schemas.py` / `models.py` | 120/111 | Pydantic contracts / SQLAlchemy ORM |
| `decoder_vocabulary.py` | 83 | per-user ASR bias from their own prior encounters |
| `documentation_style.py` | 67 | preset/focus/encounter-type validation + resolution |
| `auth.py` / `database.py` / `console.py` | 99/57/~30 | JWT, session factory, UTF-8 streams |
| `lib/utils.py` | — | `generate_patient_id`, `format_duration_mmss` |

## Model access — `groq_client.py`

```
PROVIDERS = { groq | gemini | cerebras }
resolve_role(role) -> (provider, model)      roles: pipeline, judge
GROQ_MODEL default openai/gpt-oss-120b
EVAL_JUDGE_PROVIDER / EVAL_JUDGE_MODEL       judge runs off-provider by design
chat_json(...)  → _call_with_retry → _pace → _record_usage
```
Hardening exists because of real failures: a decommissioned hardcoded model made
every call 404 and silently served the fallback note; reasoning models spend
`max_tokens` before emitting output, hence generous caps + `json_object`.

## Evaluation harness — `backend/eval/`

```
python -m eval run --suite primock57 --stages asr,note,judge --limit 10
python -m eval compare --baseline results/<a>.json --current results/<b>.json
python -m eval list
```

```
__main__.py    CLI            runner.py     run_suite / compare_reports / save_report
datasets.py    SUITES: local, primock57, primock57_notes, aci_bench, mts_dialog
audio_source.py  streams PriMock57 audio per file, discards after
textgrid.py / primock_checklists.py / golden_from_checklists.py  reference data
schema.py      EvalCase
metrics/asr.py        word_error_rate, medical_term_error_rate
metrics/entities.py   entity_scores, assertion_scores, missed_and_spurious
metrics/coverage.py   coverage_scores, judged_coverage_scores, ceiling_scores
metrics/grounding.py  grounding_scores / grounding_details
metrics/judge.py      rubric_score, claim_entailment
cases/golden.jsonl    local suite;  results/*.json  55 committed run reports
```
Every committed result was produced by `GROQ_MODEL` on Groq — changing the
pipeline model invalidates the before/after comparisons in
`context/MODEL_ROADMAP.md`.

## Tests & operational scripts

```
backend/tests/   20 files, conftest.py fixtures, one audio fixture
scripts/asr_sweep.py           sweep ASR env-var configurations
scripts/check_model_access.py  what each provider actually serves
scripts/check_schema_drift.py  models vs migrations (CI gate)
```
