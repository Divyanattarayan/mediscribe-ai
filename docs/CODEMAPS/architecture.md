<!-- Generated: 2026-09-17 | Files scanned: 142 | Token estimate: ~750 -->

# Architecture

Single-repo, two-tier clinical documentation app. React SPA → FastAPI monolith →
Postgres. Plus an offline evaluation harness (`backend/eval/`) that is a
first-class subsystem, not a test helper.

## Topology

```
browser
  │  axios + JWT (Bearer)
  ▼
nginx (docker only) ──/api/──▶ FastAPI  backend/main.py:1   :8000
  │ static                        │
  ▼                               ├─ faster-whisper (local ASR, small.en)
frontend/dist (Vite)              ├─ spaCy en_ner_bc5cdr_md + medspaCy ConText
                                  ├─ RxNav / NLM Clinical Tables (HTTP, no key)
                                  ├─ Groq | Gemini | Cerebras  (LLM, per role)
                                  └─ Postgres 16 (SQLAlchemy + Alembic)
```

## Request pipeline — `POST /api/transcribe`

Every ML stage is blocking CPU work dispatched via `run_in_threadpool`.

```
audio upload (≤50MB, ≥45s, ext allowlist)
 1  transcribe_audio           transcription.py        biased by decoder_vocabulary
 1b correct_medical_spelling   spell_correction.py     DISABLED by default (measured harmful)
 2  validate_medical_content   content_validator.py    gate → early return if non-clinical
 3  extract_medical_entities   entity_extraction.py    NER + dict pass
      └ annotate_assertions    clinical_assertions.py  negation/temporality/experiencer/uncertainty
      └ link_entities          ontology.py             RxNorm / ICD-10-CM codes
 4  extract_clinical_repr.     clinical_extraction.py  LLM → structured IR
 5  build_fact_table           clinical_facts.py       every claim + supporting transcript span
 6  generate_soap_note         soap_generator.py       LLM primary, rule-based fallback
      └ claim_verification.py                          per-claim entailment vs transcript
 7  persist                    models.py               transcriptions + entities + soap_note
```

Uploaded audio is written to `backend/uploads/<uuid><ext>` and always deleted in
`finally`. The client filename is display-only metadata, never a path component.

## Service boundaries

| Boundary | Contract |
|---|---|
| frontend ↔ backend | REST/JSON, JWT bearer, `frontend/src/services/api.ts` is the only caller |
| pipeline ↔ models | `groq_client.py` is the single access point; role → provider+model |
| pipeline ↔ eval | eval imports pipeline modules directly, runs offline via `python -m eval` |
| app ↔ schema | Alembic only; CI asserts models and migrations agree |

## Design invariants (from `context/DECISIONS.md` + module headers)

- **Provenance by construction** — the fact table carries transcript spans, so a
  claim without a row is visibly unsupported rather than judged after the fact.
- **Every decoding knob is an env var** — each is a hypothesis the eval harness
  can test; a change is kept only if it moves `medical_term_recall`.
- **The judge is a different provider than the pipeline** — stops the model
  grading its own homework and splits the free-tier quota.
- **Entities/notes are relational tables, not JSON columns** — queryable.

## Where things live

```
backend/        FastAPI app, ML pipeline, eval harness, Alembic
frontend/       React 19 + Vite 7 + Tailwind 4 SPA
context/        living project docs (ARCHITECTURE, DECISIONS, MODEL_ROADMAP, …)
docs/           deployment, local-dev, screenshots, CODEMAPS
scripts/        dev-{backend,frontend,db}.sh, smoke-test.sh
.github/workflows/backend.yml   pytest + migration up/down + schema-drift
```
