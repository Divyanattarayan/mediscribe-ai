"""Offline metric tests for the evaluation harness.

These deliberately avoid the network and the ML models: the metrics are the
instrument we judge every future model change with, so they have to be
trustworthy on their own before any number they produce means anything.
"""

from eval.metrics import asr, entities, grounding
from eval.metrics.judge import agreement
from eval.runner import CaseResult, aggregate_metrics, compare_reports
from eval.schema import EvalCase, load_cases


# ── Word error rate ───────────────────────────────────────────────────────────

def test_identical_text_scores_zero():
    assert asr.word_error_rate("the patient reports chest pain", "The patient reports chest pain.").wer == 0.0


def test_wer_counts_each_edit_type():
    result = asr.word_error_rate("patient reports chest pain", "patient reported chest")
    assert (result.substitutions, result.deletions, result.insertions) == (1, 1, 0)
    assert result.wer == 0.5           # two edits over four reference words


def test_empty_reference_does_not_divide_by_zero():
    assert asr.word_error_rate("", "").wer == 0.0
    assert asr.word_error_rate("", "unexpected speech").wer == 1.0


# ── Medical-term error rate ───────────────────────────────────────────────────

def test_medical_term_rate_ignores_errors_on_ordinary_words():
    """The clinical content survived, so the medical-term rate stays clean even
    though the overall WER is not."""
    reference = "the patient has been taking metformin for the diabetes"
    hypothesis = "so patient was taking metformin for that diabetes"
    assert asr.word_error_rate(reference, hypothesis).wer > 0
    assert asr.medical_term_error_rate(reference, hypothesis)["medical_term_error_rate"] == 0.0


def test_dropped_drug_name_is_penalised():
    scores = asr.medical_term_error_rate(
        "started on metformin and atorvastatin", "started on metformin"
    )
    assert scores["medical_terms_missed"] == 1.0
    assert scores["medical_term_recall"] == 0.5


def test_invented_drug_name_is_penalised():
    scores = asr.medical_term_error_rate("started on metformin", "started on metformin and insulin")
    assert scores["medical_terms_spurious"] == 1.0
    assert scores["medical_term_error_rate"] > 0


# ── Entity scoring ────────────────────────────────────────────────────────────

def _entity(text, label):
    return {"text": text, "label": label}


def test_lenient_matching_ignores_the_label():
    reference = [_entity("chest pain", "SYMPTOM")]
    hypothesis = [_entity("Chest pain", "DISEASE")]
    assert entities.entity_scores(reference, hypothesis)["entity_lenient_f1"] == 1.0


def test_strict_matching_requires_the_category():
    reference = [_entity("chest pain", "SYMPTOM")]
    hypothesis = [_entity("chest pain", "DISEASE")]
    assert entities.entity_scores(reference, hypothesis, strict=True)["entity_strict_f1"] == 0.0


def test_ner_labels_fold_onto_reference_categories():
    """CHEMICAL is how the model says MEDICATION; that must not read as an error."""
    reference = [_entity("aspirin", "MEDICATION")]
    hypothesis = [_entity("aspirin", "CHEMICAL")]
    assert entities.entity_scores(reference, hypothesis, strict=True)["entity_strict_f1"] == 1.0


def test_missed_and_spurious_name_the_terms():
    detail = entities.missed_and_spurious(
        [_entity("chest pain", "SYMPTOM"), _entity("aspirin", "MEDICATION")],
        [_entity("aspirin", "CHEMICAL"), _entity("insulin", "CHEMICAL")],
    )
    assert detail["missed"] == ["chest pain"]
    assert detail["spurious"] == ["insulin"]


# ── Grounding ─────────────────────────────────────────────────────────────────

TRANSCRIPT = "the patient describes chest pain and takes amlodipine every morning"


def test_a_faithful_note_has_no_hallucinations():
    note = {"assessment": "Chest pain under investigation.", "plan": "Continue amlodipine."}
    assert grounding.grounding_scores(note, TRANSCRIPT)["hallucination_rate"] == 0.0


