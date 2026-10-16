# Model Roadmap And Status

Tracks the model-quality work: what is done, what is in progress, and what is
left. This is the shared status file — update it in the same change that moves
an item, not afterwards.

Scope note: `PLAN.md` tracks the product phases (auth, export, review mode).
This file tracks the *model*: ASR, extraction, note generation, and the evidence
that any of it works. The two run in parallel and neither supersedes the other.

Last updated: 2026-09-11

**Status legend:** `[x]` done · `[~]` in progress · `[ ]` not started · `[!]` blocked or needs a decision

---

## Open decisions

Things the next stretch of work is genuinely waiting on, rather than tasks that
can simply be picked up. Kept at the top because each one gates a phase below.

1. **[x] Which ASR model.** Settled 2026-09-11: `small.en`. See § *Choosing a
   model* below. The open item it leaves behind is the 20-channel confirmation
   run, which was consciously deferred.
2. **[~] Groq free tier vs. paid, or a cheaper eval model.** 200,000 tokens/day.
   Phase 3 spends ~5 model calls per note, so a four-case run can exhaust the
   day's budget; this has blocked measurement twice. PriMock57's 57 consultations
   cannot be evaluated end to end under it.

   **Resolved 2026-09-11 for evaluation.** The judge now runs on Gemini
   `gemini-3.8-flash`, verified end to end through `rubric_score` and
   `claim_entailment`. Its free tier is bounded by requests/day (~1,500) rather
   than tokens, so judging no longer competes with generation for the 200,000
   token Groq budget. Cerebras was rejected despite a larger token allowance:
   an 8K free-tier context will not reliably hold a consultation transcript
   plus fact table.

   Still open for the **pipeline**, which remains on Groq and still has 200,000
   tokens/day. Phase 3's ~5 calls per note is the cost that matters, and a
   full 57-consultation run is still out of reach without paying or moving the
   pipeline too — and moving the pipeline means re-baselining everything.
3. **[ ] How to grow the entity golden set past 4 synthetic cases.** Both
   automated routes failed honestly (§ *Growing the evaluation set*). The options
   are hand-annotation, accepting note-level checklist coverage as the primary
   measure instead, or finding another annotated corpus.
4. **[ ] Whether the frontend should surface the new pipeline output.** The fact
   table, verification report, assertions, ontology codes and `asr_confidence`
   all reach the API and nothing renders them. Deliberate, not an oversight —
   but it is the cheapest route to a convincing demo after Phase 5.

Known and deliberately left alone: the verifier flags "continue sertraline" as
unsupported despite a prompt rule covering that case. It is a prompt-following
miss, not a code bug, and it is one case out of four — fixing it would be tuning
against a set too small to tune against.

---

## Why this file exists

A review of the pipeline on 2026-09-09 found two problems worth naming plainly:

1. **The model was fitted to two demo recordings.** Roughly 700 lines across
   `soap_generator.py`, `clinical_extraction.py` and `spell_correction.py`
   keyed off literal sentences from a diabetes counselling recording and a
   chest-pain recording. On any other audio the rules either did nothing or
   actively corrupted the note.
2. **Nothing was measured.** No golden set, no metrics, no baseline. Every
   quality claim about the project was unfalsifiable.

Phases 0 and 1 address those two. Phases 2 onward improve the model on top of
evidence rather than on top of intuition.

---

## Phase 0 — Remove the demo-specific overfitting

**Status: complete (2026-09-09).** Accepted a temporary quality drop in exchange
for behaviour that generalises. What was deleted was never general in the first
place; it only looked good on the two recordings it was written against.

- [x] Delete `PHRASE_NORMALIZATIONS` from `backend/spell_correction.py` — eight
      regexes lifted from demo audio, including a patient's name
      (`"Harry Miles" → "Harry Myles"`) applied to every user's transcript.
- [x] Delete `_apply_clinical_consistency_rules` and its pericarditis/diabetes
      helpers from `backend/soap_generator.py` (~270 lines). This included
      `re.sub(r"\bsweating\b", "poor diet", ...)`, which silently replaced a
      clinical symptom across all four sections, and sentence-level regex
      deletion of anything mentioning insulin, NSAIDs, troponin, colchicine or
      ECG in a counselling encounter.
- [x] Replace literal-sentence encounter inference (`"blood test said i had
      diabetes"`) with a generic marker-count classifier, consolidated as
      `classify_encounter_type` in `backend/transcript_facts.py`. The
      request-supplied `encounter_type` remains authoritative; this is only a
      fallback.
- [x] Rewrite `_extract_with_rules` in `backend/clinical_extraction.py` to
      report what the transcript and entity extractor contain, rather than
      emitting hardcoded diabetes bundles (fixed five-item monitoring list,
      DESMOND referral, "concerns influenced by colleague's experience").
- [x] Replace the quality scorer. The old `_score_soap_quality` penalised only
      issues the two demo scenarios produced, so an unrelated note scored ~100
      by default. The new one is generic: structural checks plus a lexical
      groundedness check, no disease names anywhere in it.
- [x] Repairs may now only *add* a fact the representation already holds or
      remove a verbatim duplicate. Nothing deletes clinical content.
- [x] Fix the blocked event loop: the ML stages in `POST /api/transcribe` ran
      inline in an `async def` route, freezing the server for the whole job.
      They now go through `run_in_threadpool`.
- [x] Replace deprecated `datetime.utcnow()` with timezone-aware calls.

### Found while doing Phase 0

- [x] **The LLM path was dead.** `GROQ_MODEL` was pinned to
      `llama-3.3-70b-versatile`, which Groq has decommissioned; every call
      returned 404 and the pipeline silently served the rule-based fallback for
      every note. Now `openai/gpt-oss-120b`, overridable via the `GROQ_MODEL`
      env var. **The eval harness caught this on its first run.**
- [x] **Truncated JSON downgraded every run.** Both Groq calls used small
      `max_tokens` with no `response_format`. Reasoning models spend budget
      before emitting output, so replies truncated mid-JSON and were treated as
      "the LLM failed". Both now share `_chat_json` with
      `response_format=json_object`, a brace-extraction fallback, and a realistic
      token budget.
- [x] **One malformed field killed the whole extraction stage.**
      `_dedupe_strings` called `.strip()` on whatever the model returned and
      raised on a dict. Values are now coerced via `_as_text`.

### Phase 0 leftovers

- [x] `Transcription.confidence_score` renamed to `medical_content_score`
      (migration `20260911_0004`, backend, and the frontend through to the
      "Medical content" label). It stores the validator's term-density score,
      computed before a note exists; the UI presented it as "Confidence" with
      high/medium/low badges, which invited a clinician to read 94% as the
      system's confidence in the note. A real per-note confidence still needs
      the ASR word probabilities of Phase 4.
- [x] `MedicalEntity.confidence` is now real for medications, filled from the
      RxNorm match score. Conditions stay at `0.0` deliberately: an ICD-10
      shortlist is a suggestion, and writing a confidence from it would claim an
      assurance that does not exist.
