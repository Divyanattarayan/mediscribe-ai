<!-- Generated: 2026-09-17 | Files scanned: 7 (models, schemas, 5 migrations) | Token estimate: ~600 -->

# Data

PostgreSQL 16, SQLAlchemy 2.0 ORM, Alembic-managed schema. Migrations are applied
by the start commands (`scripts/dev-backend.sh`, Dockerfile) **before** `main.py`
is imported — the app never creates tables.

## Tables

```
users
  id PK · email UNIQUE IDX · hashed_password · first_name · last_name
  specialty? · hospital? · license_no?
  note_style_preset            'balanced'  NOT NULL
  preferred_focus              'general'   NOT NULL
  include_bullets_in_plan      false       NOT NULL
  include_patient_friendly_language false  NOT NULL
  is_active · created_at

transcriptions
  id PK · user_id FK→users.id NOT NULL
  patient_id            PT-##### generated per row, not a real identifier
  filename              display-only, never a filesystem path
  transcription         TEXT
  medical_content_score FLOAT 0-100  term density from validate_medical_content
  asr_confidence        FLOAT NULL   mean per-word acoustic probability
  duration mm:ss · status 'complete' · created_at

medical_entities
  id PK · transcription_id FK NOT NULL
  text · label (CHEMICAL|DISEASE|SYMPTOM|TEST|PROCEDURE) · confidence · start · end
  assertions:  negated · temporality (current|historical|hypothetical)
               experiencer (patient|family) · uncertain · assertion_source
  ontology:    ontology_system (RXNORM|ICD10CM) · ontology_code
               ontology_display · ontology_requires_review

soap_notes
  id PK · transcription_id FK UNIQUE NOT NULL   (1:1)
  subjective · objective · assessment · plan
  source  e.g. "groq-llama-3.3-70b-versatile" | "rule-based-fallback"
  created_at
```

## Relationships

```
users 1──∞ transcriptions 1──∞ medical_entities
                          1──1 soap_notes
```
All children `cascade="all, delete-orphan"` — deleting a user or transcription
removes its entities and note. `DELETE /api/auth/me` relies on this.

## Two scores, deliberately distinct

| Column | Means |
|---|---|
| `medical_content_score` | term density of the **transcript**, computed before a note exists; gates non-clinical audio. Renamed in `0004` because the UI was presenting it as system confidence. |
| `asr_confidence` | the first genuine confidence: mean per-word probability from the acoustic model. NULL when the backend produced no word timestamps — absence, not zero. |

## Migration history — `backend/alembic/versions/`

```
20260504_0001_initial_schema         users, transcriptions, medical_entities, soap_notes
20260909_0002_entity_assertions      negated/temporality/experiencer/uncertain/source
20260909_0003_entity_ontology        ontology_system/code/display/requires_review
20260911_0004_rename_confidence_score  confidence_score → medical_content_score
20260911_0005_asr_confidence         + transcriptions.asr_confidence
```

## Schema governance

`.github/workflows/backend.yml` runs two gates on every push:
1. migrations apply to a clean database **and reverse**;
2. `python -m scripts.check_schema_drift` — models and migrations must agree.

## Non-relational stores

```
backend/uploads/          transient audio, deleted in the request's finally block
backend/dev-mediscribe.db local SQLite convenience DB (not the deployed store)
backend/.ontology_cache.json  RxNav / ICD-10 lookup cache
backend/eval/results/*.json   55 committed evaluation run reports
backend/eval/cases/golden.jsonl  local eval suite
```
