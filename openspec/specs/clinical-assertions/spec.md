# Spec: clinical-assertions

> Auto-extracted by spec-miner. Last mined: 2026-09-17.
> Source: backend/clinical_assertions.py, backend/entity_extraction.py (pass 3), backend/models.py
> Last verified: 2026-09-17 (commit 89807ef)

Scope: the four axes that change what a mention MEANS — negation, temporality,
experiencer, uncertainty — resolved with medspaCy ConText over the merged entity
list, and the single predicate downstream code uses to ask "is this an active
patient finding".

---

### Requirement: Assertion axes are resolved over the merged entity list
<!-- id: clinical_assertions.annotate_assertions -->
<!-- entities: MedicalEntity -->
<!-- enforced: clinical_assertions.annotate_assertions(), clinical_assertions.attach_context() -->
<!-- depends_on: Every entity carries all five assertion keys -->

ConText SHALL be invoked explicitly against the two-pass entity list rather than
left to fire during `nlp(text)` on NER entities alone, because the dictionary
scan finds most symptom mentions and those are the ones most often negated.
Entity dicts SHALL be projected onto the doc by character offset with
`alignment_mode="expand"`, and results read back by offset.

#### Scenario: a denied symptom
<!-- test: tests/test_clinical_assertions.py::test_a_denied_symptom_is_marked_negated -->
- **WHEN** the transcript says the patient denies a symptom
- **THEN** that entity has `negated=True` and `assertion_source="medspacy_context"`

#### Scenario: a relative's diagnosis
<!-- test: tests/test_clinical_assertions.py::test_a_relatives_diagnosis_is_not_the_patients -->
- **WHEN** the transcript attributes a condition to a family member
- **THEN** that entity has `experiencer="family"`

#### Scenario: conversational history phrasing
<!-- test: tests/test_clinical_assertions.py::test_conversational_history_phrasing_is_historical -->
- **WHEN** the transcript says "asthma as a child" or "years ago"
- **THEN** `temporality` is `historical`

#### Scenario: conditional safety-netting
<!-- test: tests/test_clinical_assertions.py::test_conditional_safety_netting_is_hypothetical -->
- **WHEN** the transcript says "if it comes back" or "watch out for"
- **THEN** `temporality` is `hypothetical`

#### Scenario: an unqualified mention
<!-- test: tests/test_clinical_assertions.py::test_an_unqualified_mention_stays_current_and_positive -->
- **WHEN** no ConText modifier applies
- **THEN** the mention stays `current`, un-negated, `patient`

#### Scenario: two mentions of one term
<!-- test: tests/test_clinical_assertions.py::test_two_mentions_of_one_term_are_read_independently -->
- **WHEN** the same term appears twice under different modifiers
- **THEN** each mention is resolved independently

#### Scenario: hypothetical outranks historical
- **WHEN** ConText marks a span both historical and hypothetical
- **THEN** `temporality` is `hypothetical`, because "if the chest pain returns"
  is a weaker assertion than "had chest pain"

---

### Requirement: Speaker labels are masked so negation cues still fire
<!-- id: clinical_assertions.mask_speaker_labels -->
<!-- entities: MedicalEntity -->
<!-- enforced: clinical_assertions.mask_speaker_labels() -->
<!-- triggers: Assertion axes are resolved over the merged entity list -->

`Doctor:`, `Dr:`, `Clinician:`, `Physician:`, `Nurse:`, `GP:`, `Patient:`,
`Pt:`, `Caller:`, `Interviewer:` and `Speaker N:` labels SHALL be replaced with
runs of spaces of identical length, so ConText's rules — written for dictated
prose — are not blocked by a leading label.

#### Scenario: a label before a negation
<!-- test: tests/test_clinical_assertions.py::test_a_speaker_label_no_longer_blocks_negation -->
- **WHEN** the transcript reads "Patient: No nausea."
- **THEN** the nausea mention is detected as negated

#### Scenario: offsets are preserved
<!-- test: tests/test_clinical_assertions.py::test_masking_preserves_every_character_offset -->
- **WHEN** any label is masked
- **THEN** the output string has the same length and every other character sits
  at the same index

#### Scenario: ordinary clinical prose
<!-- test: tests/test_clinical_assertions.py::test_masking_leaves_clinical_text_alone -->
- **WHEN** the text contains no speaker labels
- **THEN** it is returned unchanged

---

### Requirement: Conversational ConText rules supplement the shipped note-style rules
<!-- id: clinical_assertions._add_custom_rules -->
<!-- entities: MedicalEntity -->
<!-- enforced: clinical_assertions._add_custom_rules(), clinical_assertions._CUSTOM_RULE_SPECS -->

Custom rules SHALL be added for conversational phrasings of the same four axes,
each justifiable as a general phrasing of its axis rather than by making a
golden case pass. Adding rules SHALL NOT be fatal: a failure leaves the default
note-style rules in place.

