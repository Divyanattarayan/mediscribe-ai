# Spec: entity-extraction

> Auto-extracted by spec-miner. Last mined: 2026-09-17.
> Source: backend/entity_extraction.py, backend/medical_categories.py, backend/main.py (stage 3)
> Last verified: 2026-09-17 (commit 89807ef)

Scope: the four-pass mention detector — spaCy `en_ner_bc5cdr_md` NER, a
dictionary second pass, assertion annotation, ontology linking — and the
categorised entity payload it hands to every downstream stage.

---

### Requirement: Entities are extracted in four ordered passes
<!-- id: entity_extraction.extract_medical_entities -->
<!-- entities: MedicalEntity, Transcription -->
<!-- enforced: entity_extraction.extract_medical_entities() -->
<!-- triggers: Assertion axes are resolved over the merged entity list -->

`extract_medical_entities` SHALL run, in order: (1) NER over speaker-masked text
producing CHEMICAL/DISEASE mentions, with adjacent-entity merging; (2) a
dictionary scan for SYMPTOM, CONDITION, MEDICATION, TEST and PROCEDURE terms;
(3) assertion annotation over the merged list; (4) ontology linking, which runs
after categorisation because the lookup is chosen by category. It SHALL return
`entities`, `categorized`, `category_counts`, `assertion_counts`,
`ontology_counts` and `total_entities`.

#### Scenario: a clinical transcript
- **WHEN** a valid clinical transcript is passed
- **THEN** the result has `success=True` and every entity dict carries `text`,
  `label`, `start`, `end`, the five assertion keys, and a `category`

#### Scenario: extraction raises
- **WHEN** any pass raises
- **THEN** the result is `success=False` with `error` set and empty entity,
  categorized and count collections — the pipeline is not taken down

---

### Requirement: Entity text and offsets always index the original transcript
<!-- id: entity_extraction.extract_medical_entities -->
<!-- entities: MedicalEntity -->
<!-- enforced: entity_extraction.extract_medical_entities(), clinical_assertions.mask_speaker_labels() -->

NER SHALL be run over `mask_speaker_labels(text)`, which replaces `Doctor:` /
`Patient:` style labels with equal-length runs of spaces. Entity `text` SHALL
always be sliced from the original, unmasked transcript, and every `start`/`end`
offset SHALL remain valid against it.

#### Scenario: a speaker-labelled dialogue
<!-- test: tests/test_clinical_assertions.py::test_masking_preserves_every_character_offset -->
- **WHEN** the transcript contains "Patient: No nausea."
- **THEN** masking preserves the string length, so entity offsets, the
  dictionary scan and the persisted `start`/`end` columns all still point at the
  correct characters

---

### Requirement: A dictionary second pass recovers what the NER model cannot label
<!-- id: entity_extraction.dictionary_scan -->
<!-- entities: MedicalEntity -->
<!-- enforced: entity_extraction.dictionary_scan() -->

Because `en_ner_bc5cdr_md` emits only CHEMICAL and DISEASE, the system SHALL
scan the transcript directly against SYMPTOMS, CONDITIONS, MEDICATIONS,
TEST_TERMS and PROCEDURE_TERMS. Matches SHALL respect whole-word/phrase
boundaries and SHALL be skipped where they overlap a character range already
covered by an earlier entity, so nothing is double-counted.

#### Scenario: a symptom the NER model missed
- **WHEN** "chest pain" appears and was not tagged by NER
- **THEN** it is added as a SYMPTOM entity with transcript offsets

#### Scenario: a term already tagged by NER
- **WHEN** "chest pain" was already tagged DISEASE
- **THEN** the dictionary scan does not re-add it as SYMPTOM

#### Scenario: a substring that is not a word boundary
- **WHEN** a dictionary term occurs inside a longer alphanumeric word
- **THEN** it is not matched

---

### Requirement: Adjacent NER entities merge only into exact dictionary terms
<!-- id: entity_extraction.merge_adjacent_entities_dynamic -->
<!-- entities: MedicalEntity -->
<!-- enforced: entity_extraction.merge_adjacent_entities_dynamic(), entity_extraction.is_exact_medical_term() -->

