# Spec: transcription

> Auto-extracted by spec-miner. Last mined: 2026-09-17.
> Source: backend/transcription.py, backend/decoder_vocabulary.py, backend/main.py (stage 1), backend/spell_correction.py
> Last verified: 2026-09-17 (commit 89807ef)

Scope: local Whisper speech recognition, per-user decoder biasing, the
word-probability confidence it emits, and the disabled-by-default transcript
normalisation step that follows it.

---

### Requirement: Audio is transcribed by a local Whisper backend
<!-- id: transcription.transcribe_audio -->
<!-- entities: Transcription -->
<!-- enforced: transcription.transcribe_audio() -->
<!-- triggers: Decoding is biased by the caller's own prior encounters -->

`transcribe_audio` SHALL decode an audio file with faster-whisper when it is
installed, falling back to openai-whisper otherwise, and SHALL return a result
dict carrying `success`, `text`, `language`, `duration`, `words`, `confidence`,
`backend`, `model` and `error`. The function SHALL NOT raise: any failure is
reported as `success=False` with the exception text in `error`.

#### Scenario: decoding succeeds
- **WHEN** a readable audio file is passed
- **THEN** the returned dict has `success=True`, `error=None`, the joined
  segment text in `text`, and the decoded audio length in `duration`

#### Scenario: decoding fails
- **WHEN** the backend raises for any reason
- **THEN** the returned dict has `success=False`, `text=None`, `duration=None`,
  `confidence=None` and the exception message in `error` — no exception escapes

#### Scenario: the pipeline sees a failed decode
<!-- test: tests/test_transcribe_flow.py::test_successful_transcribe_persists_a_row (happy path only) -->
- **WHEN** `asr_result["success"]` is false inside `POST /api/transcribe`
- **THEN** `main.transcribe_audio_endpoint` raises, which the handler converts
  to HTTP 500 with a generic message

---

### Requirement: Decoding is biased by the caller's own prior encounters
<!-- id: decoder_vocabulary.build_vocabulary -->
<!-- entities: User, MedicalEntity, Transcription -->
<!-- enforced: decoder_vocabulary.build_vocabulary(), decoder_vocabulary.specialty_terms(), transcription.build_initial_prompt() -->

The system SHALL build the Whisper `initial_prompt` from a condition-neutral
clinical framing plus terms drawn from the requesting clinician's own previous
encounters (ontology-linked medication and condition entities), ordered by
mention frequency and capped at `MAX_TERMS` (40) terms, of which at most 60
reach the prompt. A fixed diagnosis list SHALL NOT be used.

#### Scenario: a new clinician
<!-- test: tests/test_decoder_vocabulary.py::test_a_new_clinician_gets_no_vocabulary -->
- **WHEN** the user has no prior transcriptions
- **THEN** `build_vocabulary` returns an empty list and the decoder receives
  only the generic framing prompt

#### Scenario: terms come from the caller alone
<!-- test: tests/test_decoder_vocabulary.py::test_another_clinicians_history_never_leaks -->
- **WHEN** another user's history contains linked entities
- **THEN** those terms never appear in this caller's vocabulary

#### Scenario: frequency ordering
<!-- test: tests/test_decoder_vocabulary.py::test_frequent_terms_come_first -->
- **WHEN** one term appears in twenty encounters and another in one
- **THEN** the frequent term is ordered first

#### Scenario: only linked entities qualify
<!-- test: tests/test_decoder_vocabulary.py::test_unlinked_entities_are_excluded -->
- **WHEN** an entity has no `ontology_system`
- **THEN** it is excluded from the vocabulary

#### Scenario: the vocabulary extends rather than replaces the framing
<!-- test: tests/test_decoder_vocabulary.py::test_vocabulary_extends_the_framing_rather_than_replacing_it -->
- **WHEN** vocabulary terms are supplied to `build_initial_prompt`
- **THEN** the generic framing is retained and the terms are appended as
  "Also expect: ...", deduplicated case-insensitively, blanks dropped

#### Scenario: specialty is used only when recorded
<!-- test: tests/test_decoder_vocabulary.py::test_specialty_is_used_only_when_recorded -->
- **WHEN** the user has no `specialty`
- **THEN** `specialty_terms` returns an empty list

---

### Requirement: ASR emits a per-word acoustic confidence
<!-- id: transcription._word_confidence -->
<!-- entities: Transcription -->
<!-- enforced: transcription._word_confidence() -->

The system SHALL compute `asr_confidence` as the mean per-word probability
across all decoded segments, rounded to 4 places, and SHALL return `None` — not
zero — when no word probabilities exist.

