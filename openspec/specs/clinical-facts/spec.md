# Spec: clinical-facts

> Auto-extracted by spec-miner. Last mined: 2026-09-17.
> Source: backend/clinical_facts.py, backend/main.py (stage 5), backend/soap_generator.py (_generate_with_groq)
> Last verified: 2026-09-17 (commit 89807ef)

Scope: the fact table — one row per clinical claim, each carrying the transcript
span that supports it. Two producers of differing trust: entity-derived rows
(exact, free, unverifiable-by-construction) and LLM-derived rows (richer, and
required to cite).

---

### Requirement: The fact table is built from entities first and the model second
<!-- id: clinical_facts.build_fact_table -->
<!-- entities: ClinicalFact, MedicalEntity, Transcription -->
<!-- enforced: clinical_facts.build_fact_table() -->
<!-- triggers: The generation prompt is led by the fact table -->

`build_fact_table` SHALL produce entity-derived facts unconditionally, then add
LLM-derived facts when `FACT_TABLE_LLM` is enabled and the transcript is
non-empty. The table SHALL degrade to entity facts alone — never to nothing —
when the model call fails or is switched off.

#### Scenario: the LLM pass is disabled
<!-- test: tests/test_clinical_facts.py::test_the_llm_pass_can_be_switched_off -->
- **WHEN** `use_llm=False` or `FACT_TABLE_LLM=0`
- **THEN** only entity-derived facts are returned and no model call is made

#### Scenario: the model call raises
- **WHEN** `chat_json` fails for any reason
- **THEN** the exception is caught, reported, and the entity-derived facts are
  returned

---

### Requirement: Every fact carries the transcript text that supports it
<!-- id: clinical_facts.ClinicalFact -->
<!-- entities: ClinicalFact -->
<!-- enforced: clinical_facts.facts_from_entities(), clinical_facts._sentence_around() -->

Each `ClinicalFact` SHALL carry `evidence`, `evidence_start` and `evidence_end`.
For entity-derived facts the evidence SHALL be the sentence containing the
entity's span, located by scanning outward to the nearest `.`, `?`, `!` or
newline.

#### Scenario: an entity fact
<!-- test: tests/test_clinical_facts.py::test_entity_facts_carry_the_sentence_that_supports_them -->
- **WHEN** an entity is converted to a fact
- **THEN** `evidence` is the containing sentence and the offsets index the
  transcript

#### Scenario: an entity fact needs no citation check
<!-- test: tests/test_clinical_facts.py::test_entity_facts_need_no_verification -->
- **WHEN** a fact's source is `entity`
- **THEN** `verified` is True, because its offsets came from the transcript

---

### Requirement: An LLM fact must cite the transcript to be assertable
<!-- id: clinical_facts.locate_evidence -->
<!-- entities: ClinicalFact -->
<!-- enforced: clinical_facts.locate_evidence(), clinical_facts.parse_llm_facts() -->

`locate_evidence` SHALL try exact match, then case-insensitive match, then the
best-matching sentence window by `fuzz.partial_ratio`, accepting the latter only
at or above `MIN_EVIDENCE_SIMILARITY` (88.0). A fact whose quote cannot be
located SHALL be kept with `verified=False` rather than deleted, so the failure
is inspectable.

#### Scenario: a verbatim quote
<!-- test: tests/test_clinical_facts.py::test_a_verbatim_quote_is_located_exactly -->
- **WHEN** the quote appears in the transcript exactly
- **THEN** it is located with similarity 100.0

#### Scenario: punctuation and casing drift
<!-- test: tests/test_clinical_facts.py::test_punctuation_and_casing_differences_still_match -->
- **WHEN** the model normalised punctuation or casing when quoting
- **THEN** the citation is still located — rejecting over a comma would discard
  true facts

#### Scenario: a paraphrase
<!-- test: tests/test_clinical_facts.py::test_a_paraphrase_is_not_accepted_as_a_citation -->
- **WHEN** the quote is a paraphrase rather than near-verbatim
- **THEN** it is not located

#### Scenario: an invented quote
<!-- test: tests/test_clinical_facts.py::test_an_invented_quote_is_rejected -->
- **WHEN** the quote does not occur in the transcript at all
- **THEN** the fact is marked `verified=False` and is not assertable

