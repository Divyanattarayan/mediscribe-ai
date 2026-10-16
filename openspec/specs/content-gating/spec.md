# Spec: content-gating

> Auto-extracted by spec-miner. Last mined: 2026-09-17.
> Source: backend/content_validator.py, backend/medical_categories.py, backend/main.py (stage 2)
> Last verified: 2026-09-17 (commit 89807ef)

Scope: the term-density gate that decides whether a transcript is clinical audio
worth documenting, the score it produces, and how a rejection terminates the
pipeline early.

---

### Requirement: Non-clinical audio is rejected before any note is generated
<!-- id: content_validator.validate_medical_content -->
<!-- entities: Transcription -->
<!-- enforced: content_validator.validate_medical_content() -->
<!-- triggers: A rejected transcript ends the request without persistence -->

`validate_medical_content` SHALL return `is_valid`, a `confidence_score` in
[0,1], a human-readable `reason`, and a `details` dict carrying medical term
density, clinical marker count, consultation marker count, word count, and
repeated/top medical terms. The default thresholds are `min_density=0.08`,
`min_markers=2`, `min_word_count=50`.

#### Scenario: entertainment or interview audio
<!-- test: tests/test_content_validator.py::test_non_medical_audio_is_rejected -->
- **WHEN** a transcript has neither sufficient term density nor clinical markers
- **THEN** `is_valid` is false and the reason is
  "Non-medical content detected. Please upload clinical audio only."

#### Scenario: a dictated clinical note
<!-- test: tests/test_content_validator.py::test_dictated_clinical_note_passes -->
- **WHEN** density >= `min_density` and markers >= `min_markers`
- **THEN** `is_valid` is true (the standard pass)

#### Scenario: empty transcript
<!-- test: tests/test_content_validator.py::test_empty_transcription_is_rejected -->
- **WHEN** the transcript is empty or whitespace
- **THEN** `is_valid` is false, `confidence_score` is 0.0, and the reason is
  "Empty transcription provided"

#### Scenario: thresholds are caller-supplied
<!-- test: tests/test_content_validator.py::test_thresholds_are_configurable -->
- **WHEN** `min_density` / `min_markers` / `min_word_count` are passed explicitly
- **THEN** the gate applies the supplied values rather than the defaults

---

### Requirement: Short clinical clips are distinguished from non-clinical audio
<!-- id: content_validator.validate_medical_content -->
<!-- entities: Transcription -->
<!-- enforced: content_validator.validate_medical_content() -->

When the transcript has fewer than `min_word_count` words, density and marker
thresholds are not meaningful. The system SHALL therefore report "too short"
rather than "non-medical" whenever any clinical signal is present — density at
75% of the threshold, or at least one clinical marker, or at least one
consultation marker, or at least one repeated medical term — and SHALL keep the
non-medical rejection path otherwise.

#### Scenario: a short but clearly clinical clip
<!-- test: tests/test_content_validator.py::test_short_clinical_clip_reads_as_too_short_not_non_medical -->
- **WHEN** the transcript is under 50 words but carries clinical signal
- **THEN** `is_valid` is false and the reason asks for a longer clinical clip,
  not for clinical audio

#### Scenario: a short clip with no clinical signal at all
- **WHEN** the transcript is under 50 words with no density, markers or repeats
- **THEN** the reason is the non-medical rejection message

---

### Requirement: Conversational consultations pass on alternative evidence
<!-- id: content_validator.validate_medical_content -->
<!-- entities: Transcription -->
<!-- enforced: content_validator.validate_medical_content() -->

Two-speaker consultation speech dilutes term density, so the gate SHALL accept a
transcript through any of four disjunctive paths: standard pass; marker-heavy
pass (markers >= max(min_markers+2, 4) and density >= 0.6x threshold);
density-heavy pass (density >= 1.25x threshold and >= 1 marker); or long-consult
pass (>= 250 words, density >= 0.5x threshold, markers >= min_markers,
consultation markers >= 2, and either >= 2 repeated terms or >= 8 distinct
terms).

#### Scenario: marker-heavy history-taking dialogue
<!-- test: tests/test_content_validator.py::test_marker_heavy_conversational_history_passes -->
- **WHEN** a conversational transcript carries four or more clinical markers and
  density at least 60% of the threshold
- **THEN** `is_valid` is true even though the standard pass would fail

---

### Requirement: Term density is measured by greedy n-gram matching with a length boost
<!-- id: content_validator.calculate_medical_term_density -->
<!-- entities: Transcription -->
<!-- enforced: content_validator.calculate_medical_term_density() -->

Density SHALL be computed over punctuation-stripped, lowercased tokens, matching
multi-word dictionary terms greedily longest-first before single words. For
transcripts over 200 words the raw density SHALL be scaled by
`min(1 + (words-200)/1000, 1.5)` and capped at 1.0, to compensate for
conversational dilution without letting non-medical content pass.

#### Scenario: a multi-word term spanning noisy punctuation
- **WHEN** the transcript contains "shortness of breath"
- **THEN** all three words count as medical, not one

#### Scenario: a long transcript
- **WHEN** the transcript exceeds 200 words
- **THEN** the raw density is scaled up, never beyond 1.5x and never above 1.0

---

### Requirement: A rejected transcript ends the request without persistence
<!-- id: main.transcribe_audio_endpoint -->
<!-- entities: Transcription, SoapNote, MedicalEntity -->
<!-- enforced: main.transcribe_audio_endpoint() -->
<!-- depends_on: Non-clinical audio is rejected before any note is generated -->

When `validate_medical_content` returns `is_valid=False`, the endpoint SHALL
return `success=False` with the transcript, the validation payload and the
rejection message, and SHALL NOT run entity extraction, clinical extraction,
fact table construction, note generation, or any database write.

#### Scenario: the gate rejects
- **WHEN** validation fails at stage 2
- **THEN** the response body carries `success: false`, the transcript, the
  validation dict and `processing_time`, and no `Transcription` row exists

---

### Invariant: medical_content_score is transcript term density, never system confidence
<!-- entities: Transcription -->
<!-- enforced: main.transcribe_audio_endpoint(), models.Transcription.medical_content_score -->

The persisted `medical_content_score` SHALL be the validator's
`confidence_score` multiplied by 100 — a property of the transcript computed
before any note exists — and SHALL NOT be conflated with `asr_confidence`, which
is the acoustic model's mean per-word probability. The column was renamed in
migration `20260911_0004` precisely because the UI was presenting it as the
system's confidence in its own output.

> Last verified: 2026-09-17 (commit 89807ef)

---

<!-- uncertainty: The four disjunctive pass paths (is_standard_pass / is_marker_heavy_pass / is_density_heavy_pass / is_long_consult_pass) have no single test asserting the boundary of each; only the standard and marker-heavy paths have anchors. The density-heavy and long-consult paths are untested. -->
<!-- uncertainty: The length-based density boost (>200 words, capped 1.5x) has no test anchor and no recorded measurement in the module header, unlike the ASR and spell-correction knobs. Its constants read as tuned rather than measured. -->