def test_a_drug_absent_from_the_transcript_is_flagged():
    note = {"plan": "Start metformin and continue amlodipine."}
    scores = grounding.grounding_scores(note, TRANSCRIPT)
    assert scores["hallucinated_term_count"] == 1.0
    assert grounding.grounding_details(note, TRANSCRIPT)["hallucinated"] == ["metformin"]


def test_omission_is_only_reported_against_a_reference_note():
    note = {"plan": "Continue amlodipine."}
    assert grounding.grounding_scores(note, TRANSCRIPT)["omission_rate"] == -1.0

    with_reference = grounding.grounding_scores(
        note, TRANSCRIPT, {"assessment": "Chest pain.", "plan": "Continue amlodipine."}
    )
    assert with_reference["omission_rate"] == 0.5     # "chest pain" dropped


# ── Aggregation, comparison, judge agreement ──────────────────────────────────

def test_aggregate_reports_the_count_each_mean_came_from():
    results = [
        CaseResult(case_id="a", source="s", metrics={"wer": 0.2, "omission_rate": -1.0}),
        CaseResult(case_id="b", source="s", metrics={"wer": 0.4}),
    ]
    aggregate = aggregate_metrics(results)
    assert aggregate["wer"] == {"mean": 0.3, "n": 2}
    assert "omission_rate" not in aggregate        # sentinel, not a real zero


def test_regression_direction_depends_on_the_metric():
    baseline = {"aggregate": {"wer": {"mean": 0.20, "n": 5}, "entity_lenient_f1": {"mean": 0.80, "n": 5}}}
    worse = {"aggregate": {"wer": {"mean": 0.30, "n": 5}, "entity_lenient_f1": {"mean": 0.60, "n": 5}}}
    assert set(compare_reports(baseline, worse)["regressions"]) == {"wer", "entity_lenient_f1"}

    better = {"aggregate": {"wer": {"mean": 0.10, "n": 5}, "entity_lenient_f1": {"mean": 0.90, "n": 5}}}
    assert compare_reports(baseline, better)["regressions"] == []


def test_small_changes_stay_inside_the_tolerance():
    baseline = {"aggregate": {"wer": {"mean": 0.20, "n": 5}}}
    current = {"aggregate": {"wer": {"mean": 0.205, "n": 5}}}
    assert compare_reports(baseline, current, tolerance=0.01)["regressions"] == []


def test_a_generous_but_correctly_ranked_judge_still_correlates():
    judged = [70.0, 80.0, 90.0]
    human = [60.0, 70.0, 80.0]
    scores = agreement(judged, human)
    assert scores["judge_spearman"] == 1.0
    assert scores["judge_mae"] == 10.0


def test_agreement_needs_at_least_two_pairs():
    assert agreement([80.0], [70.0])["judge_spearman"] == -2.0   # sentinel


# ── Case file ─────────────────────────────────────────────────────────────────

def test_the_shipped_golden_set_parses():
    from pathlib import Path

    cases = load_cases(Path(__file__).resolve().parent.parent / "eval" / "cases" / "golden.jsonl")
    assert len(cases) >= 4
    assert all(isinstance(case, EvalCase) and case.case_id and case.reference_transcript for case in cases)
    # Seed cases carry entities but deliberately no fabricated reference note.
    assert all(case.reference_entities for case in cases)
    assert all(case.reference_note is None for case in cases)
    # Assertion annotations are what the Phase 2 layer is scored against.
    annotated = [
        entity
        for case in cases
        for entity in case.reference_entities
        if "negated" in entity
    ]
    assert len(annotated) >= 20
    assert any(entity["negated"] for entity in annotated)
    assert any(entity["experiencer"] == "family" for entity in annotated)
    assert any(entity["temporality"] == "historical" for entity in annotated)


# ── Assertion accuracy ────────────────────────────────────────────────────────

def _asserted(text, negated=False, temporality="current", experiencer="patient"):
    return {"text": text, "label": "SYMPTOM", "negated": negated,
            "temporality": temporality, "experiencer": experiencer}