#### Scenario: an unverified fact is retained
<!-- test: tests/test_clinical_facts.py::test_an_unverified_fact_is_kept_for_inspection_not_deleted -->
- **WHEN** a fact fails verification
- **THEN** it remains in the table so a reviewer can see what the model claimed
  and could not support

---

### Requirement: Malformed model facts are discarded
<!-- id: clinical_facts.parse_llm_facts -->
<!-- entities: ClinicalFact -->
<!-- enforced: clinical_facts.parse_llm_facts() -->

A raw fact SHALL be dropped when it is not a dict, has an empty `value`, or
carries a `fact_type` outside `FACT_TYPES`. An out-of-range `temporality` SHALL
fall back to `current`, and any `experiencer` other than `family` SHALL become
`patient`.

#### Scenario: missing value or unknown type
<!-- test: tests/test_clinical_facts.py::test_facts_with_no_value_or_an_unknown_type_are_discarded -->
- **WHEN** a raw fact lacks a value or names an unknown type
- **THEN** it is skipped entirely

#### Scenario: an invalid temporality
<!-- test: tests/test_clinical_facts.py::test_an_out_of_range_temporality_falls_back_to_current -->
- **WHEN** temporality is not one of current/historical/hypothetical
- **THEN** it becomes `current`

---

### Requirement: Repeated mentions of one assertion collapse to one fact
<!-- id: clinical_facts.facts_from_entities -->
<!-- entities: ClinicalFact, MedicalEntity -->
<!-- enforced: clinical_facts.facts_from_entities() -->

Facts SHALL be keyed on (fact_type, lowercased value, negated, temporality,
experiencer). Repeated mentions under the same key collapse to one row; two
mentions asserting different things stay separate.

#### Scenario: four mentions of one symptom
<!-- test: tests/test_clinical_facts.py::test_repeated_mentions_of_one_assertion_collapse -->
- **WHEN** "chest pain" is said four times under the same assertion
- **THEN** the table holds one finding, not four

#### Scenario: the same term asserted differently
<!-- test: tests/test_clinical_facts.py::test_the_same_term_asserted_differently_stays_separate -->
- **WHEN** a term is denied once and raised hypothetically later
- **THEN** both rows survive

#### Scenario: a family member's condition
<!-- test: tests/test_clinical_facts.py::test_a_family_members_condition_becomes_family_history -->
- **WHEN** an entity's experiencer is `family`
- **THEN** its `fact_type` becomes `family_history`

---

### Requirement: A clinician's question loses to the patient's answer
<!-- id: clinical_facts._resolve_question_answer_pairs -->
<!-- entities: ClinicalFact -->
<!-- enforced: clinical_facts._resolve_question_answer_pairs(), clinical_facts._is_question() -->

Where the same (fact_type, value) appears in both an interrogative and a
declarative evidence sentence, only the declarative rows SHALL survive — a
question is an enquiry, not an assertion, and an un-negated fact derived from
"Any nausea?" otherwise contradicts the patient's denial. A term that is only
ever asked about SHALL be kept. Original transcript ordering SHALL be preserved.

#### Scenario: asked and answered
<!-- test: tests/test_clinical_facts.py::test_a_clinicians_question_loses_to_the_patients_answer -->
- **WHEN** the transcript reads "Any nausea? No nausea at all."
- **THEN** only the negated fact from the answer survives

#### Scenario: asked but never answered
<!-- test: tests/test_clinical_facts.py::test_a_term_only_ever_asked_about_is_kept -->
- **WHEN** a term appears only in a question
- **THEN** the fact is kept — something was raised, and dropping it silently
  would lose that

---

### Requirement: Merging prefers the entity row but keeps the model's detail
<!-- id: clinical_facts.merge_facts -->
<!-- entities: ClinicalFact -->
<!-- enforced: clinical_facts.merge_facts() -->

On a (fact_type, lowercased value) clash the entity-derived row SHALL win,
because its offsets are exact and its assertion axes were resolved by ConText
rather than by a model's self-report. The model's `detail` — onset, severity,
duration, dose — SHALL be copied onto the surviving row when it has none.

#### Scenario: both producers found the same fact
<!-- test: tests/test_clinical_facts.py::test_the_entity_row_wins_but_keeps_the_models_detail -->
- **WHEN** an entity fact and an LLM fact describe the same thing
- **THEN** the entity row survives carrying the model's detail

