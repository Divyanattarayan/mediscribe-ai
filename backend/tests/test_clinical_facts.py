"""The fact table and its evidence-verification guarantee.

The point of this layer is that a fact cannot enter the note without transcript
text supporting it, so the tests that matter are the ones proving a fabricated
citation is caught. No network: the LLM pass is exercised through
`parse_llm_facts` with recorded payloads.
"""

import clinical_facts as cf

TRANSCRIPT = (
    "Doctor: What brings you in? "
    "Patient: I've had chest pain since Tuesday, sharp, in the middle. "
    "Doctor: Any nausea? "
    "Patient: No nausea at all. "
    "Doctor: Any tablets? "
    "Patient: Just amlodipine. "
    "Patient: My dad had a heart attack in his fifties."
)


def _entity(text, category="symptom", label="SYMPTOM", **overrides):
    start = TRANSCRIPT.index(overrides.pop("find", text))
    entity = {
        "text": text, "category": category, "label": label,
        "start": start, "end": start + len(text),
        "negated": False, "temporality": "current", "experiencer": "patient",
        "uncertain": False, "confidence": 0.0,
    }
    entity.update(overrides)
    return entity


# ── Evidence location ─────────────────────────────────────────────────────────

def test_a_verbatim_quote_is_located_exactly():
    found = cf.locate_evidence("I've had chest pain since Tuesday", TRANSCRIPT)
    assert found is not None
    start, end, score = found
    assert TRANSCRIPT[start:end].startswith("I've had chest pain")
    assert score == 100.0


def test_punctuation_and_casing_differences_still_match():
    """Models normalise quotes; rejecting a citation over a comma would discard
    true facts."""
    found = cf.locate_evidence("i've had chest pain since tuesday", TRANSCRIPT)
    assert found is not None and found[2] >= cf.MIN_EVIDENCE_SIMILARITY


def test_a_paraphrase_is_not_accepted_as_a_citation():
    assert cf.locate_evidence(
        "the patient reports discomfort in the thorax lasting several days", TRANSCRIPT
    ) is None


def test_an_invented_quote_is_rejected():
    """The whole guarantee rests on this: a fact the model made up has no
    transcript text behind it, and must not be assertable."""
    assert cf.locate_evidence("Patient: I take metformin 500mg twice daily.", TRANSCRIPT) is None


def test_an_empty_quote_is_rejected():
    assert cf.locate_evidence("", TRANSCRIPT) is None


# ── Entity-derived facts ──────────────────────────────────────────────────────

def test_entity_facts_carry_the_sentence_that_supports_them():
    facts = cf.facts_from_entities([_entity("chest pain")], TRANSCRIPT)
    assert len(facts) == 1
    assert "chest pain since Tuesday" in facts[0].evidence
    assert facts[0].verified is True
    assert facts[0].source == "entity"


def test_entity_facts_need_no_verification():
    """Their offsets came from the transcript, so there is nothing to check."""
    facts = cf.facts_from_entities([_entity("chest pain")], TRANSCRIPT)
    assert all(fact.is_assertable for fact in facts)


def test_a_family_members_condition_becomes_family_history():
    facts = cf.facts_from_entities(
        [_entity("heart attack", "condition", "DISEASE", experiencer="family")], TRANSCRIPT
    )
    assert facts[0].fact_type == "family_history"


def test_repeated_mentions_of_one_assertion_collapse():
    facts = cf.facts_from_entities([_entity("chest pain"), _entity("chest pain")], TRANSCRIPT)
    assert len(facts) == 1


def test_the_same_term_asserted_differently_stays_separate():
    """Denied once and confirmed later are two findings, not one."""
    facts = cf.facts_from_entities([
        _entity("chest pain"),
        _entity("chest pain", negated=True),
    ], TRANSCRIPT)
    assert len(facts) == 2


def test_a_clinicians_question_loses_to_the_patients_answer():
    """"Any nausea? No nausea at all." would otherwise yield a present symptom
    the patient explicitly denied."""
    facts = cf.facts_from_entities([
        _entity("nausea"),                                     # the question
        _entity("nausea", find="No nausea", negated=True),     # the answer
    ], TRANSCRIPT)
    assert len(facts) == 1
    assert facts[0].negated is True
    assert facts[0].evidence.startswith("Patient:")


def test_a_term_only_ever_asked_about_is_kept():
    """Something was raised; dropping it silently would lose that."""
    facts = cf.facts_from_entities([_entity("nausea")], TRANSCRIPT)
    assert len(facts) == 1
    assert facts[0].evidence.endswith("?")


# ── LLM-derived facts ─────────────────────────────────────────────────────────

