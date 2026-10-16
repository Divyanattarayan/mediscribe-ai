# Spec: ontology-linking

> Auto-extracted by spec-miner. Last mined: 2026-09-17.
> Source: backend/ontology.py, backend/models.py (MedicalEntity ontology columns)
> Last verified: 2026-09-17 (commit 89807ef)

Scope: normalising entity strings to standard clinical codes via the NLM's
public REST services — RxNorm for medications (a resolution), ICD-10-CM for
conditions (a ranked suggestion) — plus the on-disk cache and the
best-effort failure contract.

---

### Requirement: A medication name resolves to a single RxNorm concept
<!-- id: ontology.lookup_medication -->
<!-- entities: MedicalEntity -->
<!-- enforced: ontology.lookup_medication() -->

`lookup_medication` SHALL try RxNav's exact-name endpoint first and, on a miss,
fall back to the approximate matcher. An approximate candidate SHALL be accepted
only when rapidfuzz string similarity between the normalised query and the
candidate name is at least `MIN_NAME_SIMILARITY` (default 80) — RxNav's own
score is on an opaque scale and cannot be thresholded directly.

#### Scenario: an exact formulary spelling
<!-- test: tests/test_ontology.py::test_an_exact_drug_name_resolves_to_one_rxcui -->
- **WHEN** the drug name matches RxNav exactly
- **THEN** the result is `{system: RXNORM, match: "exact", score: 100.0}` with
  the rxcui as `code`

#### Scenario: an ASR-introduced misspelling
<!-- test: tests/test_ontology.py::test_a_misspelling_falls_back_to_approximate_matching -->
- **WHEN** the exact lookup misses but a named candidate scores at or above the
  similarity floor
- **THEN** the result is `match: "approximate"` carrying the measured similarity

#### Scenario: a nonsense term
<!-- test: tests/test_ontology.py::test_a_nonsense_term_matches_nothing -->
- **WHEN** no candidate reaches the similarity floor
- **THEN** `None` is returned

---

### Requirement: A condition resolves to a ranked, review-flagged ICD-10-CM shortlist
<!-- id: ontology.lookup_condition -->
<!-- entities: MedicalEntity -->
<!-- enforced: ontology.lookup_condition(), ontology._rank_icd_candidates() -->

`lookup_condition` SHALL re-rank the Clinical Tables response generic-first —
exact name match wins outright, then fewest qualifier tokens the query did not
ask for (treating "unspecified", "uncomplicated", "without", "complications",
"nos", "other", "acute", "type" as neutral markers), then shorter ICD code —
and SHALL return the top code with up to three `alternatives`, a
`total_candidates` count, and a SNOMED-backed `preferred_term` when available.

#### Scenario: the API's first candidate is too specific
<!-- test: tests/test_ontology.py::test_the_generic_code_beats_the_specific_one_the_api_returns_first -->
- **WHEN** a bare "pericarditis" returns `A39.53 Meningococcal pericarditis` first
- **THEN** the generic code is ranked above it, because coding to the specific
  one would invent a specificity the transcript never stated

#### Scenario: alternatives accompany the choice
<!-- test: tests/test_ontology.py::test_condition_results_carry_alternatives_for_review -->
- **WHEN** more than one candidate survives ranking
- **THEN** up to three alternatives are returned alongside the chosen code

#### Scenario: qualifier counting
<!-- test: tests/test_ontology.py::test_ranking_prefers_fewer_added_qualifiers -->
- **WHEN** candidates are "Mild intermittent asthma" and
  "Unspecified asthma, uncomplicated"
- **THEN** the latter ranks higher — its extra words mark the absence of a
  qualifier, not the presence of one

---

### Requirement: Lookups are cached on disk, including misses
<!-- id: ontology.link_term -->
<!-- entities: MedicalEntity -->
<!-- enforced: ontology.link_term(), ontology._load_cache(), ontology.save_cache() -->

`link_term` SHALL key the cache on `"{category}:{normalised term}"` and SHALL
store negative results too, so an out-of-vocabulary term costs one request per
process lifetime rather than one per transcript. The cache lives at
`MEDISCRIBE_ONTOLOGY_CACHE` (default `backend/.ontology_cache.json`) and SHALL
be written only when at least one entity was linked. A cache write failure
SHALL be swallowed.