#### Scenario: only the model found it
<!-- test: tests/test_clinical_facts.py::test_a_fact_only_the_model_found_is_added -->
- **WHEN** an LLM fact has no entity counterpart
- **THEN** it is appended to the table

---

### Requirement: The generation prompt is grouped by what each fact asserts
<!-- id: clinical_facts.render_for_prompt -->
<!-- entities: ClinicalFact -->
<!-- enforced: clinical_facts.render_for_prompt() -->
<!-- triggers: The generation prompt is led by the fact table -->

`render_for_prompt` SHALL bucket assertable facts into PRESENT, DENIED,
HISTORICAL, FAMILY, HYPOTHETICAL and UNCERTAIN under headings that state what
may be documented from each, and SHALL include each fact's evidence (truncated
to 160 characters) and ontology code where present.

#### Scenario: mixed assertions
<!-- test: tests/test_clinical_facts.py::test_the_prompt_groups_facts_by_what_they_assert -->
- **WHEN** the table spans several assertion states
- **THEN** each fact appears under the heading matching its assertion, with
  DENIED explicitly instructing "document as negatives only"

#### Scenario: unverified facts
<!-- test: tests/test_clinical_facts.py::test_unverified_facts_are_excluded_from_the_prompt -->
- **WHEN** a fact has `verified=False`
- **THEN** it does not appear in the rendered prompt

#### Scenario: an empty table
<!-- test: tests/test_clinical_facts.py::test_rendering_an_empty_table_says_so -->
- **WHEN** there are no facts
- **THEN** the render is "No clinical facts extracted."

---

### Requirement: The fact table is summarised and returned to the client
<!-- id: clinical_facts.fact_table_summary -->
<!-- entities: ClinicalFact -->
<!-- enforced: clinical_facts.fact_table_summary(), clinical_facts.facts_to_json(), main.transcribe_audio_endpoint() -->

The summary SHALL report total, assertable, unverified, from_entities, from_llm,
negated and a per-type breakdown of assertable facts. The endpoint SHALL return
both `fact_table` (full rows) and `fact_table_summary`.

#### Scenario: a mixed table
<!-- test: tests/test_clinical_facts.py::test_the_summary_separates_verified_from_unverified -->
- **WHEN** the table holds verified and unverified rows
- **THEN** `assertable` and `unverified` are reported separately

---

### Invariant: Provenance exists by construction
<!-- entities: ClinicalFact, Transcription -->
<!-- enforced: clinical_facts.ClinicalFact, clinical_facts.facts_from_entities(), clinical_facts.parse_llm_facts() -->
<!-- verified_by: tests/test_clinical_facts.py::test_entity_facts_carry_the_sentence_that_supports_them, tests/test_clinical_facts.py::test_an_llm_fact_with_a_fabricated_quote_is_not_assertable -->

Every row in the fact table SHALL carry the transcript span supporting it, so a
claim in the note without a corresponding row is visibly unsupported rather than
judged after the fact. No row may be created without an `evidence` field
attempt, and `is_assertable` SHALL be exactly `verified`.

> Last verified: 2026-09-17 (commit 89807ef)

---

### Invariant: Assertion axes survive the entity-to-fact boundary
<!-- entities: ClinicalFact, MedicalEntity -->
<!-- enforced: clinical_facts.facts_from_entities() -->
<!-- verified_by: tests/test_clinical_facts.py::test_the_same_term_asserted_differently_stays_separate -->

`negated`, `temporality`, `experiencer` and `uncertain` SHALL be copied from the
entity onto the fact, defaulting from `clinical_assertions.DEFAULT_ASSERTIONS`,
so a denied symptom stays denied all the way to the note.

> Last verified: 2026-09-17 (commit 89807ef)

---

### Invariant: The fact table is never persisted
<!-- entities: ClinicalFact, Transcription -->
<!-- enforced: main.transcribe_audio_endpoint() -->

The fact table is returned in the response but has no database table — the
schema holds `transcriptions`, `medical_entities` and `soap_notes` only.
Provenance is therefore available to the caller of `POST /api/transcribe` and to
the generation prompt, but not to the history routes.

> Last verified: 2026-09-17 (commit 89807ef)

---

<!-- uncertainty: The above invariant records observed behaviour, not a documented decision — context/DECISIONS.md was not read for this capability. Whether the fact table's non-persistence is deliberate or a gap is undetermined from code alone. -->
