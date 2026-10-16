# Spec: evaluation-harness

> Auto-extracted by spec-miner. Last mined: 2026-09-17.
> Source: backend/eval/{runner,schema,datasets,audio_source,__main__}.py, backend/eval/metrics/{asr,entities,coverage,grounding,judge}.py
> Last verified: 2026-09-17 (commit 89807ef)

Scope: the offline measurement subsystem — a first-class subsystem, not a test
helper. It runs pipeline stages over reference datasets, scores them, and diffs
runs so a change can be kept or rejected on evidence.

---

### Requirement: Stages are opt-in so the expensive parts are only paid for when wanted
<!-- id: eval.runner.run_suite -->
<!-- entities: EvalCase, CaseResult, RunConfig -->
<!-- enforced: eval.runner.run_suite(), eval.runner._run_case(), eval.runner.STAGES -->

The runner SHALL support three stages — `asr` (transcribe and score against the
reference transcript), `note` (entity extraction, clinical extraction and SOAP
generation), `judge` (LLM rubric and claim entailment) — selected per run.
Offline metrics SHALL always run when their inputs exist, which is what makes
`--stages note` usable as a CI gate without network beyond generation. Heavy
model imports SHALL be deferred into the functions that need them, so a
metrics-only re-scoring run pays for neither Whisper nor scispaCy.

#### Scenario: a note-only run
- **WHEN** `--stages note` is requested
- **THEN** ASR is skipped and generation runs against the reference transcript,
  so note quality is measured independently of ASR error

#### Scenario: a text-only dataset
- **WHEN** a suite's cases have no `audio_path` or `audio_url`
- **THEN** the ASR stage is skipped for those cases rather than failing

---

### Requirement: Every metric travels with the count it was computed over
<!-- id: eval.runner.aggregate_metrics -->
<!-- entities: CaseResult -->
<!-- enforced: eval.runner.aggregate_metrics() -->

Aggregation SHALL average each metric only across cases that actually produced
it, skipping None and negative sentinel values, and SHALL emit
`{"mean": ..., "n": ...}`. An average over three cases and one over fifty must
not read the same on a report.

#### Scenario: a metric only some cases produce
<!-- test: tests/test_eval_metrics.py::test_aggregate_reports_the_count_each_mean_came_from -->
- **WHEN** only a subset of cases yields a metric
- **THEN** its `n` reflects that subset, not the suite size

#### Scenario: a case that produced nothing
<!-- test: tests/test_coverage_metric.py::test_a_failed_judgement_produces_no_metric -->
- **WHEN** a judged metric fails for a case
- **THEN** no metric is recorded rather than a zero being averaged in

---

### Requirement: Run comparison distinguishes regressions from diagnostics
<!-- id: eval.runner.compare_reports -->
<!-- entities: CaseResult -->
<!-- enforced: eval.runner.compare_reports(), eval.runner.LOWER_IS_BETTER, eval.runner.is_informational() -->

`compare_reports` SHALL compute per-metric deltas, and SHALL flag a regression
only when a metric moved the wrong way by more than `tolerance` (default 0.01),
with direction taken from `LOWER_IS_BETTER` (WER, medical-term error rate,
hallucination and omission rates, judge MAE, unsupported-claim rate). Metrics in
`INFORMATIONAL`, or ending `_predicted` / `_reference` / `_true_positives`,
SHALL NOT gate: they are raw counts that move whenever the case set changes.

#### Scenario: direction depends on the metric
<!-- test: tests/test_eval_metrics.py::test_regression_direction_depends_on_the_metric -->
- **WHEN** WER rises and coverage falls
- **THEN** both are regressions

#### Scenario: a change inside tolerance
<!-- test: tests/test_eval_metrics.py::test_small_changes_stay_inside_the_tolerance -->
- **WHEN** a metric moves by less than the tolerance
- **THEN** it is not reported as a regression

#### Scenario: different case sets
- **WHEN** baseline and current have different `case_count`
- **THEN** the report says `comparable` is false, rather than letting the deltas
  imply a like-for-like read

---

### Requirement: ASR accuracy is measured separately from medical-term accuracy
<!-- id: eval.metrics.asr.word_error_rate -->
<!-- entities: EvalCase -->
<!-- enforced: eval.metrics.asr.word_error_rate(), eval.metrics.asr.medical_term_error_rate() -->

