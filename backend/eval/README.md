# Evaluation harness

Measures the clinical pipeline rather than the web app. Everything the tests in
`backend/tests/` cover is engineering correctness; everything here is model
quality.

Run from `backend/`:

```bash
python -m eval list
python -m eval run --suite local --stages note
python -m eval run --suite primock57 --stages asr,note,judge --limit 10 --label baseline
python -m eval compare --baseline eval/results/<a>.json --current eval/results/<b>.json
```

Reports land in `eval/results/<timestamp>_<label>.json` and hold per-case output
alongside the aggregate, so a number can always be traced back to the note that
produced it.

## Stages

| stage   | what it does                                            | needs                    |
|---------|---------------------------------------------------------|--------------------------|
| `asr`   | transcribes `audio_path`, scores against the reference   | Whisper model, audio     |
| `note`  | entities → clinical representation → SOAP, then scores   | scispaCy model, GROQ key |
| `judge` | rubric scoring, claim entailment, checklist coverage      | judge provider key       |

Note quality is scored against the **reference** transcript when a case has one,
so ASR error does not get charged to the generator.

## Metrics

Offline — deterministic, no API key, safe to run in CI:

- `wer`, with substitution/deletion/insertion breakdown.
- `medical_term_error_rate` and `medical_term_recall` — error rate restricted to
  the medication/condition/procedure/symptom lexicon. A transcript can post a
  respectable WER while dropping every drug name; this is the number that
  matters clinically.
- `entity_lenient_*` and `entity_strict_*` — P/R/F1 on extracted entities, text
  only versus text *and* category. Matching is over the distinct concepts each
  side mentions, with plural forms folded onto their singular:

  - **Sets, not multisets.** References annotate a *term*; the extractor emits
    one entity per *mention*. Counting occurrences scored a transcript that says
    "headaches" three times as two false positives for finding it three times.
  - **Plural folding.** `headaches` matches `headache`. Without it a correct
    extraction was scored as both a miss and a false positive. The transform is
    applied to both sides, so it can only merge forms that should match — it is
    deliberately crude (`diabetes` becomes `diabete`) and does not need to be
    linguistically right, only symmetric.

  Reference entities record the span **as it appears in the transcript**, not
  the canonical term. Annotating "hypertension" where the patient said "high
  blood pressure" would score a normalisation step we do not claim to perform,
  and would hide the lexicon gaps we do have.
- `hallucination_rate` — clinical terms in the note that appear nowhere in the
  transcript. Lexical proxy, cheap, runs everywhere.
- `omission_rate` — clinical terms in the reference note the generated note
  dropped. Reported as `-1.0` when the case has no reference note, so it is
  never confused with a genuine zero.

### Which model judges

The judge runs on whichever provider `EVAL_JUDGE_PROVIDER` names, falling back
to the pipeline provider and model when it names none. Separating the two is
worth doing for a reason beyond quota: a model asked to grade its own output
shares whatever blind spot produced it, so agreement is inflated for reasons
that have nothing to do with note quality. `scripts/check_model_access.py`
reports when the two currently coincide, and lists the model ids each provider
actually offers — check a model name there before a long run depends on it.

Currently `gemini-3.5-flash-lite`, against the pipeline's Groq
`openai/gpt-oss-120b`.
**Pin the judge model; never point it at a `-latest` alias or a `-preview`.** A
judge whose model changes underneath it makes scores from different runs
incomparable, which is most of what a judge is for.

Everything below was measured against the live API, because none of it is in the
documentation and the public write-ups were wrong on every point:

