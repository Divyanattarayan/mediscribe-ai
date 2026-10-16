# Repo Health & Drift Inventory — mediscribe-ai
Scanned 2026-09-17 · main @ 89807ef · 152 tracked files · 6.8 MB tracked

## Verdict: healthy. The drift is documentation, not code.

The `repo-scan` skill targets 50k-file monorepos with vendored C++ and committed
build artifacts. This repo is the opposite: 152 tracked files, zero vendored
third-party source, zero committed artifacts. Its classic failure modes do not
apply. What follows is the audit that does.

## Surface

```
backend   85 files (68 .py, 12,890 LOC)
frontend  38 files (20 .tsx, 6 .ts, 3,654 LOC)
context   13 .md    docs 7    scripts 4    .github 1
```

## Clean — checked, nothing found

| Check | Result |
|---|---|
| Committed secrets / `.env` | none tracked |
| Committed build artifacts (`dist/`, `__pycache__`, `*.pyc`, `node_modules`) | none tracked |
| Committed databases (`*.db`) / uploaded audio | none tracked |
| Vendored third-party source | none — all deps declared in requirements.txt / package.json |
| Dead backend modules | none — all 21 referenced by ≥1 other module |

Import graph is coherent and layered: `groq_client` (10 referents) and `models`
(9) are the hubs; `schemas` at 1 is a leaf by design, not orphaned.

## Drift — ranked

### 1. `context/ARCHITECTURE.md` predates three phases of work — HIGH

Its 12-step pipeline and its supporting-module list were written before the
Phase 2/3/4 subsystems landed. Grepped for every current subsystem; the doc
mentions **none** of them:

```
fact_table · clinical_facts · claim_verification · clinical_assertions
ontology · asr_confidence · decoder_vocabulary · documentation_style
groq_client · gemini · cerebras                      → 0 hits each
```

Concretely missing:
- **Step 5, the fact table** — the pipeline's central provenance mechanism — is
  absent from the numbered workflow entirely.
- 9 modules on the hot path are absent from "Supporting Backend Modules":
  `clinical_facts`, `claim_verification`, `clinical_assertions`, `ontology`,
  `groq_client`, `decoder_vocabulary`, `documentation_style`,
  `transcript_facts`, `console`.
- Multi-provider model routing (groq / gemini / cerebras) is undescribed.

The file's mtime (2026-09-09) makes it *look* current, which is worse than being
visibly old. `docs/CODEMAPS/architecture.md` now carries the accurate version.

### 2. Stale-by-date docs — MEDIUM

```
docs/test_results.md        2026-01-08   252 days
frontend/README.md          2026-02-24   205 days   (Vite scaffold default)
project_memory.md           2026-04-02   168 days
context/PROJECT_STRATEGY.md 2026-05-04   136 days
context/README_v2.md        2026-05-04   136 days
docs/local-dev.md           2026-05-05   135 days
```
`docs/test_results.md` is the riskiest: results published under a name that
implies currency, predating the ASR model change, the metric rename, and the
judge migration.

Current and trustworthy: `README.md`, `docs/deployment.md`,
`context/DECISIONS.md`, `context/MODEL_ROADMAP.md`, `backend/eval/README.md`.
`README.md` notably self-flags its own stale benchmark (base.en → small.en)
rather than restating figures upward — that is the pattern the other docs lack.

### 3. Test coverage gaps — MEDIUM

20 test files, but 10 modules have no dedicated test, weighted toward the
largest and most behaviour-bearing code:

```
1430 LOC  soap_generator      only test_soap_sections.py (42 lines)
 568 LOC  medical_categories
 558 LOC  main                partial: test_transcribe_flow, test_upload_validation,
                              test_history_ownership, test_auth
 476 LOC  clinical_extraction  none
 399 LOC  entity_extraction    none
 329 LOC  transcription        none
 120 LOC  schemas / models / database / console
```
`clinical_extraction`, `entity_extraction` and `transcription` are 1,204 LOC of
untested pipeline. **Frontend has zero tests** (0 test/spec files across 38).

### 4. Unpinned Python dependencies — MEDIUM

10 of ~25 requirements float, including every ML dependency:

```
faster-whisper      (bare)     scispacy   (bare)     spacy (bare)
openai>=1.0.0       groq>=0.9.0            pydantic[email]>=2.0.0
medspacy>=1.3,<2    pytest>=8.0            httpx>=0.24,<0.28
```
This matters more here than in a typical app: `backend/eval/results/` holds 55
committed run reports whose comparability assumes a fixed stack. A silent
`spacy`/`scispacy` minor bump changes entity extraction and invalidates every
before/after comparison in `context/MODEL_ROADMAP.md` with no signal. The spaCy
model itself is correctly pinned by URL — the libraries around it are not.

## Strengths worth preserving

- **Schema governance is real**: CI applies migrations forward *and reverse*,
  then runs `check_schema_drift` to assert models match migrations.
- **Module headers explain why, not what** — and record measured negative
  results (`spell_correction.py` documents its own disabling with the numbers).
- **Deliberate separation of the two confidence scores**, with the rename
  migration and the reasoning preserved.
- **Judge runs off-provider by design** so the pipeline cannot grade itself.

## Recommended order

1. Rewrite `context/ARCHITECTURE.md`'s pipeline + module list, or point it at
   `docs/CODEMAPS/`. Highest value, lowest effort — it is actively misleading.
2. Rename or date-stamp `docs/test_results.md`.
3. Pin `spacy`, `scispacy`, `faster-whisper`, `medspacy` to exact versions.
4. Add tests for `entity_extraction` and `clinical_extraction`.
5. Decide whether the frontend gets tests or an explicit "no tests" rationale.