#### Scenario: word timestamps present
- **WHEN** faster-whisper returns segments carrying word probabilities
- **THEN** `confidence` is their rounded mean

#### Scenario: no word timestamps
- **WHEN** the openai-whisper fallback path is used, or word timestamps are off
- **THEN** `confidence` is `None`, and the persisted `asr_confidence` column is
  NULL rather than 0.0

---

### Requirement: Every decoding knob is an environment variable
<!-- id: transcription.WHISPER_MODEL -->
<!-- entities: Transcription -->
<!-- enforced: transcription (module-level env reads) -->

Backend, model, compute type, beam size, VAD filter,
`condition_on_previous_text`, initial prompt and word timestamps SHALL all be
read from the environment so the evaluation harness can test each as a
hypothesis. Defaults: `faster-whisper`, `small.en`, `int8`, beam 3, VAD on,
condition-on-previous on, word timestamps on.

#### Scenario: default configuration
- **WHEN** no WHISPER_* variables are set
- **THEN** `small.en` is loaded on CPU with int8 compute and beam size 3

#### Scenario: an unavailable backend is requested
- **WHEN** `WHISPER_BACKEND=openai-whisper` and the package is not installed
- **THEN** module import raises `RuntimeError` naming the missing package

---

### Requirement: Transcript spell correction is disabled by default
<!-- id: spell_correction.correct_medical_spelling -->
<!-- entities: Transcription -->
<!-- enforced: spell_correction.SPELL_CORRECTION_ENABLED, spell_correction.correct_medical_spelling() -->

Fuzzy medical spell correction SHALL be off unless `MEDICAL_SPELL_CORRECTION`
is explicitly enabled, because measurement showed it inverts clinical meaning
(`regular` -> `irregular` 24x, `eating` -> `sweating` 11x) and tripled the
medical-term error rate on real ASR output (0.1705 -> 0.5105, 19 of 20 channels
made worse). The call signature SHALL be unchanged whether or not it is enabled.

#### Scenario: default state
<!-- test: tests/test_spell_correction.py::test_correction_is_off_by_default -->
- **WHEN** `MEDICAL_SPELL_CORRECTION` is unset
- **THEN** correction is disabled

#### Scenario: disabled pass-through
<!-- test: tests/test_spell_correction.py::test_disabled_correction_returns_the_text_untouched -->
- **WHEN** correction is disabled and a transcript is passed
- **THEN** the text is returned unchanged with an empty corrections list, and
  callers need no knowledge that it is off

#### Scenario: enabled, the documented corruption reproduces
<!-- test: tests/test_spell_correction.py::test_the_corruption_it_causes_when_enabled -->
- **WHEN** correction is explicitly enabled on correct clinical prose
- **THEN** it substitutes clinically inverted terms — the measured reason it
  ships off

---

### Invariant: The client-supplied duration hint is never authoritative
<!-- entities: Transcription -->
<!-- enforced: transcription.transcribe_audio_realtime(), main.transcribe_audio_endpoint() -->
<!-- verified_by: tests/test_transcribe_flow.py::test_short_real_audio_is_rejected_even_if_header_lies -->

The `X-Audio-Duration-Seconds` header SHALL only ever short-circuit work as a
pre-flight hint. The duration derived from the decoded audio by the ASR backend
SHALL be the value used for the authoritative minimum-duration guard and for the
persisted `duration` column.

> Last verified: 2026-09-17 (commit 89807ef)

---

### Invariant: Decoder bias never crosses user boundaries
<!-- entities: User, MedicalEntity -->
<!-- enforced: decoder_vocabulary.build_vocabulary() -->
<!-- verified_by: tests/test_decoder_vocabulary.py::test_another_clinicians_history_never_leaks -->

The vocabulary query SHALL join through `transcriptions` and filter on
`Transcription.user_id == user_id`, so no term derived from one clinician's
encounters can bias another clinician's decode.

> Last verified: 2026-09-17 (commit 89807ef)

---

<!-- uncertainty: transcription.py (329 LOC) has no dedicated test module. `transcribe_audio`, `_word_confidence` and the faster-whisper/openai-whisper backend split are exercised only indirectly through tests/test_transcribe_flow.py and tests/test_decoder_vocabulary.py (which tests build_initial_prompt). Scenarios above without a `test:` anchor have none. -->
<!-- uncertainty: The README's 20-channel ASR quality figures describe base.en and are stale for the shipped small.en, per the transcription.py module header. No requirement asserts a quality number. -->