def test_reading_a_denial_as_present_costs_accuracy():
    reference = [_asserted("chest pain", negated=True)]
    hypothesis = [_asserted("chest pain", negated=False)]
    scores = entities.assertion_scores(reference, hypothesis)
    assert scores["assertion_negated_accuracy"] == 0.0
    assert scores["assertion_exact_accuracy"] == 0.0


def test_all_three_axes_must_agree_for_an_exact_match():
    reference = [_asserted("heart attack", experiencer="family", temporality="historical")]
    hypothesis = [_asserted("heart attack", experiencer="family", temporality="current")]
    scores = entities.assertion_scores(reference, hypothesis)
    assert scores["assertion_experiencer_accuracy"] == 1.0
    assert scores["assertion_temporality_accuracy"] == 0.0
    assert scores["assertion_exact_accuracy"] == 0.0


def test_a_correct_reading_scores_one():
    reference = [_asserted("nausea", negated=True), _asserted("asthma", temporality="historical")]
    scores = entities.assertion_scores(reference, list(reference))
    assert scores["assertion_exact_accuracy"] == 1.0
    assert scores["assertion_matched_entities"] == 2.0


def test_undetected_entities_are_not_charged_to_assertion_accuracy():
    """A miss is a recall failure; charging it here would double-count it."""
    reference = [_asserted("nausea", negated=True), _asserted("never extracted")]
    hypothesis = [_asserted("nausea", negated=True)]
    scores = entities.assertion_scores(reference, hypothesis)
    assert scores["assertion_matched_entities"] == 1.0
    assert scores["assertion_exact_accuracy"] == 1.0


def test_an_unannotated_reference_produces_no_assertion_scores():
    """Otherwise every axis would trivially match its default and report 100%."""
    assert entities.assertion_scores([{"text": "chest pain"}], [_asserted("chest pain")]) == {}


def test_assertion_errors_name_the_axis_that_was_wrong():
    errors = entities.assertion_errors(
        [_asserted("chest pain", negated=True)], [_asserted("chest pain")]
    )
    assert errors[0]["text"] == "chest pain"
    assert errors[0]["axes"]["negated"] == {"expected": True, "actual": False}


# ── Entity matching semantics ─────────────────────────────────────────────────

def test_repeated_mentions_are_one_concept():
    """A transcript that says "headaches" three times does not make the
    extractor three times wrong for finding it three times."""
    reference = [_entity("headache", "SYMPTOM")]
    hypothesis = [_entity("headaches", "SYMPTOM")] * 3
    assert entities.entity_scores(reference, hypothesis)["entity_lenient_precision"] == 1.0


def test_plurals_match_their_singular():
    reference = [_entity("migraine", "CONDITION")]
    hypothesis = [_entity("Migraines", "DISEASE")]
    assert entities.entity_scores(reference, hypothesis)["entity_lenient_f1"] == 1.0


def test_stemming_is_symmetric_between_the_two_forms():
    """The transform only has to be consistent, not correct. A rule that fires
    on the plural without a matching one for the singular is the bug this
    guards: "headaches" once stemmed to "headach" while "headache" did not."""
    for singular, plural in [
        ("headache", "headaches"), ("migraine", "migraines"),
        ("allergy", "allergies"), ("symptom", "symptoms"),
    ]:
        assert entities.canonical_text(singular) == entities.canonical_text(plural)


def test_distinct_terms_are_not_merged_by_stemming():
    assert entities.canonical_text("nausea") != entities.canonical_text("headache")
    assert entities.canonical_text("asthma") != entities.canonical_text("eczema")


def test_a_missed_term_is_reported_once_not_per_mention():
    detail = entities.missed_and_spurious(
        [_entity("chest pain", "SYMPTOM")],
        [_entity("nausea", "SYMPTOM")] * 3,
    )
    assert detail["missed"] == ["chest pain"]
    assert detail["spurious"] == ["nausea"]
