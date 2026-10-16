"""Assertion detection: negation, temporality, experiencer, uncertainty.

The pure helpers are tested unconditionally. The ConText integration is tested
against a real (blank + sentencizer) pipeline when medspaCy is installed, and
skipped otherwise — the pipeline is meant to degrade rather than fail when the
dependency is absent, and that degradation is asserted too.
"""

import pytest

import clinical_assertions as ca

pytestmark = pytest.mark.filterwarnings("ignore::FutureWarning")


# ── Pure helpers ──────────────────────────────────────────────────────────────

def _entity(text, **overrides):
    """An entity ConText actually resolved, unless a test says otherwise."""
    entity = {"text": text, "label": "SYMPTOM", "start": 0, "end": len(text)}
    entity.update(ca.DEFAULT_ASSERTIONS)
    entity["assertion_source"] = ca.CONTEXT_PIPE
    entity.update(overrides)
    return entity


def test_an_unqualified_mention_is_an_active_patient_finding():
    assert ca.is_active_patient_finding(_entity("chest pain")) is True


@pytest.mark.parametrize("overrides", [
    {"negated": True},
    {"experiencer": "family"},
    {"temporality": "historical"},
    {"temporality": "hypothetical"},
])
def test_qualified_mentions_are_not_active_findings(overrides):
    assert ca.is_active_patient_finding(_entity("chest pain", **overrides)) is False


def test_missing_keys_default_to_an_active_finding():
    """Entities from a path that never ran assertion detection must still be
    usable rather than raising."""
    assert ca.is_active_patient_finding({"text": "chest pain"}) is True


def test_counts_summarise_each_axis():
    counts = ca.assertion_counts([
        _entity("chest pain", negated=True),
        _entity("asthma", temporality="historical"),
        _entity("heart attack", experiencer="family"),
        _entity("pericarditis", uncertain=True),
        _entity("fever", temporality="hypothetical"),
        {"text": "unresolved"},
    ])
    assert counts["negated"] == 1
    assert counts["historical"] == 1
    assert counts["hypothetical"] == 1
    assert counts["family"] == 1
    assert counts["uncertain"] == 1
    # The entity with no assertion_source counts as unresolved, so degraded
    # coverage shows up instead of passing as "nothing was negated".
    assert counts["unresolved"] == 1


# ── ConText integration ───────────────────────────────────────────────────────

medspacy_required = pytest.mark.skipif(
    not ca.MEDSPACY_AVAILABLE, reason="medspacy is not installed"
)


@pytest.fixture(scope="module")
def context_pipeline():
    import spacy

    nlp = spacy.blank("en")
    return ca.attach_context(nlp)


def _annotate(nlp, text, terms):
    """Build entity dicts for `terms` by locating them in `text`."""
    doc = nlp(text)
    entities = []
    for term in terms:
        start = text.lower().index(term.lower())
        entities.append({"text": term, "label": "SYMPTOM", "start": start, "end": start + len(term)})
    return {e["text"]: e for e in ca.annotate_assertions(doc, entities, nlp)}


@medspacy_required
def test_a_denied_symptom_is_marked_negated(context_pipeline):
    found = _annotate(context_pipeline, "The patient denies chest pain today.", ["chest pain"])
    assert found["chest pain"]["negated"] is True
    assert found["chest pain"]["assertion_source"] == ca.CONTEXT_PIPE


@medspacy_required
def test_a_relatives_diagnosis_is_not_the_patients(context_pipeline):
    found = _annotate(context_pipeline, "My dad had a heart attack in his fifties.", ["heart attack"])
    assert found["heart attack"]["experiencer"] == "family"
    assert ca.is_active_patient_finding(found["heart attack"]) is False


@medspacy_required
def test_conversational_history_phrasing_is_historical(context_pipeline):
    """ConText's shipped rules cover "history of"; consultation speech says
    "as a child", which the added rules have to catch."""
    found = _annotate(context_pipeline, "I had asthma as a child but I grew out of it.", ["asthma"])
    assert found["asthma"]["temporality"] == "historical"


@medspacy_required
def test_conditional_safety_netting_is_hypothetical(context_pipeline):
    found = _annotate(
        context_pipeline, "Watch out for fever or a stiff neck over the next few days.", ["fever"]
    )
    assert found["fever"]["temporality"] == "hypothetical"


