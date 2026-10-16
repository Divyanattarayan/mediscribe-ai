# Spec: claim-verification

> Auto-extracted by spec-miner. Last mined: 2026-09-17.
> Source: backend/claim_verification.py, backend/soap_generator.py (_validate_and_repair_soap_note, _score_soap_quality)
> Last verified: 2026-09-17 (commit 89807ef)

Scope: per-claim entailment of a generated note against its transcript,
replacing the lexical `_ungrounded_terms` proxy. The note is decomposed into
atomic assertions, each judged supported / unsupported / contradicted with a
supporting quote.

---

### Requirement: Every claim in the note is judged against the transcript
<!-- id: claim_verification.verify_note -->
<!-- entities: SoapNote, ClaimVerification, VerificationReport, Transcription -->
<!-- enforced: claim_verification.verify_note() -->
<!-- triggers: Verification results drive the note quality score -->

`verify_note` SHALL render the four sections as text, ask the model to decompose
it into atomic clinical claims, and record each with a verdict of `supported`,
`unsupported` or `contradicted` plus a verbatim transcript quote. The check is
per claim rather than per term, because a lexical check cannot see an invented
relationship between two terms that are both present.

#### Scenario: a faithful note
<!-- test: tests/test_claim_verification.py::test_a_fully_supported_note_reports_no_problems -->
- **WHEN** every claim is judged supported
- **THEN** `report.problems` is empty and `unsupported_rate` is 0.0

#### Scenario: unsupported and contradicted both count
<!-- test: tests/test_claim_verification.py::test_unsupported_and_contradicted_claims_both_count_as_problems -->
- **WHEN** the note carries claims of both kinds
- **THEN** both appear in `problems`, and `claims_contradicted` is reported
  separately in `to_dict()`

#### Scenario: problems are attributable to a section
<!-- test: tests/test_claim_verification.py::test_problems_are_grouped_by_section_for_targeted_regeneration -->
- **WHEN** problem claims name subjective/objective/assessment/plan
- **THEN** `problems_by_section()` groups them so regeneration can target the
  section that is actually wrong

#### Scenario: a claim with no recognised section
<!-- test: tests/test_claim_verification.py::test_a_claim_with_no_recognised_section_is_still_reported -->
- **WHEN** the verdict carries an empty or unknown section
- **THEN** it is grouped under `unattributed` rather than dropped

#### Scenario: malformed verdicts
<!-- test: tests/test_claim_verification.py::test_malformed_claims_are_ignored -->
- **WHEN** a raw claim is not a dict, has an empty claim text, or carries a
  verdict outside the three known values
- **THEN** it is skipped

#### Scenario: the report records what was checked
<!-- test: tests/test_claim_verification.py::test_the_report_records_what_was_checked -->
- **WHEN** `to_dict()` is called
- **THEN** it carries `ran`, `error`, `claims_total`, `claims_unsupported`,
  `claims_contradicted`, `unsupported_rate`, `problems_by_section` and
  `problem_claims`

---

### Requirement: Documentation scaffolding is skipped, not judged
<!-- id: claim_verification._VERIFICATION_PROMPT -->
<!-- entities: SoapNote, ClaimVerification -->
<!-- enforced: claim_verification._VERIFICATION_PROMPT -->

The prompt SHALL instruct the judge to skip section headings and every statement
about what the RECORD lacks — "not documented in transcript", "not elicited in
this recording", "history gaps identified", "objective findings are pending
examination". A statement that a topic was not covered is a claim about the
consultation and is true whenever the transcript indeed does not cover it.

#### Scenario: a history-gap statement
- **WHEN** the note says "smoking history not elicited in this recording"
- **THEN** it must not be marked unsupported merely because the transcript lacks
  the topic — that is precisely what the statement says

#### Scenario: a recorded negative
- **WHEN** the note says "denies chest pain"
- **THEN** it IS judged, and is supported only if the transcript shows the denial

---