#### Scenario: a repeated term
<!-- test: tests/test_ontology.py::test_repeated_terms_hit_the_cache_not_the_network -->
- **WHEN** the same term is linked twice
- **THEN** the second call makes no network request

#### Scenario: a term that resolves to nothing
<!-- test: tests/test_ontology.py::test_a_miss_is_cached_too -->
- **WHEN** a lookup returns None
- **THEN** the miss is cached and not retried

---

### Requirement: Linking is opt-out and attaches codes in place
<!-- id: ontology.link_entities -->
<!-- entities: MedicalEntity -->
<!-- enforced: ontology.link_entities(), ontology.ONTOLOGY_ENABLED -->
<!-- depends_on: A medication name resolves to a single RxNorm concept -->

`link_entities` SHALL attach an `ontology` dict to entities whose `category` is
`medication` or `condition`, leaving all other categories untouched, and SHALL
return the list unchanged when `ONTOLOGY_LINKING` is disabled.

#### Scenario: a non-linkable category
<!-- test: tests/test_ontology.py::test_uncategorised_entities_are_left_alone -->
- **WHEN** an entity's category is neither medication nor condition
- **THEN** no lookup is attempted and no `ontology` key is added

#### Scenario: linking switched off
<!-- test: tests/test_ontology.py::test_linking_can_be_switched_off -->
- **WHEN** `ONTOLOGY_LINKING=0`
- **THEN** `link_term` returns None and `link_entities` is a no-op

#### Scenario: counts split the two systems
<!-- test: tests/test_ontology.py::test_counts_separate_the_two_systems -->
- **WHEN** `ontology_counts` is called
- **THEN** it reports `linkable`, `linked`, `rxnorm` and `icd10cm` separately

---

### Invariant: An ICD-10 code is a suggestion; an RxNorm code is a resolution
<!-- entities: MedicalEntity -->
<!-- enforced: ontology.lookup_condition(), ontology.link_entities(), models.MedicalEntity.ontology_requires_review -->
<!-- verified_by: tests/test_ontology.py::test_a_non_exact_condition_match_is_flagged_for_review, tests/test_ontology.py::test_an_exact_name_match_is_not_flagged -->

Any ICD-10-CM result short of an exact normalised name match SHALL carry
`requires_review=True`, and the flag SHALL be stored on the entity row rather
than inferred from the system at read time. Mapping free text to ICD-10 is a
curated-crosswalk problem, not a string-similarity one.

> Last verified: 2026-09-17 (commit 89807ef)

---

### Invariant: Only a medication match may fill an entity confidence
<!-- entities: MedicalEntity -->
<!-- enforced: ontology.link_entities() -->
<!-- verified_by: tests/test_ontology.py::test_only_medications_receive_a_confidence -->

`confidence` SHALL be written only from an RxNorm match (score/100, capped at
1.0). Condition entities SHALL keep `confidence` at 0.0 and carry their
candidate shortlist instead, because writing a confidence from a search ranking
would claim an assurance that does not exist.

> Last verified: 2026-09-17 (commit 89807ef)

---

### Invariant: An unreachable NLM service never fails the request
<!-- entities: MedicalEntity, Transcription -->
<!-- enforced: ontology._get_json(), ontology.link_entities() -->
<!-- verified_by: tests/test_ontology.py::test_an_unreachable_service_returns_none_rather_than_raising -->

`_get_json` SHALL swallow `URLError`, `TimeoutError`, `OSError`,
`JSONDecodeError` and `ValueError` and return None, subject to a
`ONTOLOGY_TIMEOUT_SECONDS` (default 6s) timeout. An uncoded note is a worse
note; a crashed request is no note at all.

> Last verified: 2026-09-17 (commit 89807ef)

---

<!-- uncertainty: _rank_icd_candidates is explicitly documented as a heuristic that does not always land — the module header states a bare "hypertension" should code to I10 by convention and no ordering rule derives that from candidate names. No requirement asserts correct coding; requires_review is the mitigation. -->
<!-- uncertainty: The module cache is process-global and guarded by a lock only on write (`_load_cache` mutates a module global without the lock). Concurrent first-touch behaviour is unspecified. Flagged, not fixed. -->