WER SHALL report substitutions, insertions, deletions and reference word count
alongside the rate. A separate medical-term error rate SHALL ignore errors on
ordinary words and penalise dropped and invented clinical terms, because that is
the metric a change to the ASR stage is kept or rejected on.

#### Scenario: identical text
<!-- test: tests/test_eval_metrics.py::test_identical_text_scores_zero -->
- **WHEN** hypothesis equals reference
- **THEN** WER is 0

#### Scenario: each edit type counted
<!-- test: tests/test_eval_metrics.py::test_wer_counts_each_edit_type -->
- **WHEN** the hypothesis differs by substitutions, insertions and deletions
- **THEN** each is counted separately

#### Scenario: an empty reference
<!-- test: tests/test_eval_metrics.py::test_empty_reference_does_not_divide_by_zero -->
- **WHEN** the reference is empty
- **THEN** no division by zero occurs

#### Scenario: an ordinary-word error
<!-- test: tests/test_eval_metrics.py::test_medical_term_rate_ignores_errors_on_ordinary_words -->
- **WHEN** only non-clinical words are wrong
- **THEN** the medical-term error rate is unaffected

#### Scenario: a dropped or invented drug name
<!-- test: tests/test_eval_metrics.py::test_dropped_drug_name_is_penalised, tests/test_eval_metrics.py::test_invented_drug_name_is_penalised -->
- **WHEN** a drug name is missed or fabricated
- **THEN** the medical-term error rate rises and the term is named in
  `missed_and_spurious`

---

### Requirement: Entity and assertion scoring are separate measurements
<!-- id: eval.metrics.entities.entity_scores -->
<!-- entities: EvalCase, MedicalEntity -->
<!-- enforced: eval.metrics.entities.entity_scores(), eval.metrics.entities.assertion_scores() -->

Entity matching SHALL support a lenient mode ignoring the label and a strict
mode requiring the category, with NER labels folded onto reference categories.
Assertion accuracy SHALL be charged only against entities that were actually
detected, and SHALL require all three axes to agree for an exact match, naming
the axis that was wrong otherwise. Repeated mentions SHALL count as one concept,
and plurals SHALL match their singular symmetrically.

#### Scenario: lenient vs strict
<!-- test: tests/test_eval_metrics.py::test_lenient_matching_ignores_the_label, tests/test_eval_metrics.py::test_strict_matching_requires_the_category -->
- **WHEN** the text matches but the category does not
- **THEN** lenient matching counts it and strict matching does not

#### Scenario: a denial read as present
<!-- test: tests/test_eval_metrics.py::test_reading_a_denial_as_present_costs_accuracy -->
- **WHEN** a negated reference mention is predicted positive
- **THEN** assertion accuracy falls and the negation axis is named

#### Scenario: an undetected entity
<!-- test: tests/test_eval_metrics.py::test_undetected_entities_are_not_charged_to_assertion_accuracy -->
- **WHEN** an entity was never detected
- **THEN** it is not charged against assertion accuracy — that is an extraction
  miss, not an assertion error

#### Scenario: an unannotated reference
<!-- test: tests/test_eval_metrics.py::test_an_unannotated_reference_produces_no_assertion_scores -->
- **WHEN** the reference carries no assertion annotations
- **THEN** no assertion scores are produced

#### Scenario: a missed term reported once
<!-- test: tests/test_eval_metrics.py::test_a_missed_term_is_reported_once_not_per_mention -->
- **WHEN** a term is missed across several mentions
- **THEN** it is reported once

---

### Requirement: Coverage is judged semantically and split by criticality
<!-- id: eval.metrics.coverage.judged_coverage_scores -->
<!-- entities: EvalCase, SoapNote -->
<!-- enforced: eval.metrics.coverage.coverage_scores(), eval.metrics.coverage.judged_coverage_scores(), eval.metrics.coverage.ceiling_scores() -->

Coverage of human-authored checklist items SHALL be reported separately for
critical and non-critical items, because a lexical match cannot see clinical
shorthand or British/American spelling variants. Items marked irrelevant SHALL
not be scored, and malformed judge verdicts SHALL be ignored. The human ceiling
SHALL be reported under its own prefix as context, not as a target.