- [x] README corrected and given a **Measured Performance** section carrying the
      real numbers. Removed a claim that the content validator produced "zero
      false positives and zero false negatives across all test scenarios" —
      there was no test set behind it. Fixed the decommissioned model name, a
      wrong density threshold (10% stated, 8% actual), and an API example whose
      fields no longer exist.
- [x] **Fuzzy spell correction measured, and switched off.** It was worse than
      "plausibly" harmful. See below.

### Spell correction: measured, then disabled (2026-09-11)

The fuzzy corrector had been in the live pipeline, unmeasured, since the start.
Two measurements settled it.

**Run over PriMock57's human transcripts**, which are correct by definition, so
every change is a false correction. It altered 309 of 34,367 words (0.90%):

| change | count | why it matters |
|---|---|---|
| `feeling` → `peeling` | 51 | nonsense |
| `regular` → `irregular` | 24 | **inverts the clinical meaning** |
| `start` → `stat` | 17 | changes the instruction |
| `eating` → `sweating` | 11 | invents a symptom |
| `ever` → `fever` | 10 | invents a symptom |

`regular → irregular` on a cardiac examination is a patient-safety defect.

**Run over real ASR output**, which is what it exists for, over the 20 PriMock57
channels in the ASR baseline:

| metric | before | after |
|---|---|---|
| WER | 0.2713 | 0.2790 |
| medical-term error rate | 0.1705 | **0.5105** |

It improved **0 of 20** cases and made 19 worse. Now off by default behind
`MEDICAL_SPELL_CORRECTION=1`, with the measurement recorded in the module and
tests pinning both the default and the corruption.

### The dictionary contained misspellings (2026-09-11)

Chasing why the corrector failed on its own demo examples found the cause: five
misspellings were sitting in `medical_categories.py` as valid entries —
`certraline`, `spiranylactone`, `hypertropium`, `methamin`, `diabetes malitis`.

That is worse than untidy. It meant the entity extractor emitted them as
legitimate clinical entities; the spell corrector could never fix them, since a
term already in the vocabulary scores 100 against itself; and
`medical_term_error_rate` counted them as valid medical terms, so the ASR metric
would have credited a misspelling as a correct transcription.

Every medication in the file was checked against RxNorm to find them, rather
than by eye. Eight had no exact concept; four were misspellings and the other
four — `flexeril`, `vicodin`, `zofran`, `nitro` — are real brand names and
clinician shorthand, and were kept. A similarity scan over conditions found only
`diabetes malitis`: every other near-pair (`hypertension`/`hypotension`,
`stable angina`/`unstable angina`) is clinically distinct, which is exactly why
they were checked against a vocabulary rather than removed by string distance.

The ASR baseline stands: none of the removed terms appears in the PriMock57
references or in our transcripts.

---

## Phase 1 — Evaluation harness

**Status: harness built and running (2026-09-09); real-dataset baselines still
to record.** Everything downstream depends on this, because without it no change
can be shown to help.

Built at `backend/eval/` — see `backend/eval/README.md` for full usage.

- [x] Case schema and JSONL loader (`eval/schema.py`), tolerant of datasets with
      different coverage (audio / transcript / note / entities).
- [x] Offline metrics, deterministic and CI-safe:
      WER with edit-type breakdown; **medical-term error rate** and recall over
      the clinical lexicon; entity P/R/F1 in strict and lenient modes; lexical
      hallucination and omission rates.
- [x] LLM judge (`eval/metrics/judge.py`): five-criterion clinical rubric,
      claim-level entailment with evidence spans, plus `agreement()` reporting
      MAE and Spearman against human scores.
- [x] Runner and CLI: `python -m eval run|compare|list`, per-case reports,
      aggregates that carry the count each mean came from, and a
      `--fail-on-regression` gate that knows which metrics are lower-is-better.
- [x] Dataset adapters for PriMock57, ACI-Bench and MTS-Dialog. Data is not
      vendored; `eval/data/` is gitignored.
- [x] Seed golden set: three synthetic transcripts with hand-checked reference
      entities and deliberately no reference notes.
- [x] 20 offline metric tests (`backend/tests/test_eval_metrics.py`). Full suite:
      83 passing.
- [x] First baseline recorded: `backend/eval/results/baseline-local.json`.

### Phase 1 remaining

