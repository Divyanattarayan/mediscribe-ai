# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Specs are source of truth

`openspec/specs/<capability>/spec.md` holds the mined behavioural contract for 12
capabilities. **Read the relevant spec before changing a capability, and update it in
the same commit as the behaviour change.** A spec whose `Last verified` commit is far
behind HEAD should be re-checked against the code before it is trusted.

Blocks are flat `### Requirement:` / `### Invariant:` with `id`, `entities`, `enforced`
and `test:` metadata. A `test:` anchor means a real test function exists; absence means
the requirement is unverified — do not add anchors for tests that do not exist.

`<!-- uncertainty: -->` comments mark places where observed behaviour could not be
distinguished from deliberate design. Resolve them by asking, not by guessing.

## Commands

Local dev runs Postgres in Docker and the app on the host.

```bash
./scripts/dev-db.sh            # Postgres on :5432
./scripts/dev-backend.sh       # alembic upgrade head, then uvicorn --reload on :8000
./scripts/dev-frontend.sh      # vite on :5173
./scripts/smoke-test.sh        # end-to-end: register -> upload -> note -> history -> cleanup
```

`dev-backend.sh` overrides `DATABASE_URL` to `localhost:5432`, since the value in `.env`
uses the Docker-only `db` hostname. It also activates `.venv/` if present.

### Tests

```bash
cd backend && python -m pytest -q
```

```bash
cd backend && python -m pytest tests/test_ontology.py -q
```

```bash
cd backend && python -m pytest tests/test_auth.py::test_login_happy_path -q
```

Run pytest from `backend/`, not the repo root — `pytest.ini` sets `testpaths = tests`
and the modules import as top-level (`import models`, not `backend.models`).

`conftest.py` does two things worth knowing: it forces `DATABASE_URL=sqlite://` and it
installs **stub ML models** in place of Whisper and spaCy. Tests therefore never load
real model weights and never assert real ASR or NER output. A test that needs genuine
model behaviour does not belong in this suite — use the eval harness.

### Frontend

```bash
cd frontend && npm run dev
```

`npm run build` is `tsc -b && vite build`, so type errors fail the build. `npm run lint`
runs ESLint. There are no frontend tests.

### Evaluation harness

```bash
cd backend && python -m eval list
```

```bash
cd backend && python -m eval run --suite primock57 --stages asr,note,judge --limit 10
```

```bash
cd backend && python -m eval compare --baseline results/<a>.json --current results/<b>.json
```

### Schema

```bash
cd backend && alembic -c alembic.ini upgrade head
```

```bash
cd backend && python -m scripts.check_schema_drift
```

```bash
cd backend && python -m scripts.check_model_access
```

CI (`.github/workflows/backend.yml`) runs pytest, applies migrations **forward and
reverse**, then asserts models and migrations agree. A model change without a migration
fails CI.

## Architecture

React 19 SPA -> FastAPI monolith -> Postgres, plus an offline evaluation harness.
`docs/CODEMAPS/` carries the detailed map (architecture, backend, frontend, data,
dependencies).

### The pipeline is the product

`POST /api/transcribe` in `backend/main.py` runs seven stages in order. Every stage is
blocking CPU work dispatched through `run_in_threadpool` — the route is `async def`, so
calling them inline would stall the event loop for the whole job.

```
1  transcribe_audio          transcription.py       biased by decoder_vocabulary.py
1b correct_medical_spelling  spell_correction.py    disabled by default
2  validate_medical_content  content_validator.py   gate: non-clinical audio returns early
3  extract_medical_entities  entity_extraction.py   + clinical_assertions + ontology
4  extract_clinical_repr     clinical_extraction.py LLM -> structured IR
5  build_fact_table          clinical_facts.py      claim + supporting transcript span
6  generate_soap_note        soap_generator.py      LLM primary, rule-based fallback
7  persist                   models.py
```

**Provenance by construction is the central design idea.** Every fact-table row carries
the transcript span that supports it, so a claim without a row is visibly unsupported
rather than judged after the fact. Changes that let a note assert something the fact
table does not carry defeat the architecture, not just a test.

### Invariants that are clinical-safety, not code-quality

- **Assertion axes change what a mention means.** "Denies chest pain" must never surface
  as a positive finding. `clinical_assertions.py` resolves negation, temporality,
  experiencer and uncertainty; every entity carries all four.
- **`medical_content_score` and `asr_confidence` are different things.** The first is
  transcript term-density computed before a note exists, and gates non-clinical audio.
  The second is mean per-word acoustic probability, nullable because only some ASR paths
  produce one. Migration `0004` exists because the UI once presented the first as system
  confidence. Do not conflate them.
- **RxNorm codes are resolutions; ICD-10 codes are ranked suggestions.** The difference
  is stored as `ontology_requires_review`, not inferred from the system name.
- **Client filenames are display-only metadata**, never a filesystem path component.
  Uploads are stored under a UUID and always deleted in the request's `finally` block.
- **History routes enforce ownership by `user_id`** rather than assuming it.

### Single access points

- `groq_client.py` is the only module that talks to an LLM. It owns provider routing
  (groq / gemini / cerebras), retry, pacing and per-request token accounting. Do not add
  a second client.
- `frontend/src/services/api.ts` is the only module that makes network calls.
- Schema changes go through Alembic only — the app never creates tables. Migrations are
  applied by the start commands *before* `main.py` is imported.

### Things that look like bugs but are decisions

- `spell_correction.py` is off by default because measurement showed it inverts clinical
  meaning (`regular` -> `irregular`, 24x). Its header carries the numbers. Do not
  re-enable it without new measurement.
- Every ASR knob in `transcription.py` is an env var because each is a hypothesis the
  eval harness can test. Change one only with a before/after run.
- The eval judge runs on a **different provider** from the pipeline, so the pipeline
  cannot grade its own output, and so evaluation does not consume the pipeline's quota.
- `backend/eval/results/` holds 55 committed run reports. They were all produced by
  `GROQ_MODEL` on Groq. Changing the pipeline model invalidates every before/after
  comparison recorded in `context/MODEL_ROADMAP.md`.

### Frontend shape

No router. `App.tsx` switches on `currentPage` from the Zustand store in
`store/appStore.ts`, which holds nav, auth, upload, result, history, profile and
preferences in one store. Dark mode is token-driven: toggling `.dark` on `<html>`
re-points every `--color-*` variable, so components never branch on theme for colour.

## Documentation trust map

Current and reliable: `README.md`, `docs/CODEMAPS/*`, `openspec/specs/*`,
`docs/deployment.md`, `context/DECISIONS.md`, `context/MODEL_ROADMAP.md`,
`backend/eval/README.md`.

**Stale — do not rely on:** `context/ARCHITECTURE.md` predates the fact table, claim
verification, assertions, ontology linking, `asr_confidence` and multi-provider routing;
its recent mtime makes it look current. `docs/test_results.md` (Jan 2026) predates the
ASR model change and the metric rename. `context/PROJECT_STRATEGY.md`,
`context/README_v2.md` and `docs/local-dev.md` are months behind.

Module header comments are the highest-signal documentation in this repo. They explain
why a thing exists and frequently record measured negative results. Preserve that style:
when a change is driven by measurement, put the numbers in the header.

## Known gaps

`soap_generator.py` (1,430 LOC) is tested only by six tests on `_normalize_soap_sections`
— the quality scorer, repair loop and rule-based fallback have none.
`clinical_extraction.py`, `entity_extraction.py` and `transcription.py` have no test
modules at all. The `spec.md` files mark which requirements this leaves unanchored.