#### Scenario: a rule that depends on tense alone is excluded
<!-- test: tests/test_clinical_assertions.py::test_past_tense_reporting_of_a_new_diagnosis_stays_current -->
- **WHEN** the transcript reads "the blood test said I had diabetes"
- **THEN** the diagnosis stays `current` — the removed "i had" rule would have
  marked an active diagnosis historical

#### Scenario: rule registration fails
- **WHEN** `ConTextRule` construction or `.add()` raises
- **THEN** the exception is caught and reported; assertion detection continues
  with default rules only

---

### Requirement: `is_active_patient_finding` is the single downstream predicate
<!-- id: clinical_assertions.is_active_patient_finding -->
<!-- entities: MedicalEntity -->
<!-- enforced: clinical_assertions.is_active_patient_finding() -->

A mention SHALL be treated as an active problem only when it is not negated, its
experiencer is `patient`, and its temporality is `current`.

#### Scenario: an unqualified mention
<!-- test: tests/test_clinical_assertions.py::test_an_unqualified_mention_is_an_active_patient_finding -->
- **WHEN** all three axes hold their defaults
- **THEN** the predicate returns True

#### Scenario: any axis qualified
<!-- test: tests/test_clinical_assertions.py::test_qualified_mentions_are_not_active_findings -->
- **WHEN** the mention is negated, or belongs to family, or is historical or
  hypothetical
- **THEN** the predicate returns False

#### Scenario: keys missing entirely
<!-- test: tests/test_clinical_assertions.py::test_missing_keys_default_to_an_active_finding -->
- **WHEN** an entity dict lacks the assertion keys
- **THEN** the defaults apply and the predicate returns True

---

### Requirement: Assertion coverage is reported, including what was never resolved
<!-- id: clinical_assertions.assertion_counts -->
<!-- entities: MedicalEntity -->
<!-- enforced: clinical_assertions.assertion_counts() -->

The summary SHALL count negated, historical, hypothetical, family, uncertain and
`unresolved`. An entity with `assertion_source` missing or equal to `"default"`
SHALL count as unresolved, because an entity that never reached assertion
detection is exactly as unverified as one ConText declined to resolve.

#### Scenario: a mixed entity list
<!-- test: tests/test_clinical_assertions.py::test_counts_summarise_each_axis -->
- **WHEN** entities span several axes
- **THEN** each axis count reflects its members and `unresolved` counts the
  default-source entities

---

### Invariant: Every entity carries all five assertion keys
<!-- entities: MedicalEntity -->
<!-- enforced: clinical_assertions.annotate_assertions(), clinical_assertions.DEFAULT_ASSERTIONS -->
<!-- verified_by: tests/test_clinical_assertions.py::test_entities_survive_a_pipeline_without_the_component -->

`annotate_assertions` SHALL write `DEFAULT_ASSERTIONS` onto every entity before
attempting resolution, so downstream code can read `negated`, `temporality`,
`experiencer`, `uncertain` and `assertion_source` without testing for presence —
whatever happens next.

> Last verified: 2026-09-17 (commit 89807ef)

---

### Invariant: A denied symptom never surfaces as a positive finding
<!-- entities: MedicalEntity, ClinicalFact -->
<!-- enforced: clinical_assertions.annotate_assertions(), clinical_facts.facts_from_entities(), clinical_facts.render_for_prompt() -->
<!-- verified_by: tests/test_clinical_assertions.py::test_a_denied_symptom_is_marked_negated, tests/test_clinical_facts.py::test_the_prompt_groups_facts_by_what_they_assert -->

The `negated` axis SHALL be carried from the entity layer through the fact table
to the generation prompt, where denied facts are rendered under a DENIED heading
instructing the model to document them as negatives only. A note asserting a
symptom the patient explicitly denied is a clinical safety defect, not a quality
one.

> Last verified: 2026-09-17 (commit 89807ef)

---

### Invariant: Entity data is never lost to an assertion failure
<!-- entities: MedicalEntity -->
<!-- enforced: clinical_assertions.annotate_assertions() -->
<!-- verified_by: tests/test_clinical_assertions.py::test_entities_survive_a_pipeline_without_the_component -->

If medspaCy is unavailable, no spans project, or ConText raises,
`annotate_assertions` SHALL return the entity list intact with defaults, and
SHALL restore `doc.ents` in a `finally` block.

> Last verified: 2026-09-17 (commit 89807ef)

---

<!-- uncertainty: Anaphoric denial ("Any chest pain?" / "No, none of that") is a known and tested LIMITATION, not a requirement — tests/test_clinical_assertions.py::test_anaphoric_denial_is_a_known_limitation asserts the current wrong behaviour. It is deliberately not specified as a Requirement here. -->