- [x] PriMock57 wired in, with a `.TextGrid` parser and two suites from one
      download: `primock57` (114 per-channel ASR cases) and `primock57_notes`
      (57 consultations as merged dialogue plus the clinician's own note).
- [x] Audio is streamed per case and deleted, not stored. A full LFS clone keeps
      the corpus twice (~1.9 GB checked out plus the same again in
      `.git/lfs/objects`); a WER run reads each file once, so peak disk is now
      one recording (~26 MB). `--audio-cache DIR` opts back in.
- [x] **ASR baseline recorded** over 20 channels (10 consultations, ~3 hours of
      audio, 28 min of CPU). Committed as
      `eval/results/baseline-primock57-asr.json`. Numbers and analysis below.
- [ ] Download ACI-Bench and record a note-generation baseline against its
      published results.
- [x] **Evaluation widened from 4 synthetic cases to 20 real consultations**
      (2026-09-11) — though not in the shape originally planned. See below.
- [ ] Entity-level golden set beyond the 4 synthetic cases. Two automated routes
      were tried and both failed honestly; growing this properly needs human
      annotation time, which is worth saying rather than faking.
- [ ] **Calibrate the judge**: hand-score 20–30 notes, store as `human_score`,
      report MAE and Spearman. Until then the judge number is uncalibrated and
      must be quoted as such.
- [x] CI: `.github/workflows/backend.yml` runs the test suite and a migration
      job on every push and PR. The migration job applies, reverses and
      re-applies the revisions, then runs `scripts/check_schema_drift`, which
      fails when `models.py` describes something no migration creates — the rule
      `DECISIONS.md` states but nothing previously enforced. CI installs
      `requirements-ci.txt`, derived by recording the imports of a real test
      run, so it skips the ~500 MB of ASR and NER weights conftest stubs anyway.
- [ ] The `python -m eval` gate stays a local pre-merge step: it needs the real
      models and an API key, and the generation metrics are non-deterministic at
      temperature 0.3, so gating a PR on them would be noise rather than signal.
- [ ] Publish baseline numbers in the README, replacing the unfalsifiable claims.

### ASR baseline — the first real number the project has

`faster-whisper base.en`, int8, beam 3, no VAD. PriMock57, 20 channels of real
primary-care consultation audio, 17,555 reference words.

| metric | value | what it answers |
|---|---|---|
| `wer` | **0.271** | does the output match a verbatim transcript |
| `wer_fluent` | **0.231** | did it capture what was actually said |
| `medical_term_error_rate` | **0.171** | did the clinical content survive |
| `medical_term_recall` | **0.886** | share of clinical terms recovered |

**The error mix is the finding, not the WER.** Deletions are 53% of all errors,
substitutions 41%, insertions 6%, and every single channel came back *shorter*
than its reference — ratios from 0.76 to 0.95, never above 1.0. That is
systematic under-transcription, not random error, so it was worth asking what
was being dropped:

| filler | in reference | in output | dropped |
|---|---|---|---|
| `um` | 546 | 23 | 523 |
| `uh` | 435 | 20 | 415 |
| `ok` | 418 | 0 | 418 |

**60% of the missing words are disfluencies.** PriMock57's transcripts are
verbatim; Whisper is trained to produce clean prose and omits hesitation sounds.
That is a transcription-convention difference, not a recognition failure, and
for a scribe it is desirable behaviour being scored as error.

Hence `wer_fluent`, which strips hesitation sounds from *both* sides before
aligning: 0.271 → 0.231. Reported alongside raw WER and never instead of it,
because the two answer different questions. Deliberately only sounds and
backchannels are stripped — "no", "yes" and "right" stay, since dropping those
would hide real errors.

**Quote `medical_term_recall` 0.886 as the headline.** It is the number that
tracks whether a note can be written from the transcript, and it is unaffected
by the disfluency artefact. The remaining 11% of clinical terms lost is what
Phase 4 has to fix, and VAD plus a larger model is the obvious first attempt.

### Growing the evaluation set: two failures and what worked (2026-09-11)

PriMock57 ships **clinician-authored checklists** for 20 of its 57
consultations — the clinicians who designed each case listing what was
clinically present, rated Critical / Non-Critical / Irrelevant, including the
explicit negatives ("No blood in stool", "no vomiting"). That is exactly the
external ground truth the golden set lacks, since annotating transcripts with
our own extractor and scoring our extractor against the result measures
self-agreement: recall would be near 1.0 by construction, because we cannot miss
what we never wrote down.

Parsed without a new dependency (`eval/primock_checklists.py` — .xlsx is a zip
of XML and only two parts are needed): **1,287 scored items across 20
consultations**, with two clinicians independently annotating 7 of them.

**Attempt 1 — checklist items as entity references. Rejected.** The conversion
produced roughly half real findings ("blood in stool" negated, "night sweats"
negated, "asthma") and half structural fragments the checklists use as
scaffolding ("one side", "comes and goes", "accountant", "and 2 children").
Scoring an entity extractor against references containing "accountant" would
understate recall for reasons unrelated to extraction. Filtering the fragments
needs a clinical vocabulary: ours would reintroduce the circularity, and the
external NLM endpoint was no better — it rejected "loss of appetite" and
"watery stool" while matching "left" to *Left ventricular dysfunction* at full
confidence.

**Attempt 2 — lexical note coverage. Rejected by its own calibration.** Using
the items whole ("does the note cover this finding?") removes the span-mapping
problem. Scoring the **clinician's own note against their own checklist** — a
ceiling, since if a human reference scores badly the metric is broken — gave
**0.22**. The misses said why: the checklist writes "Abdominal pain - lower"
where the note writes "LLQ pain", and "7 times/day" where it writes "x6/day".
Clinical shorthand does not word-match.

**What shipped — model-judged coverage with a human ceiling**
(`eval/metrics/coverage.py`). The model is asked a narrow, checkable question
("is this specific human-authored finding present in this note?") rather than
"is this note any good", so the ground truth stays human and only the matching
is automated. The same ceiling check now reports alongside every score:

| consultation | lexical ceiling | judged ceiling |
|---|---|---|
| day1_consultation01 | 0.22 | **0.63** |
| day1_consultation02 | 0.37 | **0.55** |

A judged ceiling near 0.6 is plausible and useful: real clinicians write terse
notes and genuinely omit fine-grained checklist detail. It makes the metric
interpretable — a pipeline scoring 0.5 achieved 80% of what the human did on the
same items — which a bare coverage percentage never is.

`ceiling_*` metrics are marked informational so the gate never treats the human
score as a target to beat, and a failed judgement returns **no** metric rather
than silently falling back to the lexical version, which would make two runs
incomparable without saying so.

### The entity metric was measuring the wrong thing (fixed 2026-09-09)

Investigating why entity F1 sat at 0.57 found that most of the "errors" were
artefacts of the metric and of my own reference annotations, not model failures:

| problem | example | effect |
|---|---|---|
| multiset matching | `headaches` three times in the output, once in the reference | two false positives for finding it three times |
| no plural folding | reference `headache`, output `headaches` | scored as **both** a miss and a spurious |
| reference wording | reference said `shortness of breath`; transcript and output both say `breathlessness` | counted as a miss |

Fixed: matching is now set-based over distinct concepts, with symmetric plural
folding. Four reference annotations were corrected to the spans that actually
appear in the transcripts, and the convention is written into the case file —
**annotate the span that exists, not the canonical term**, because annotating
"hypertension" where the patient said "high blood pressure" scores a
normalisation step we do not perform and hides the lexicon gaps we do have.

One subtlety worth keeping: a richer stemming rule (`-ches` → strip `es`, to
turn "boxes" into "box") broke the invariant, because it fires on the plural
with no matching transform for the singular — `headaches` became `headach`
while `headache` stayed itself. A test now pins symmetry.

| metric | before | after | delta |
|---|---|---|---|
| `entity_lenient_f1` | 0.574 | **0.805** | +0.231 |
| `entity_lenient_precision` | 0.481 | **0.748** | +0.268 |
| `entity_lenient_recall` | 0.741 | **0.877** | +0.136 |
| `entity_strict_f1` | 0.397 | **0.507** | +0.110 |
| `hallucination_rate` | 0.443 | 0.386 | −0.057 |
| `assertion_exact_accuracy` | 0.813 | 0.768 | −0.044 |

**The assertion dip is coverage, not regression.** Matched entities rose from
5.0 to 6.0 per case: plural folding made terms scorable that the metric
previously skipped entirely, and two of the newly-scored ones are the known
anaphoric-denial failure ("Any dizziness or headaches? No, none of those"),
which was previously counted once because `headaches` never matched
`headache`. The layer did not get worse; the measurement got more complete.

The earlier 0.574 / 0.397 figures should not be quoted anywhere — they were
depressed by the artefacts above. Model quality did not change between those
runs and these.

Still genuinely open after the fix: `entity_strict_f1` 0.507 means category
assignment remains much weaker than detection, and the extractor still
over-produces (`pressure` from "blood pressure", a bad merge into
`nausea or vomiting`).

### What the first local baseline actually says

Four synthetic cases, note stage only, `openai/gpt-oss-120b`. Current figures
after the metric correction above:

| metric | value | reading |
|---|---|---|
| `entity_lenient_f1` | 0.805 | detection is decent; precision 0.75, recall 0.88 |
| `entity_strict_f1` | 0.507 | category assignment is still much weaker than detection |
| `assertion_exact_accuracy` | 0.768 | all three assertion axes right at once |
| `hallucination_rate` | 0.386 | see the caveat below — this number is not what it looks like |

**Read the hallucination rate carefully.** It is a *lexical* proxy: it flags any
medication or condition in the note that is not in the transcript. On inspection,
most flags on these cases are legitimate clinical reasoning — proposing
pericarditis as a differential for pleuritic positional pain after a viral
illness, or ibuprofen as treatment — and one ("allergies") comes from the note
correctly stating that allergies were not elicited. The proxy cannot tell a
*proposed* differential from an *asserted* fact.

So treat it as a **relative regression signal, not an absolute quality claim**,
and do not quote it as a hallucination rate publicly until Phase 3 replaces it
with claim-level entailment. The entity numbers, by contrast, are sound: they
compare against hand-checked references and can be quoted as they stand.

---

## Phase 2 — Clinical NLP axes and ontology linking

**Status: assertion detection complete (2026-09-09). Ontology linking not started.**

### Assertion detection — done

- [x] Negation, temporality, experiencer and hypothetical detection via
      **medspaCy ConText**, in `backend/clinical_assertions.py`. ConText runs a
      second time against the *merged* two-pass entity list rather than firing
      on the NER entities alone — the dictionary scan finds most symptom
      mentions, and those are the ones most often negated.
- [x] Conversational ConText rules. The shipped rules target dictated prose
      ("history of"); consultation speech says "as a child", "used to get",
      "my dad". Added as generic phrasings of the same four axes.
- [x] **Speaker-label masking.** The largest single source of missed
      assertions: ConText's negation triggers do not fire through a leading
      `Patient:`, so `No nausea.` was detected and `Patient: No nausea.` was
      not. Labels are replaced with equal-length spaces, preserving every
      character offset in the pipeline.
- [x] Assertions reach the prompt. `_build_entity_summary` groups terms into
      active / denied / historical / family / hypothetical / uncertain blocks
      with explicit instructions, so a denied symptom cannot be documented as
      present.
- [x] Assertions reach the clinical representation: `denied_symptoms`,
      `family_history`, `historical_manifestations` and
      `active_differential_targets` are populated from the axes instead of one
      flat list.
- [x] Persisted: `negated`, `temporality`, `experiencer`, `uncertain`,
      `assertion_source` on `medical_entities`, migration `20260909_0002`,
      verified against both a clean database and the existing dev one.
- [x] Assertion metrics in the harness (per-axis and exact accuracy), scored
      only over entities found in both reference and output so a detection miss
      is not counted twice.
- [x] Golden set annotated with assertion references, plus a fourth case built
      to stress the layer: four denials, two family conditions, two resolved
      past conditions, one hypothetical.
- [x] 24 new tests. Full suite: 108 passing.

### Assertion results

Measured against the Phase 2 entry baseline, same four cases:

| metric | before | after | delta |
|---|---|---|---|
| `assertion_exact_accuracy` | 0.719 | **0.813** | +0.094 |
| `assertion_temporality_accuracy` | 0.750 | **0.875** | +0.125 |
| `assertion_experiencer_accuracy` | 1.000 | **1.000** | — |
| `assertion_negated_accuracy` | 0.969 | 0.938 | −0.031 |
| `hallucination_rate` | 0.690 | 0.443 | −0.246 |
| `entity_lenient_f1` | 0.574 | 0.574 | 0.000 |

Read three ways:

- **Entity F1 unchanged to four decimal places is the control.** Phase 2 added
  assertion fields and touched detection not at all, so identical detection
  numbers are the expected result and confirm the comparison is clean.
- **The negation dip is real but not a true regression.** The one failing case
  is `Any dizziness or headaches? No, none of those.` — anaphoric denial, which
  needs coreference and is beyond ConText. It happened to be marked negated
  before speaker-label masking, by accident. A coincidental hit was replaced by
  an honest miss. A test pins the current behaviour so a future fix has
  something to flip.
- **The hallucination-rate fall is encouraging but is not evidence.**
  Generation runs at temperature 0.3 over four cases; the same config varies by
  several points run to run. Do not quote it.

### Known limitations

- Anaphoric denial ("no, none of those") is unresolved — needs coreference.
- Temporality is the weakest axis. Remaining misses: a relative's past MI
  ("in his fifties") and results reporting ("the blood test showed").
- The reference annotates a *term*; assertions belong to a *mention*. Where a
  term appears twice with different assertions — the clinician's question and
  the patient's answer — the metric compares against the first. Span-level
  references are the proper fix.
- **The golden set is too small to tune against.** Four cases cannot justify a
  rule, and adding one because it makes a case pass rebuilds exactly the
  overfitting Phase 0 removed. `_CUSTOM_RULE_SPECS` carries this as written
  policy: a rule must be defensible as a general phrasing of its axis.

### Ontology linking — done, via APIs instead of a local knowledge base

**Status: complete (2026-09-09).** scispaCy's `UMLSEntityLinker` was the planned
route and needs a ~1 GB download. It was dropped in favour of the NLM's public
REST services, which need no key, no licence and no disk — a better fit for a
laptop, and a more honest demonstration of integration work than a bundled KB.

- [x] `backend/ontology.py`: RxNorm for medications (`rxnav.nlm.nih.gov`),
      ICD-10-CM and the SNOMED-backed conditions endpoint for diagnoses
      (`clinicaltables.nlm.nih.gov`).
- [x] On-disk response cache, negative results included. Clinical vocabulary is
      small and repeats heavily, so a warm cache answers almost everything
      locally and an unknown term costs one request, not one per transcript.
- [x] Best-effort by design: an unreachable NLM service leaves entities
      unlinked and never fails the transcription request. Switchable off with
      `ONTOLOGY_LINKING=0`.
- [x] `MedicalEntity.confidence` is finally real — for medications. An exact
      RxNorm hit is 1.0; a misspelling matched approximately carries its name
      similarity ("adervastatin" → atorvastatin, 83.3).
- [x] Persisted: `ontology_system`, `ontology_code`, `ontology_display`,
      `ontology_requires_review`, migration `20260909_0003`.
- [x] 15 offline tests using recorded response shapes, so the suite neither
      needs the network nor breaks when NLM is slow.

### What the two sides are worth, honestly

They are not equally reliable and the code does not pretend otherwise.

**Medications resolve.** RxNorm maps a drug name to one concept and either finds
it or does not. Verified against the live API: `amlodipine` → 17767,
`atorvastatin` → 83367, `metformin` → 6809, the misspelling `adervastatin` →
83367 (atorvastatin), and `wibblefloop` → no match.

Two bugs were found and fixed while measuring this. RxNav's own match score is
on an opaque scale — a *correct* match for a misspelling scores about 9, not 90
— so the first threshold rejected good matches; scoring now uses rapidfuzz name
similarity, the same measure the spell-correction stage uses. And taking the
first candidate was wrong because only some candidates carry a name.

**Conditions do not resolve, and are shipped as suggestions.** Mapping a bare
diagnosis to ICD-10 is a curated-crosswalk problem, not a search-ranking one.
The API returns most-specific-first, so the naive read of `pericarditis` is
`A39.53 Meningococcal pericarditis` — inventing a specificity the transcript
never stated, which is the exact fabrication the rest of the pipeline exists to
prevent.

`_rank_icd_candidates` reorders generic-first (exact name > fewest added
qualifier tokens > shorter code, treating "unspecified"/"uncomplicated" as
marking the *absence* of a qualifier). It gets `pericarditis` → I30.9,
`asthma` → J45.909 and `type 2 diabetes` → E11.9 right. It still gets
`hypertension` wrong (I15.0, should be I10 by convention) and `diabetes` wrong
(`E23.2 Diabetes insipidus`). No ordering rule derives those from candidate
names alone.

So every condition result carries `requires_review: true` and a shortlist of
alternatives, and **nothing consumes the ICD code automatically**. It is a
review surface for a clinician, which is what the roadmap's coding-suggestions
feature always intended.

- [ ] Measure ICD suggestion quality: annotate the golden set with expected
      codes and report top-1 and top-3 accuracy. Currently unmeasured, so the
      shortlist should not be described as accurate — only as a shortlist.
- [ ] Consider a curated SNOMED→ICD-10 crosswalk for the common cases, which is
      how this is actually solved.
- [ ] Report the entity-F1 delta. Entity precision is 0.48 and strict F1 0.40;
      linking has not yet been used to filter or re-categorise entities, which
      is where it would move those numbers.

## Phase 3 — Fact-table generation and claim-level verification

**Status: built and wired (2026-09-09); the quality delta is not yet measured.**

- [x] **Fact table** (`backend/clinical_facts.py`). Every clinical statement is
      a row carrying the transcript span that supports it, so provenance exists
      by construction rather than by inspection afterwards. Two producers,
      trusted differently: entity-derived rows are exact and free (the offsets
      already exist), while LLM-derived rows must return a **verbatim quote**
      that `locate_evidence` finds in the transcript.
- [x] Evidence verification. Verbatim quotes match exactly; punctuation and
      casing differences match fuzzily; **paraphrases and inventions are
      rejected**. An unverified fact is kept in the table but excluded from the
      prompt — a dropped row is invisible, a flagged one shows what the model
      claimed and could not support.
- [x] The fact table leads the generation prompt, grouped by what each row
      asserts (present / denied / historical / family / hypothetical /
      uncertain). The transcript still follows: constraining generation to the
      table alone trades hallucination for omission, and that is not a trade to
      make without measuring both.
- [x] **Claim-level verification** (`backend/claim_verification.py`), promoted
      from an eval metric into the pipeline. Every claim is judged against the
      transcript with a supporting quote.
- [x] Nothing is rewritten. Unsupported claims are named and the section is
      handed back to the generator. The old repair layer deleted sentences by
      regex and silently dropped true findings; a verifier that edits clinical
      prose by pattern is that same mistake relocated.
- [x] A verifier that cannot run reports `ran=False` and says so in the log, and
      `quality_report.groundedness_check` records whether the score came from
      `claim_entailment` or the `lexical_terms` fallback. "Nothing was checked"
      must not read as "nothing was wrong".
- [x] `_ungrounded_terms` demoted to fallback rather than deleted: it needs no
      API key, so it still runs when entailment cannot.
- [x] `pipeline_unsupported_claim_rate` added to the eval harness.
- [x] `groq_client.py` extracted — `clinical_extraction` had been importing the
      Groq helper *from* `soap_generator`, making a generation module the home
      for shared infrastructure.
- [x] 51 new tests. Full suite: 193 passing, all offline.

### Evidence verification, measured on real output

Across the four local cases: **10–19 facts per case, 6–8 of them LLM-produced,
and zero failed citations.** The guarantee holds in practice, not only in tests.

### Bugs found while building it

- **Clinicians' questions became findings.** "Any nausea? / No nausea at all"
  produced two facts — one un-negated from the question, one denied from the
  answer — and the question's version could reach the note as a symptom the
  patient had explicitly denied. A question is an enquiry, not an assertion, so
  declaratives now win; a term only ever *asked* about is still kept.
- **`groq_client` did not load `.env`**, so any entry point that had not already
  called `load_dotenv` got "Missing API key" on a machine where the key was set.
- **The retry policy made things worse.** Groq reports per-minute limits and
  daily quotas with the same 429 and they need opposite handling; a daily quota
  was being retried four times, returning the same error more slowly while the
  caller silently downgraded.
- **A regex read `224.999999ms` as 224 minutes** (matching `m` inside `ms`),
  which would have misclassified every routine per-minute limit as too long to
  wait for, breaking retries entirely. Caught by a new test, not by a run.
- **The verifier over-flagged documentation scaffolding**, marking "Allergies
  were not elicited in this recording" unsupported. That is a claim about the
  consultation, true precisely when the transcript lacks the topic. Prompt
  tightened, along with continuing an already-established medication.

### Why the delta is not measured yet

Phase 3 adds roughly five model calls per note — fact extraction, generation,
verification, regeneration, re-verification. The Groq free tier allows **200,000
tokens per day**, and a four-case run exhausts it. Two attempts produced
partial coverage (verification ran on 2 of 4 cases, then 0 of 4).

Cost work done in response, since the budget is now the binding constraint on
how much can be evaluated:

- The representation dump in the generation prompt was pretty-printed JSON
  including empty lists and a duplicate copy of the entities. Pruned and
  compacted: **922 → 180 characters** on a representative case.
- Re-verification is skipped when regeneration changed no prose.
- `groq_client` now counts tokens per request, returned as `token_usage` and
  logged with each transcription, so the cost of a pipeline change is visible
  rather than inferred from a 429 days later.

- [x] **Phase 3 delta measured** (2026-09-11), committed as
      `eval/results/baseline-phase3-verification.json`. Four cases, zero failed
      (the console-encoding crash below is what caused the two earlier partial
      runs). Verification ran on 3 of 4 cases — see "why not 4/4" below.

      | metric | value |
      |---|---|
      | fact-table citation failures | **0 / 45** across all four cases |
      | `pipeline_unsupported_claim_rate` | 0.133 (mean over 3 scored cases) |
      | `pipeline_claims_total` | 23 (mean) |
      | entity / assertion metrics | unchanged (0.0 delta) vs. the Phase 2 baseline |

      The unchanged entity/assertion numbers are the control: Phase 3 does not
      touch extraction, so identical numbers confirm the comparison is clean.

      **Why not 4/4:** `eval/runner.py` was not recording *why* a case fell back
      to the lexical check — a silent gap in the report itself, now fixed
      (`details.verification_skipped` carries the reason).

      **What the flagged claims actually were, checked by hand against the
      transcripts, not assumed:**
      - Genuine catches: specific safety-netting timeframes ("follow up in
        48-72 hours") and a cardiology-referral condition the transcript never
        stated — invented specificity, the exact failure class this phase exists
        to catch.
      - One systematic false-positive class, now fixed: "Patient is 69 years
        old" was flagged unsupported because the transcript states a date of
        birth (1957) but never says "69" aloud. The age is correctly derived
        arithmetic, not fabrication. The verifier prompt now has an explicit
        rule for values computed from stated data.
      - One residual false positive, left open rather than chased: "continue
        sertraline" was flagged despite the existing "continuing an established
        medication is supported" rule — a prompt-following miss on the model's
        part, not a bug in this codebase. Not tuned further against this one
        case, per the golden-set policy below.
- [x] **A `print()` was crashing note generation.** The Phase 3 harness surfaced
      it: a model-generated non-breaking hyphen (U+2011) raised
      `UnicodeEncodeError` from inside a diagnostic `print()` on Windows'
      cp1252 console, aborting the request — a 500 in production, and the cause
      of the two earlier partial Phase 3 runs. Fixed at the process entry
      points (`backend/console.py`, forces UTF-8 with `errors="replace"`),
      not by removing the print — a logging statement must never be able to
      destroy the work it is describing.
- [ ] Retire `hallucination_rate` as a headline once entailment has full
      coverage. Its rise to 0.518 in the partial run was scaffolding —
      `vital signs`, `physical exam`, `allergies` appearing in *absence*
      statements ("vital signs not documented"), which the lexical proxy cannot
      distinguish from fabrication. Further evidence the proxy is unfit, not a
      regression.
- [ ] Consider a paid tier or a smaller model for eval runs; four cases per day
      is not enough to evaluate against PriMock57's 57 consultations.

### Splitting the judge from the pipeline (2026-09-11)

The model access point (`groq_client.py`) is now multi-provider: Groq keeps its
native SDK, and anything OpenAI-compatible (Gemini, Cerebras) is reachable by
base URL. Callers pick a *role* — `pipeline` or `judge` — rather than a model.

Two reasons, and the second is the one that matters:

1. **Quota.** One 200,000 token/day tier serving both note generation and
   evaluation is why measurement has stalled twice. The judge can now spend a
   different provider's budget.
2. **Self-assessment.** The judge and the generator were the same model, so the
   grader carried whatever blind spot produced the note. That inflates agreement
   for reasons unrelated to note quality. This is a methodology fix that happens
   to also solve a budget problem, not the other way round.

The pipeline stays on Groq `openai/gpt-oss-120b` deliberately. Every committed
baseline in `eval/results/` was generated by it, and changing the generating
model invalidates every before/after comparison in this file. That is a
re-baselining decision to take on purpose, not a default to drift into.

**Found while doing it: the judge's default model did not exist.**
`EVAL_JUDGE_MODEL` defaulted to `llama-3.3-70b-versatile` — the same
decommissioned model that once silently disabled the whole LLM path. Groq's live
model list confirms it is gone. Any judge run without an explicit override was
404ing. The judge also held its own client, so it bypassed the retry
classification and the token accounting every other call gets; it now goes
through `chat_json` like everything else.

`scripts/check_model_access.py` exists so that class of bug fails loudly: it
lists what each provider actually offers and makes one tiny call per role. A
configured model name is a claim about the world, and it is now checkable
before a four-hour run depends on it.

**The judge is Gemini `gemini-3.5-flash-lite`**, against the pipeline's Groq
`openai/gpt-oss-120b`. Pinned deliberately — not `gemini-flash-latest`, not a
`-preview`. A judge whose model moves underneath it makes scores from different
runs incomparable, and a preview is a deprecation waiting to happen, which is
the failure this project already had once.

It took four attempts, and the reasons are worth keeping because none of them
are documented:

- `gemini-3.8-flash` — the newest, and the first choice — allows **5 requests a
  minute and 20 a day**. Public write-ups claiming ~1,500/day describe other
  models. Choosing "newest and pinned" without checking quota was the wrong axis
  to optimise.
- `gemini-2.5-flash` — the fallback — **appears in `models.list` and then 404s**
  with "no longer available to new users". A model listing is not a capability
  check; only a real call is, which is what `check_model_access.py` makes.
- `gemini-3.6-flash` works, and was what Google's own 404 recommended — but it
  is **also 20 requests a day**. That switch bought nothing.
- `gemini-3.5-flash-lite` is the answer, and the account dashboard is what
  revealed it.

**The tier matters far more than the version.** Every full Flash model — 3.8,
3.7, 3.6, 3.5, 3, 2.5 — is 5 RPM / 20 RPD. The Lite tier is twenty-five times
larger:

| model | RPM | TPM | RPD |
|---|---|---|---|
| `gemini-3.5-flash-lite` | 15 | 250K | **500** |
| `gemini-3.1-flash-lite` | 15 | 250K | **500** |
| `gemma-4-26b` / `gemma-4-31b` | 30 | **16K** | 14,400 |
| any full Flash | 5 | 250K | 20 |

Gemma's 14,400 RPD is larger again, but 16K TPM is tight against ~2,200-token
judge calls.

**Lite does not judge this task worse, and that was checked rather than
assumed.** Same clinician note, same 90-item checklist: `gemini-3.6-flash`
returned 0.6966 coverage / 0.7188 critical, `gemini-3.5-flash-lite` returned
0.6854 / 0.7344 — within about a point and a half either way on identical item
counts. One case and one metric, so evidence rather than proof; if the rubric or
entailment numbers later look strange, suspect this first.

The general lesson, which cost several hours: **quota limits are account data,
not documentation.** Read them from
<https://aistudio.google.com/rate-limit>, never from a write-up.

Three things the wiring surfaced, each of which would have been a confusing
failure later:

- **The fallback was wrong as first written.** An unset `EVAL_JUDGE_MODEL`
  inherited the *pipeline's* model, so naming Gemini as the provider produced
  `provider=gemini model=openai/gpt-oss-120b` — a guaranteed 404. A model name
  does not carry across providers, so that case is now refused with a message
  naming the variable to set. The preflight caught it on its first real run.
- **Reasoning tokens are charged against `max_tokens`.** Gemini spends thinking
  budget before emitting anything and the amount varies per call, so the
  preflight's 64-token cap intermittently returned a truncated `{"` and reported
  a working model as broken. Raised to 512. Judge calls need headroom for the
  same reason. Measured cost: one judge call was 582 prompt + 347 completion but
  1,730 total — thinking roughly doubled it.
- **The retry path now covers the judge**, which it did not when the judge held
  its own client. The first verified run hit a Gemini `InternalServerError`,
  retried, and succeeded. Previously that would have surfaced as a skipped
  metric.
- **Reasoning tokens are charged against `max_tokens`,** and this is not a
  rounding error. A 90-item coverage prompt spent 2,900 of its 3,000 budget
  thinking and returned 115 tokens of truncated JSON, losing the whole metric.
  `reasoning_effort=low` is accepted by Gemini and measured byte-identical
  output at 390 tokens against 702 — so it is now sent to any provider recorded
  as supporting it, rather than to Groq alone. (`none` is a 400; `low` is the
  floor.)
- **Calls are paced rather than retried into a wall.** A per-minute quota
  refuses the retries too, since they land inside the same window. Gemini calls
  are spaced 12.5s, from the measured `quotaValue: 5`. `_RETRY_AFTER` also now
  understands Gemini's "Please retry in 51.17s" — it only matched Groq's "try
  again in", so the server's stated wait was being ignored entirely.
- **A dropped connection is retried.** `APIConnectionError` carries no status
  code and says only "Connection error.", so neither the status check nor the
  text markers caught it, and a 90-item judge prompt lost its metric to one bad
  socket.

### What a run costs, measured

The runner records `token_usage` per provider, because "will this finish inside
today's quota" was previously unanswerable. One `primock57_notes` case with
`--stages note,judge`: **6 Groq calls, 31,697 tokens**. At 200,000/day that is
**about six cases a day** — the binding limit on Phase 3 and on the coverage
metric at scale, and the thing a paid tier would actually buy.

### The coverage metric, validated end to end (2026-09-12)

It had only ever run on two consultations. It now runs, and the number that
matters is the human ceiling: scoring **the clinician's own note against their
own checklist gives 0.6966** (0.7188 on critical items) over 90 items.

That is the calibration the lexical version failed. Word overlap scored the same
kind of human reference at 0.22, which meant the metric was broken rather than
the note. A human reference scoring ~0.70 is believable — clinicians do not
document every checklist item — and it sets the usable range. **A generated
note's coverage should be read against ~0.70, not against 1.0.**

## Phase 4 — ASR

**Status: config work done and under measurement (2026-09-11); model upgrade
pending a download decision.**

Everything in this phase is measurable for free — ASR runs locally, so unlike
Phases 2 and 3 it costs no API quota.

- [x] **Every decoding setting is now an environment variable**, because each
      one is a hypothesis the harness can test rather than a constant someone
      chose. `eval/runner.py` records the settings used in each report, since a
      WER figure without them is unattributable.
- [x] **The hardcoded `INITIAL_PROMPT` is gone.** It listed "chest pain,
      palpitations, pericarditis, ECG, troponin, diabetes, HbA1c, metformin,
      thrush" — the vocabulary of the two demo recordings — and Whisper
      conditions decoding on it, so every user's audio was biased toward those
      diagnoses whatever the patient had. It is the same overfitting Phase 0
      removed from note generation, still live in the ASR stage.
- [x] **Replaced with per-request vocabulary** (`backend/decoder_vocabulary.py`):
      terms drawn from the *caller's own* previous encounters, most frequent
      first, restricted to entities an ontology actually resolved so a
      misrecognised word cannot feed itself back into the next transcription.
      Empty for a new user, which leaves the decoder unbiased — a wrong bias is
      worse than none. Only the caller's data is ever used; a test pins that one
      clinician's history cannot leak into another's.
- [x] **`word_timestamps=True`**, which gives the project its **first genuine
      confidence**: the mean per-word probability the acoustic model assigned to
      its own output, stored as `transcriptions.asr_confidence` (migration
      `20260911_0005`). Everything previously called "confidence" was either a
      hardcoded `0.0` or the validator's term-density score.
- [x] **Ablation complete** (`scripts/asr_sweep.py`, 7 variants on identical
      channels). A single combined run cannot attribute a delta, and the first
      one-channel check showed why: deletions fell *and* medical-term recall
      dropped, so at least two effects were pulling opposite ways.

      | variant | recall | term error | missed | spurious | WER |
      |---|---|---|---|---|---|
      | g — legacy prompt + VAD | 0.897 | **0.129** | 1.50 | 0.33 | **0.211** |
      | f — generic vocabulary + VAD | 0.882 | 0.137 | 1.83 | 0.17 | 0.217 |
      | d — short generic + VAD | 0.885 | 0.141 | 1.83 | 0.33 | 0.227 |
      | a — legacy, no VAD | 0.897 | 0.163 | 1.67 | 0.67 | 0.238 |
      | b — no prompt at all | 0.849 | 0.218 | 2.00 | 0.83 | 0.250 |

- [x] **VAD is a clean win** — the only change that improved both directions
      (missed 2.50 → 1.83, spurious 1.00 → 0.33).
- [x] **`condition_on_previous_text=False` was my wrong prediction.** Phase 0
      flagged it as a hallucination-loop trigger that should be off. Measured, it
      trades fewer spurious terms (0.33 → 0.17) for more misses (1.83 → 2.00) and
      a worse error rate overall. Default reverted to `True`, with the reason
      recorded so nobody re-derives the same guess.
- [x] **Removing the prompt entirely is the worst option** — highest deletions
      of any variant. Some decoder biasing genuinely helps.
- [x] **Held-out check: the legacy prompt's advantage was not real.** It led on
      the tuning channels (term error 0.129 vs 0.137), so `--offset` was added to
      the harness and both prompts were re-scored on consultations 04-10, which
      neither had seen:

      | prompt | recall | term error | missed | spurious | WER |
      |---|---|---|---|---|---|
      | legacy (names diagnoses) | 0.8923 | 0.1457 | 1.64 | 0.64 | 0.273 |
      | generic (no diagnoses) | **0.8931** | 0.1477 | 1.71 | 0.64 | 0.278 |

      The gap collapsed from 0.008 to 0.002 and the generic prompt is marginally
      ahead on recall — the two measure the same on unseen audio. Since they are
      equivalent, the one shipped is the one that cannot mislead a decoder about
      a patient it has never seen. Tuning and testing on the same channels is how
      a dev-set result gets mistaken for an improvement, and this is what the
      split was added to catch.
- [x] **Shipping configuration**: condition-neutral clinical framing as the
      base prompt, extended per request with the caller's own vocabulary, VAD
      on, `condition_on_previous_text` on, word timestamps on.
- [x] **Full 20-channel before/after recorded**
      (`eval/results/baseline-primock57-asr-phase4.json`). The result is a wash
      on quality, and that is worth stating plainly rather than dressing up:

      | metric | before | after | delta |
      |---|---|---|---|
      | `medical_term_error_rate` | 0.1705 | 0.1697 | −0.0008 |
      | `medical_term_recall` | 0.8862 | **0.8687** | **−0.0175** |
      | `wer` | 0.2713 | 0.2643 | −0.0070 |
      | `wer_fluent` | 0.2314 | 0.2268 | −0.0046 |
      | terms missed | 1.80 | 2.00 | +0.20 |
      | terms spurious | 0.65 | 0.60 | −0.05 |
      | deletions | 127.2 | 121.5 | −5.7 |
      | insertions | 14.8 | 18.5 | +3.7 |

      **Phase 4's configuration work did not make transcription better.** The
      aggregate medical-term error rate is flat, WER improves by 0.7 points, and
      recall drops 1.8 points — slightly more misses traded for slightly fewer
      spurious terms. The headline number the README quotes, medical-term
      recall, went *down*.

      The case for shipping it anyway is not a quality gain, and should not be
      presented as one. It is: an equivalent error rate, minus a decoder bias
      that pushed every recording toward two demo recordings' diagnoses and
      could not generalise to any other patient, plus word-level probabilities
      the pipeline did not have before. A real ASR improvement needs the model
      upgrade below, not decoding flags on `base.en`.

      One caveat on attribution: the "before" column is the original config
      (legacy prompt, no VAD) and the "after" is the new one (generic prompt,
      VAD), so this row compares two changes at once. The held-out test above is
      the cleaner evidence on the prompt question, and the six-channel sweep on
      VAD.
- [x] **Move off `base.en`. Shipped `small.en` on 2026-09-11.**

      ### Choosing a model

      Four checkpoints on the same three channels, same decoder settings, so the
      model is the only variable (`eval/results/baseline-asr-model-probe.json`).
      The machine is CPU-only — an i7-1355U with no CUDA — which turned out to
      matter more than disk:

      | model | disk | recall | med-term err | WER | x realtime |
      |---|---|---|---|---|---|
      | `large-v3-turbo` | 1.6 G | **0.9500** | **0.1092** | **0.1567** | 1.93 |
      | **`small.en`** | 464 M | 0.9278 | **0.1092** | 0.1924 | 1.02 |
      | `base.en` (was) | 141 M | 0.8908 | 0.1685 | 0.2301 | 0.11 |
      | `distil-small.en` | 321 M | 0.8074 | 0.2666 | 0.3108 | 0.65 |

      `small.en` ties `large-v3-turbo` on medical-term error rate at 29% of the
      disk and half the runtime. Turbo keeps a 2.2 point recall lead. At ~2x
      realtime it cannot serve an interactive upload on this hardware — a
      10-minute consultation would take 19 minutes — so the trade went to
      `small.en`.

      **The honest caveat, recorded because it would otherwise be forgotten: a
      2.2 point gap on three channels is not resolvable.** The 20-channel
      confirmation was offered and deliberately declined in favour of moving on
      to Phase 5; this is a decision taken on disk and latency with the
      measurement uncertainty understood, not a measured win over turbo. The
      README's 20-channel table still describes `base.en` and was *not* restated
      upward from three-channel numbers.

      Left undone: the 20-channel run on `small.en`, which is what would make
      any of these numbers quotable.

      ### `condition_on_previous_text` is per-model, not universal

      The Phase 4 decision to leave it on was measured on `base.en`. Carried to
      `distil-small.en` unchanged it sent the decoder into the repetition loop
      the flag is known for — recall 0.303, WER 0.761, 550 deletions a channel,
      output stuttering "Are you stop? Or should you stop?". With it off, the
      same checkpoint scored 0.807.

      Two things follow. The flag is a property of the checkpoint and any new
      model must re-check it — the distilled ones especially, their decoders
      being shallower. And `distil-small.en` was nearly written off on a number
      that was measuring a misconfiguration rather than the model; it lost on
      its own merits in the end (worse than `base.en` and 5.6x slower), but it
      very nearly lost on a bug. `scripts/asr_sweep.py --set KEY=VALUE` exists
      so decoder settings can be varied alongside the model rather than assumed
      constant across it.
- [x] Enable Silero VAD, then set `condition_on_previous_text=False` and measure.
      VAD is on. Turning conditioning off measured *worse* on `base.en` and the
      default stands — but see the per-model finding above: the answer differs by
      checkpoint, and on `distil-small.en` leaving it on was catastrophic.
- [x] Enable `word_timestamps=True` for evidence linking and real confidence.
- [x] Replace the hardcoded `INITIAL_PROMPT`, which biased every recording
      toward chest-pain and diabetes vocabulary, with condition-neutral framing
      extended per request by the caller's own vocabulary
      (`decoder_vocabulary.py`). Dynamic biasing from a stored specialty and
      medication list is still open.
- [x] Report WER and medical-term WER before and after, on PriMock57. Done for
      the Phase 4 configuration change over 20 channels; **owed for the
      `small.en` model change**, which so far has three channels behind it.
- [ ] Speaker diarization (pyannote / WhisperX) with clinician/patient roles.

## Phase 5 — The demo surface

- [ ] Evidence-linked notes: click a note sentence → highlight the transcript
      span and seek the audio. Falls out of Phases 3 and 4 nearly free.
- [ ] Per-section confidence and a "needs review" queue, from ASR word
      probabilities plus entailment scores.
- [ ] Generalised missing-information prompts: encounter-type completeness
      templates driving a clinician checklist of what was not asked.

## Phase 6 — The ML engineering proof

- [ ] LoRA fine-tune Qwen-2.5-7B or Llama-3.1-8B on ACI-Bench + MTS-Dialog;
      benchmark against the hosted model on the eval suite; publish quality,
      cost and latency together.
- [ ] Trained encounter-type classifier to replace `classify_encounter_type`,
      with a confusion matrix.
- [ ] Instrument clinician edits (store generated vs final note) as preference
      data; DPO fine-tune; report whether edit distance falls over time.
- [ ] Persist run metadata per generation — model, prompt version, temperature,
      latency, token cost. **Start this now**, it is a prerequisite for every
      comparison above.

---

## Feature backlog (competitive differentiation)

Tracked here so it does not get lost; sequenced after the model work it depends on.

- [ ] Coding suggestions (ICD-10 / SNOMED / CPT) with evidence spans, review-first — needs Phase 2.
- [ ] One encounter, many artifacts: SOAP + patient instructions at a target reading level + referral letter + SBAR handover — needs Phase 3.
- [ ] Safety layer: red-flag detection, allergy/medication contradiction checks, differential completeness — needs Phase 2.
- [ ] Local/private mode: Whisper plus a local LLM via Ollama, nothing leaving the machine.
- [ ] PHI de-identification as a toggleable stage.
- [ ] Longitudinal pull-forward from prior notes with delta detection.

---

## How to verify the current state

```bash
cd backend
python -m pytest -q                                   # 193 passing
python -m eval list                                   # suites and case counts
python -m eval run --suite local --stages note        # ~3 min, needs GROQ_API_KEY
python -m eval compare --baseline eval/results/baseline-local.json --current eval/results/<new>.json
```

## Changelog

- **2026-09-11** — ASR model moved from `base.en` to `small.en`, cutting
  medical-term error rate 0.169 → 0.109 on a three-channel comparison. Chosen
  over `large-v3-turbo`, which led on recall (0.950 vs 0.928) but costs 3.4x the
  disk and runs at ~2x realtime on a CPU-only machine. The gap between them is
  smaller than three channels can resolve and the 20-channel confirmation is
  still owed — the README was *not* restated upward on three-channel numbers.
  `condition_on_previous_text` turned out to be per-model rather than universal:
  carried unchanged to `distil-small.en` it caused a repetition loop that made a
  usable model look broken (recall 0.303 → 0.807 once turned off).
  The model client became multi-provider so the evaluation judge can run on a
  different free tier from the pipeline — which also stops the pipeline grading
  its own output. Found in the process: the judge's default model was the same
  decommissioned `llama-3.3-70b-versatile` that once silently disabled the whole
  LLM path, so every unconfigured judge run was 404ing.

- **2026-09-09** — First real ASR baseline on PriMock57: WER 0.271,
  disfluency-normalised 0.231, medical-term recall 0.886 over 20 channels.
  Audio is streamed per case and deleted (peak disk ~26 MB instead of 725 MB).
  Ontology linking added via the NLM REST APIs rather than a 1 GB local KB.
  Entity metric corrected — set semantics plus plural folding took lenient F1
  from 0.574 to 0.805 with no model change. CI added, including a schema-drift
  check that enforces the Alembic rule `DECISIONS.md` has stated since May.

- **2026-09-09** — Phase 2 assertion detection complete: medspaCy ConText,
  conversational rules, speaker-label masking, assertion-aware prompt and
  representation, persistence via migration `20260909_0002`, and assertion
  metrics. Exact assertion accuracy 0.719 → 0.813. Three more bugs the harness
  surfaced and fixed: the regression gate treated diagnostic counts as quality
  metrics, so a *fall* in hallucinated terms read as a regression; a dict
  returned where a list was expected crashed the structured extractor; and an
  unretried Groq rate limit silently downgraded a note to the rule-based
  fallback.
- **2026-09-09** — Phase 0 complete. Phase 1 harness built, first baseline
  recorded. Found and fixed three live bugs in the process: a decommissioned
  Groq model that had silently disabled the entire LLM path, JSON truncation in
  both Groq calls, and a crash in the extraction stage on non-string values.