#### Scenario: criticality split
<!-- test: tests/test_coverage_metric.py::test_coverage_is_split_by_criticality -->
- **WHEN** a checklist mixes critical and non-critical items
- **THEN** two coverage figures are reported

#### Scenario: full coverage
<!-- test: tests/test_coverage_metric.py::test_full_coverage_scores_one -->
- **WHEN** every item is covered
- **THEN** the score is 1

#### Scenario: an empty note or checklist
<!-- test: tests/test_coverage_metric.py::test_an_empty_note_or_checklist_scores_nothing -->
- **WHEN** either side is empty
- **THEN** nothing is scored

#### Scenario: why the judge is needed
<!-- test: tests/test_coverage_metric.py::test_lexical_matching_misses_clinical_shorthand, tests/test_coverage_metric.py::test_british_and_american_spellings_match -->
- **WHEN** the note uses clinical shorthand or a different spelling convention
- **THEN** lexical matching misses it and judged matching does not

---

### Requirement: Judge scores are reported as uncalibrated unless human ratings exist
<!-- id: eval.runner._judge_agreement -->
<!-- entities: EvalCase -->
<!-- enforced: eval.runner._judge_agreement(), eval.metrics.judge.agreement(), eval.schema.EvalCase.human_score -->

Judge-to-human agreement SHALL be computed only over cases carrying a
`human_score`, and SHALL be omitted entirely when there are none. Agreement
SHALL require at least two pairs.

#### Scenario: a generous but correctly ranked judge
<!-- test: tests/test_eval_metrics.py::test_a_generous_but_correctly_ranked_judge_still_correlates -->
- **WHEN** the judge scores uniformly high but ranks cases correctly
- **THEN** correlation is preserved even though MAE is poor

#### Scenario: fewer than two pairs
<!-- test: tests/test_eval_metrics.py::test_agreement_needs_at_least_two_pairs -->
- **WHEN** only one human-rated case exists
- **THEN** no agreement figure is produced

---

### Requirement: Benchmark audio is streamed and discarded
<!-- id: eval.audio_source.local_audio -->
<!-- entities: EvalCase -->
<!-- enforced: eval.audio_source.local_audio(), eval.audio_source.download(), eval.audio_source.primock57_audio_url() -->

PriMock57 audio SHALL be fetched one file at a time over plain HTTPS from the
GitHub LFS media host — no git, no git-lfs, no local clone — and deleted as soon
as it has been transcribed, so peak disk is one recording (~26 MB) rather than
the ~1.9 GB corpus. A `cache_dir` SHALL trade that back for repeat-run speed.

#### Scenario: streamed audio
<!-- test: tests/test_eval_data_sources.py::test_streamed_audio_is_deleted_after_use -->
- **WHEN** a case is transcribed from a streamed file
- **THEN** the file is deleted afterwards

#### Scenario: an audio file that already exists locally
<!-- test: tests/test_eval_data_sources.py::test_an_existing_local_file_is_used_and_never_deleted -->
- **WHEN** `audio_path` points at an existing file
- **THEN** it is used as-is and never deleted

#### Scenario: a cached file
<!-- test: tests/test_eval_data_sources.py::test_a_cached_file_is_downloaded_once -->
- **WHEN** a cache directory is configured
- **THEN** the file is downloaded once and reused

#### Scenario: a failed download
<!-- test: tests/test_eval_data_sources.py::test_a_failed_download_leaves_no_partial_file -->
- **WHEN** the download fails midway
- **THEN** no partial file is left behind

#### Scenario: a stale LFS pointer
<!-- test: tests/test_eval_data_sources.py::test_a_stale_lfs_pointer_is_treated_as_missing -->
- **WHEN** the local file is an LFS pointer rather than audio
- **THEN** it is treated as missing

#### Scenario: neither a path nor a URL
<!-- test: tests/test_eval_data_sources.py::test_no_path_and_no_url_is_an_error -->
- **WHEN** a case names no audio source
- **THEN** an error is raised

---

### Requirement: Reference transcripts are parsed to clean, timed, speaker-labelled dialogue
<!-- id: eval.textgrid -->
<!-- entities: EvalCase -->
<!-- enforced: eval.textgrid, eval.datasets -->