- **Free limits are per model, per day, and account-specific.** Google does not
  publish them; they are visible at <https://aistudio.google.com/rate-limit>,
  and that dashboard is the only source worth trusting — every public write-up
  consulted while setting this up was wrong.

  The shape of it is not what you would guess. **Every full Flash model is 20
  requests a day** — 3.8, 3.7, 3.6, 3.5, 3, and 2.5 alike, all at 5 RPM. The
  Lite tier is 25 times larger:

  | model | RPM | TPM | RPD |
  |---|---|---|---|
  | `gemini-3.5-flash-lite` | 15 | 250K | **500** |
  | `gemini-3.1-flash-lite` | 15 | 250K | **500** |
  | `gemma-4-26b` / `gemma-4-31b` | 30 | **16K** | 14,400 |
  | any full Flash | 5 | 250K | 20 |

  So the model tier to reach for is Lite, not Flash, and choosing "the newest
  Flash" is choosing the same 20 requests as the oldest. Gemma's 14,400 RPD is
  larger still but its 16K TPM is tight against ~2,200-token judge calls.

  **Lite does not judge worse here, and that was checked rather than assumed.**
  Scoring the same clinician note against the same 90-item checklist:
  `gemini-3.6-flash` gave 0.6966 coverage / 0.7188 critical,
  `gemini-3.5-flash-lite` gave 0.6854 / 0.7344 — within about a point and a half
  either way, on identical item counts. One case and one metric, so it is
  evidence rather than proof; if the rubric or entailment metrics start looking
  strange, suspect this first.
- **Being listed does not mean being callable.** `gemini-2.5-flash` appears in
  `models.list` and then 404s with "no longer available to new users". Only a
  real call proves a model works, which is why `check_model_access.py` makes one.
- **Reasoning tokens come out of `max_tokens`.** Thinking is spent before any
  output and the amount varies per call, so a cap sized for the answer can still
  starve it: a 90-item coverage prompt spent 2,900 of 3,000 thinking and
  returned 115 tokens of truncated JSON. `GROQ_REASONING_EFFORT=low` is
  forwarded to Gemini and fixes it — same output, roughly half the tokens.
  (`none` is rejected with a 400.)
- **Naming a provider is not naming a model.** Setting `EVAL_JUDGE_PROVIDER`
  without `EVAL_JUDGE_MODEL` is refused rather than inherited — sending Gemini
  the pipeline's `openai/gpt-oss-120b` would simply 404.

### What a run costs

Reports carry `token_usage` and `token_usage_per_case` per provider, so this is
checkable rather than estimated. Measured on one `primock57_notes` case with
`--stages note,judge`: **6 Groq calls and 31,697 tokens**. Against a 200,000
token daily tier that is **about six cases a day**, which is the real limit on
how much of PriMock57 can be evaluated — not anything about the harness.

Online — needs the judge provider's key:

- `judge_score` — 0-100 aggregate over the rubric in `metrics/judge.py`
  (faithfulness, completeness, section discipline, clinical reasoning,
  actionability).
- `judge_hallucination_rate` — share of atomic claims the judge marks
  unsupported or contradicted, with the offending claims kept in the report.
- `judge_mae` / `judge_spearman` — agreement with `human_score` on cases that
  carry one.

Assertion metrics (offline, from the Phase 2 layer):

- `assertion_negated_accuracy`, `assertion_temporality_accuracy`,
  `assertion_experiencer_accuracy` — per-axis, over entities found in both the
  reference and the output, so a detection miss is charged to the entity
  metrics and not counted twice.
- `assertion_exact_accuracy` — all three axes right at once. The number that
  says a mention was read correctly rather than mostly correctly.

**A judge score without an agreement figure is an opinion, not a metric.** Score
20-30 cases by hand, put the scores in the case file as `human_score`, and quote
the agreement whenever the judge number is quoted.

### Which metrics are ready to gate on

Not all of them, and pretending otherwise makes the gate noise.

| metric group | deterministic? | gate-ready |
|---|---|---|
| entity P/R/F1, assertion accuracy | yes — same input, same output | **yes** |
| WER, medical-term error rate | yes | **yes** |
| `hallucination_rate`, `omission_rate` | no — generation runs at temperature 0.3 | not yet |
| judge metrics | no, and uncalibrated | not yet |

The lexical grounding rates move by several points between identical runs on
the four-case suite. That is sampling noise, not signal: use them to spot large
shifts, and grow the suite before treating a small delta as real.

Counts (`*_predicted`, `hallucinated_term_count`, `wer_substitutions`, …) are
diagnostics that explain the rates. `runner.INFORMATIONAL` excludes them from
the gate — they move whenever the case set changes and mean nothing on their
own.