def _payload(**overrides):
    fact = {
        "fact_type": "symptom", "value": "chest pain",
        "evidence": "I've had chest pain since Tuesday",
        "detail": "sharp, central, since Tuesday",
    }
    fact.update(overrides)
    return {"facts": [fact]}


def test_a_cited_llm_fact_is_verified_and_assertable():
    facts = cf.parse_llm_facts(_payload(), TRANSCRIPT)
    assert facts[0].verified is True
    assert facts[0].is_assertable is True
    assert facts[0].detail.startswith("sharp")


def test_an_llm_fact_with_a_fabricated_quote_is_not_assertable():
    facts = cf.parse_llm_facts(
        _payload(value="metformin", fact_type="medication",
                 evidence="Patient: I take metformin every morning."),
        TRANSCRIPT,
    )
    assert facts[0].verified is False
    assert facts[0].is_assertable is False


def test_an_unverified_fact_is_kept_for_inspection_not_deleted():
    """A dropped row is invisible; a flagged one shows what the model claimed
    and could not support."""
    facts = cf.parse_llm_facts(_payload(evidence="entirely invented sentence"), TRANSCRIPT)
    assert len(facts) == 1
    assert facts[0].verified is False


def test_facts_with_no_value_or_an_unknown_type_are_discarded():
    payload = {"facts": [
        {"fact_type": "symptom", "value": "", "evidence": "x"},
        {"fact_type": "nonsense", "value": "something", "evidence": "x"},
        "not a dict",
    ]}
    assert cf.parse_llm_facts(payload, TRANSCRIPT) == []


def test_an_out_of_range_temporality_falls_back_to_current():
    facts = cf.parse_llm_facts(_payload(temporality="whenever"), TRANSCRIPT)
    assert facts[0].temporality == "current"


# ── Merging and rendering ─────────────────────────────────────────────────────

def test_the_entity_row_wins_but_keeps_the_models_detail():
    """Entity facts carry exact offsets and ConText-resolved assertions; the
    model contributes the qualifiers entities cannot express."""
    entity_facts = cf.facts_from_entities([_entity("chest pain")], TRANSCRIPT)
    llm_facts = cf.parse_llm_facts(_payload(), TRANSCRIPT)
    merged = cf.merge_facts(entity_facts, llm_facts)

    assert len(merged) == 1
    assert merged[0].source == "entity"
    assert merged[0].detail.startswith("sharp")


def test_a_fact_only_the_model_found_is_added():
    merged = cf.merge_facts(
        cf.facts_from_entities([_entity("chest pain")], TRANSCRIPT),
        cf.parse_llm_facts(
            _payload(fact_type="patient_concern", value="worried about his heart",
                     evidence="My dad had a heart attack in his fifties"),
            TRANSCRIPT,
        ),
    )
    assert len(merged) == 2


def test_unverified_facts_are_excluded_from_the_prompt():
    """The guarantee has to hold at the point the note is written."""
    facts = cf.parse_llm_facts(
        _payload(value="metformin", fact_type="medication", evidence="invented"), TRANSCRIPT
    )
    assert "metformin" not in cf.render_for_prompt(facts)


def test_the_prompt_groups_facts_by_what_they_assert():
    facts = cf.facts_from_entities([
        _entity("chest pain"),
        _entity("nausea", find="No nausea", negated=True),
        _entity("heart attack", "condition", "DISEASE", experiencer="family"),
    ], TRANSCRIPT)
    rendered = cf.render_for_prompt(facts)

    assert "DENIED" in rendered and "FAMILY HISTORY" in rendered
    # The denial must not appear under the present findings.
    present_block = rendered.split("DENIED")[0]
    assert "nausea" not in present_block
    assert "chest pain" in present_block


def test_rendering_an_empty_table_says_so():
    assert cf.render_for_prompt([]) == "No clinical facts extracted."


def test_the_summary_separates_verified_from_unverified():
    facts = (
        cf.facts_from_entities([_entity("chest pain")], TRANSCRIPT)
        + cf.parse_llm_facts(_payload(value="metformin", evidence="invented"), TRANSCRIPT)
    )
    summary = cf.fact_table_summary(facts)
    assert summary == {
        "total": 2, "assertable": 1, "unverified": 1,
        "from_entities": 1, "from_llm": 1, "negated": 0,
        "by_type": {"symptom": 1},
    }


def test_the_llm_pass_can_be_switched_off():
    """Entity facts still arrive, so the table degrades rather than vanishing."""
    facts = cf.build_fact_table(TRANSCRIPT, [_entity("chest pain")], use_llm=False)
    assert len(facts) == 1
    assert facts[0].source == "entity"