Two adjacent entities separated by no more than 5 characters SHALL merge when
the spanning text is an exact dictionary match and categorises as symptom,
medication, condition, procedure, anatomical or modifier. A span containing a
sentence terminator (`.`, `!`, `?`) SHALL NOT merge.

#### Scenario: a compound term split by the model
- **WHEN** "shortness" and "breath" are adjacent and the span reads
  "shortness of breath"
- **THEN** one merged entity replaces both

#### Scenario: a sentence boundary between them
- **WHEN** the spanning text contains a full stop
- **THEN** no merge occurs

---

### Requirement: Known conversational false positives are filtered out
<!-- id: entity_extraction.filter_contextual_false_positives -->
<!-- entities: MedicalEntity -->
<!-- enforced: entity_extraction.filter_contextual_false_positives() -->

The system SHALL drop entities whose text is "hi" or "hello", and SHALL drop
"surgery" when the preceding 10 characters of context read "gp surgery" — a
British premises name, not a procedure.

#### Scenario: a greeting tagged as an entity
- **WHEN** an entity's text is "hi"
- **THEN** it is removed before categorisation

#### Scenario: GP surgery
- **WHEN** "surgery" is preceded by "gp "
- **THEN** it is removed

---

### Requirement: Entities are persisted with their full assertion and ontology state
<!-- id: main.transcribe_audio_endpoint -->
<!-- entities: MedicalEntity, Transcription -->
<!-- enforced: main.transcribe_audio_endpoint() -->

For each extracted entity the endpoint SHALL write a `medical_entities` row
carrying text, label, confidence, start, end, the four assertion axes plus
`assertion_source`, and the four ontology columns, defaulting missing values to
`negated=False`, `temporality="current"`, `experiencer="patient"`,
`uncertain=False`, `assertion_source="default"`,
`ontology_requires_review=False`.

#### Scenario: a successful pipeline run
<!-- test: tests/test_transcribe_flow.py::test_successful_transcribe_persists_a_row -->
- **WHEN** the pipeline completes
- **THEN** entity rows exist linked to the transcription, each carrying its
  assertion axes and any ontology code

---

### Invariant: Ontology linking runs after categorisation, never before
<!-- entities: MedicalEntity -->
<!-- enforced: entity_extraction.extract_medical_entities(), ontology.link_entities() -->

`link_entities` dispatches on `entity["category"]`, which only exists after
`categorize_entities` has run. The ordering NER -> dictionary -> assertions ->
categorisation -> ontology SHALL be preserved.

> Last verified: 2026-09-17 (commit 89807ef)

---

### Invariant: Entity extraction degrades rather than fails
<!-- entities: MedicalEntity -->
<!-- enforced: entity_extraction.extract_medical_entities(), ontology.link_entities(), clinical_assertions.annotate_assertions() -->

A missing medspaCy install, an unreachable NLM service, or an internal error in
any pass SHALL leave entities unannotated or unlinked and visible in the
`assertion_counts` / `ontology_counts` summaries, rather than raising into the
request.

> Last verified: 2026-09-17 (commit 89807ef)

---

<!-- uncertainty: entity_extraction.py (399 LOC) has NO dedicated test module. Every scenario above without a `test:` anchor is unanchored: dictionary_scan, merge_adjacent_entities_dynamic, filter_contextual_false_positives and the four-pass orchestration are covered only by the module's own `__main__` smoke block and indirectly via tests/test_clinical_assertions.py and tests/test_transcribe_flow.py. -->
<!-- uncertainty: `is_valid_medical_term` performs substring matching in both directions (`text_lower in term or term in text_lower`), which will return True for very short strings against any containing term. It appears unused by extract_medical_entities; only `is_exact_medical_term` is called. Flagged, not fixed. -->
<!-- deferred: medical_categories.py (568 LOC, vocabulary data — categorize_entity/categorize_entities behaviour not mined) -->