TextGrid parsing SHALL drop silence intervals, carry timings and speaker per
utterance, strip uncertainty markers while keeping the words, remove
unintelligible regions entirely, join utterances in time order, and interleave
per-speaker channels by start time into speaker-labelled dialogue.

#### Scenario: silence and unintelligible regions
<!-- test: tests/test_eval_data_sources.py::test_silence_intervals_are_dropped, tests/test_eval_data_sources.py::test_unintelligible_regions_are_removed_entirely -->
- **WHEN** the TextGrid contains silence or unintelligible markers
- **THEN** neither reaches the reference transcript

#### Scenario: uncertainty markers
<!-- test: tests/test_eval_data_sources.py::test_unsure_markers_are_stripped_but_the_words_are_kept -->
- **WHEN** a word is marked unsure
- **THEN** the marker is stripped and the word kept

#### Scenario: two channels merged
<!-- test: tests/test_eval_data_sources.py::test_merging_channels_interleaves_by_start_time, tests/test_eval_data_sources.py::test_merged_dialogue_is_speaker_labelled -->
- **WHEN** per-speaker channels are merged
- **THEN** utterances interleave by start time and carry speaker labels

---

### Requirement: Runs are reported to disk with the decoder settings that produced them
<!-- id: eval.runner.save_report -->
<!-- entities: CaseResult -->
<!-- enforced: eval.runner.save_report(), eval.runner.asr_config() -->

Reports SHALL be written to `eval/results/` as
`{UTC timestamp}_{label or suite}.json`, carrying the aggregate metrics, the
case count and the ASR decoding settings the run used.

#### Scenario: a completed run
- **WHEN** `run_suite` finishes
- **THEN** a timestamped JSON report exists under `eval/results/`

---

### Invariant: The judge runs off-provider so the pipeline cannot grade itself
<!-- entities: Provider -->
<!-- enforced: eval.metrics.judge (role="judge"), eval.metrics.coverage (role="judge"), groq_client.JUDGE_PROVIDER -->
<!-- verified_by: tests/test_groq_client.py::test_a_judge_on_another_provider_needs_its_own_model -->

Every judged metric SHALL call `chat_json(..., role="judge")`. Scoring a model's
output with that same model is self-assessment: whatever blind spot produced a
bad note is present in the grader that reads it. Splitting the roles also lifts
the single 200,000-token/day free-tier ceiling that has blocked measurement
twice. `scripts/check_model_access.py` reports when the two providers coincide.

> Last verified: 2026-09-17 (commit 89807ef)

---

### Invariant: A judge model must be pinned
<!-- entities: Provider -->
<!-- enforced: groq_client.JUDGE_MODEL -->

`EVAL_JUDGE_MODEL` SHALL name a pinned model — no `-latest`, no `-preview` — or
scores stop being comparable across runs.

> Last verified: 2026-09-17 (commit 89807ef)

---

### Invariant: Every field of EvalCase except case_id is optional
<!-- entities: EvalCase -->
<!-- enforced: eval.schema.EvalCase -->
<!-- verified_by: tests/test_eval_metrics.py::test_the_shipped_golden_set_parses -->

Public datasets carry different ground truth — PriMock57 has audio, transcript
and note; ACI-Bench has dialogue and note but no audio; MTS-Dialog has dialogue
and a single section. Metrics that need a reference SHALL skip cases lacking
one, and the report SHALL record how many cases each metric was computed over.

> Last verified: 2026-09-17 (commit 89807ef)

---

### Invariant: Every decoding knob is a hypothesis the harness can test
<!-- entities: EvalCase -->
<!-- enforced: transcription (env vars), eval.runner.asr_config() -->

Every ASR setting is an environment variable precisely so
`python -m eval run --suite primock57 --stages asr` can evaluate it. A change is
kept only if it moves `medical_term_recall` on real consultation audio, and
confirmed on cases it was not tuned on (`RunConfig.offset` exists for this).

> Last verified: 2026-09-17 (commit 89807ef)

---

<!-- uncertainty: The 55 committed reports in eval/results/ were all produced by GROQ_MODEL on Groq. Their comparability is an external constraint on the model-access capability, not something the harness enforces in code. -->
<!-- deferred: eval/datasets.py (SUITES registry), eval/primock_checklists.py, eval/golden_from_checklists.py, eval/__main__.py (CLI argument contract), eval/metrics/grounding.py -->