## Suites

`local` is the only suite that ships with the repo. The seed cases in
`cases/golden.jsonl` are synthetic transcripts with hand-checked reference
entities and deliberately **no** reference notes — a fabricated "correct" note
would make every note-similarity number meaningless.

The public suites are not vendored: they carry their own licences, and some
require a data-use agreement.

### Where the data lives

Set `MEDISCRIBE_EVAL_DATA` to a directory **outside any cloud-synced folder**.
This repo sits under OneDrive, so the default `eval/data/` would sync every byte
to the cloud:

```bash
export MEDISCRIBE_EVAL_DATA="$LOCALAPPDATA/mediscribe-eval-data"   # Windows
```

### Audio is streamed, not stored

PriMock57 is ~1.9 GB of audio in full, and `git clone` with LFS keeps it twice —
once checked out and once in `.git/lfs/objects`. None of it needs to persist: a
WER run reads each file once, and the transcript and metrics that come out are
kilobytes.

So only the transcripts and notes are kept locally (~3 MB); audio is fetched per
case from GitHub's LFS media endpoint, transcribed, and deleted. **Peak disk is
one recording, about 26 MB.** Pass `--audio-cache DIR` to keep downloads instead
and trade disk for repeat-run speed.

Getting the transcripts without the audio:

```bash
GIT_LFS_SKIP_SMUDGE=1 git clone --depth 1 https://github.com/babylonhealth/primock57.git
rm -rf primock57/.git primock57/audio/*.wav      # ~725 MB reclaimed, nothing lost
```

| suite       | contents                                          | expected layout                                |
|-------------|---------------------------------------------------|------------------------------------------------|
| `primock57` | 57 mock primary-care consultations, doctor and patient on separate channels. The only suite that exercises ASR. | `primock57/transcripts/*.TextGrid` (audio streamed) |
| `primock57_notes` | the same consultations as merged dialogue, with the clinician's own note | `primock57/{transcripts,notes}/` |
| `aci_bench` | doctor-patient dialogue → four-section note; published baselines to compare against | `aci_bench/*.csv` with `dialogue` and `note` columns |
| `mts_dialog`| short dialogue → single clinical section; good for section-routing accuracy | `mts_dialog/*.csv` with `dialogue`, `section_header`, `section_text` |

PriMock57 is CC BY 4.0 (Babylon Health) — attribution required if you publish
results. Its transcripts use `<UNSURE>text</UNSURE>` and `<UNIN/>` tags; the
parser keeps the text inside `<UNSURE>` (the transcriber's best guess is still
the best reference available) and drops `<UNIN/>` entirely (there is no
reference text for it, so scoring against it would charge the ASR for words no
human could make out). Both choices are lossy and both are stated here so a WER
figure from this harness can be compared like for like.

Check the licence and any data-use terms for each before use, and do not commit
the data.

## Adding your own cases

Append to `cases/golden.jsonl` — one JSON object per line, `#` lines ignored:

```json
{"case_id": "clinic/2026-03-visit-01", "source": "local", "encounter_type": "follow_up",
 "reference_transcript": "...", "reference_note": {"subjective": "...", "objective": "..."},
 "reference_entities": [{"text": "amlodipine", "label": "MEDICATION"}],
 "human_score": 82}
```

Every field except `case_id` is optional; metrics skip cases that lack what they
need and report the count they were computed over.

Never commit real patient audio, transcripts, or notes.

## CI gate

```bash
python -m eval run --suite local --stages note \
  --baseline eval/results/<committed-baseline>.json --fail-on-regression
```

Exits 1 when a metric moves the wrong way by more than `--tolerance` (default
0.01). `runner.LOWER_IS_BETTER` says which direction is wrong for each metric.

## Status

Phase 1 of `context/MODEL_ROADMAP.md`. The committed baseline
(`results/baseline-local.json`) covers the four local synthetic cases only.

The public suites have **not** been run yet: PriMock57, ACI-Bench and MTS-Dialog
still need downloading, and until they are, there is no WER number and no
note-quality number comparable to published work. Four synthetic cases is enough
to catch a regression; it is not enough to make a claim.