@medspacy_required
def test_an_unqualified_mention_stays_current_and_positive(context_pipeline):
    found = _annotate(context_pipeline, "He takes amlodipine every morning.", ["amlodipine"])
    entity = found["amlodipine"]
    assert (entity["negated"], entity["temporality"], entity["experiencer"]) == (False, "current", "patient")


@medspacy_required
def test_two_mentions_of_one_term_are_read_independently(context_pipeline):
    """The whole point of span-level assertion: the same words can assert
    opposite things in one transcript."""
    text = "The patient denies chest pain. If the chest pain comes back, return immediately."
    doc = context_pipeline(text)
    first = text.index("chest pain")
    second = text.index("chest pain", first + 1)
    entities = ca.annotate_assertions(doc, [
        {"text": "chest pain", "label": "SYMPTOM", "start": first, "end": first + 10},
        {"text": "chest pain", "label": "SYMPTOM", "start": second, "end": second + 10},
    ], context_pipeline)
    assert entities[0]["negated"] is True
    assert entities[1]["temporality"] == "hypothetical"


@medspacy_required
def test_entities_survive_a_pipeline_without_the_component():
    """No ConText means defaults everywhere and an honest `unresolved` count,
    not lost entities."""
    import spacy

    nlp = spacy.blank("en")
    entities = ca.annotate_assertions(nlp("The patient denies chest pain."), [
        {"text": "chest pain", "label": "SYMPTOM", "start": 19, "end": 29}
    ], nlp)
    assert len(entities) == 1
    assert entities[0]["negated"] is False
    assert ca.assertion_counts(entities)["unresolved"] == 1


# ── Speaker-label masking ─────────────────────────────────────────────────────

def test_masking_preserves_every_character_offset():
    """Offsets index the original transcript everywhere else in the pipeline,
    so the mask must substitute, never shorten."""
    text = "Doctor: What's wrong? Patient: My chest hurts."
    masked = ca.mask_speaker_labels(text)
    assert len(masked) == len(text)
    assert masked.index("chest") == text.index("chest")
    assert "Doctor:" not in masked and "Patient:" not in masked


def test_masking_leaves_clinical_text_alone():
    text = "The patient reports chest pain; no doctor has reviewed the ECG."
    assert ca.mask_speaker_labels(text) == text


@medspacy_required
def test_a_speaker_label_no_longer_blocks_negation(context_pipeline):
    """ConText's rules were written for dictated prose: "No nausea." is
    detected but "Patient: No nausea." was not, which cost us most denials in
    dialogue transcripts."""
    text = "Patient: No nausea."
    masked = ca.mask_speaker_labels(text)
    index = text.index("nausea")
    entities = ca.annotate_assertions(context_pipeline(masked), [
        {"text": "nausea", "label": "SYMPTOM", "start": index, "end": index + 6}
    ], context_pipeline)
    assert entities[0]["negated"] is True


@medspacy_required
def test_past_tense_reporting_of_a_new_diagnosis_stays_current(context_pipeline):
    """"the blood test said I had diabetes" reports an active diagnosis. A
    HISTORICAL rule on "i had" marked it resolved; measurement caught it."""
    text = "Patient: the blood test said I had diabetes."
    index = text.index("diabetes")
    entities = ca.annotate_assertions(context_pipeline(ca.mask_speaker_labels(text)), [
        {"text": "diabetes", "label": "CONDITION", "start": index, "end": index + 8}
    ], context_pipeline)
    assert entities[0]["temporality"] == "current"


@medspacy_required
def test_anaphoric_denial_is_a_known_limitation(context_pipeline):
    """"Any dizziness? No, none of those." needs coreference, which ConText
    does not do. Documented as a limitation so a future fix has a test to flip,
    rather than sitting as an unexplained miss in the eval report.
    """
    text = "Doctor: Any dizziness or headaches? Patient: No, none of those."
    index = text.index("dizziness")
    entities = ca.annotate_assertions(context_pipeline(ca.mask_speaker_labels(text)), [
        {"text": "dizziness", "label": "SYMPTOM", "start": index, "end": index + 9}
    ], context_pipeline)
    assert entities[0]["negated"] is False, "if this now passes, update the roadmap limitation"