### Requirement: Clinical reasoning is judged on its premises, not its conclusion
<!-- id: claim_verification._VERIFICATION_PROMPT -->
<!-- entities: SoapNote, ClaimVerification -->
<!-- enforced: claim_verification._VERIFICATION_PROMPT -->

A differential diagnosis, a proposed investigation or a planned treatment SHALL
be judged supported when the findings it rests on are in the transcript, and
SHALL NOT be judged unsupported merely because the transcript never names the
diagnosis. Continuing a medication the patient states they take is supported. A
value correctly computed from stated data — an age from a date of birth — is
supported even though the transcript never says the computed value. Hedged or
conditional wording asserts a plan, not a fact.

#### Scenario: a proposed differential
- **WHEN** the note proposes pericarditis for pleuritic pain the transcript
  describes
- **THEN** the claim is supported — the lexical proxy read exactly this as a
  hallucination

#### Scenario: a stated fact about the patient
- **WHEN** the note records a medication, measurement or history item
- **THEN** it is supported ONLY if the transcript contains it

---

### Requirement: Verification results drive the note quality score
<!-- id: soap_generator._score_soap_quality -->
<!-- entities: SoapNote, VerificationReport -->
<!-- enforced: soap_generator._score_soap_quality(), soap_generator._ISSUE_PENALTIES -->
<!-- depends_on: Every claim in the note is judged against the transcript -->

`unsupported_claims` SHALL carry the heaviest issue penalty (15), above the
`ungrounded_terms` lexical proxy (12) it replaced, because a claim the
transcript does not support is the most serious defect a note can carry.

#### Scenario: a note with unsupported claims
- **WHEN** verification flags problems in a section
- **THEN** that section's score is reduced by 15 per unsupported-claim issue,
  and the note is likely pushed below the 85.0 pass threshold

---

### Invariant: A verifier failure is not a note failure
<!-- entities: SoapNote, VerificationReport -->
<!-- enforced: claim_verification.verify_note() -->
<!-- verified_by: tests/test_claim_verification.py::test_a_model_failure_never_raises, tests/test_claim_verification.py::test_a_verifier_that_cannot_run_is_not_a_clean_bill_of_health -->

`verify_note` SHALL never raise. When it cannot run it SHALL return `ran=False`
with a populated `error`, so callers can distinguish "nothing was wrong" from
"nothing was checked" — the distinction the old lexical check could not make.
The note SHALL be returned unverified and say so, rather than being blocked or
silently treated as clean.

> Last verified: 2026-09-17 (commit 89807ef)

---

### Invariant: A verifier that returns nothing usable counts as not run
<!-- entities: VerificationReport -->
<!-- enforced: claim_verification.verify_note() -->
<!-- verified_by: tests/test_claim_verification.py::test_a_verifier_returning_nothing_usable_counts_as_not_run -->

`report.ran` SHALL be `bool(report.claims)`. A model reply that parses but
yields zero valid claims SHALL set `ran=False` with the error "verifier returned
no usable claims", never an empty clean bill of health.

> Last verified: 2026-09-17 (commit 89807ef)

---

### Invariant: Nothing is rewritten by the verifier
<!-- entities: SoapNote -->
<!-- enforced: claim_verification.verify_note() -->

The verifier SHALL only report. Unsupported claims are named and handed back to
the generator; the module SHALL NOT edit clinical prose. The predecessor repair
layer deleted any sentence matching a regex, which silently dropped true
findings.

> Last verified: 2026-09-17 (commit 89807ef)

---

### Invariant: Verification can be disabled without breaking the pipeline
<!-- entities: VerificationReport -->
<!-- enforced: claim_verification.CLAIM_VERIFICATION_ENABLED -->
<!-- verified_by: tests/test_claim_verification.py::test_verification_can_be_switched_off, tests/test_claim_verification.py::test_an_empty_note_or_transcript_is_not_verified -->

With `CLAIM_VERIFICATION=0`, or with an empty note or transcript, `verify_note`
SHALL return `ran=False` with a stated reason and make no model call. The note
is then scored by the lexical fallback.

> Last verified: 2026-09-17 (commit 89807ef)
