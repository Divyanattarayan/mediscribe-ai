"""Ontology linking against the NLM REST services.

No network here: `_get_json` is stubbed with recorded response shapes, so the
suite stays fast and does not fail when NLM is slow or unreachable. The shapes
are copied from real responses — the ICD-10 candidate lists in particular are
the actual orderings the API returns, which is what the ranking has to cope
with.
"""

import pytest

import ontology


@pytest.fixture(autouse=True)
def isolated_cache(tmp_path, monkeypatch):
    """Every test gets an empty cache, and nothing is written to the real one."""
    monkeypatch.setattr(ontology, "_cache", {})
    monkeypatch.setattr(ontology, "CACHE_PATH", tmp_path / "cache.json")
    monkeypatch.setattr(ontology, "ONTOLOGY_ENABLED", True)


def _stub_responses(monkeypatch, responses: dict):
    """Route `_get_json` by substring match on the URL."""
    calls = []

    def fake_get_json(url):
        calls.append(url)
        for fragment, payload in responses.items():
            if fragment in url:
                return payload
        return None

    monkeypatch.setattr(ontology, "_get_json", fake_get_json)
    return calls


# ── Medications ───────────────────────────────────────────────────────────────

def test_an_exact_drug_name_resolves_to_one_rxcui(monkeypatch):
    _stub_responses(monkeypatch, {"rxcui.json": {"idGroup": {"rxnormId": ["17767"]}}})
    result = ontology.lookup_medication("Amlodipine")
    assert result["system"] == "RXNORM"
    assert result["code"] == "17767"
    assert result["match"] == "exact"
    assert result["score"] == 100.0


def test_a_misspelling_falls_back_to_approximate_matching(monkeypatch):
    """RxNav's own score is on an opaque scale (~9 for a good match), so the
    decision is made on name similarity instead."""
    _stub_responses(monkeypatch, {
        "rxcui.json": {"idGroup": {}},
        "approximateTerm.json": {"approximateGroup": {"candidate": [
            {"rxcui": "83367", "score": "9.004", "rank": "1"},                    # no name
            {"rxcui": "83367", "score": "9.004", "rank": "1", "name": "ATORVASTATIN"},
        ]}},
    })
    result = ontology.lookup_medication("adervastatin")
    assert result["code"] == "83367"
    assert result["match"] == "approximate"
    assert result["score"] >= ontology.MIN_NAME_SIMILARITY


def test_a_nonsense_term_matches_nothing(monkeypatch):
    _stub_responses(monkeypatch, {
        "rxcui.json": {"idGroup": {}},
        "approximateTerm.json": {"approximateGroup": {"candidate": [
            {"rxcui": "1234", "score": "5.0", "name": "warfarin"},
        ]}},
    })
    assert ontology.lookup_medication("wibblefloop") is None


def test_an_unreachable_service_returns_none_rather_than_raising(monkeypatch):
    monkeypatch.setattr(ontology, "_get_json", lambda url: None)
    assert ontology.lookup_medication("amlodipine") is None
    assert ontology.lookup_condition("asthma") is None


# ── Conditions ────────────────────────────────────────────────────────────────

# The real ordering the API returns for "asthma" — most specific first.
ASTHMA_CANDIDATES = [
    ["J45.998", "Other asthma"],
    ["J82.83", "Eosinophilic asthma"],
    ["J45.909", "Unspecified asthma, uncomplicated"],
    ["J45.991", "Cough variant asthma"],
    ["J45.20", "Mild intermittent asthma, uncomplicated"],
]


def test_the_generic_code_beats_the_specific_one_the_api_returns_first(monkeypatch):
    """Coding "asthma" to `J82.83 Eosinophilic asthma` would invent a
    specificity the transcript never stated."""
    _stub_responses(monkeypatch, {"icd10cm": [5, [], None, ASTHMA_CANDIDATES]})
    result = ontology.lookup_condition("asthma")
    assert result["code"] == "J45.909"


def test_condition_results_carry_alternatives_for_review(monkeypatch):
    _stub_responses(monkeypatch, {"icd10cm": [5, [], None, ASTHMA_CANDIDATES]})
    result = ontology.lookup_condition("asthma")
    assert len(result["alternatives"]) == 3
    assert all("code" in alt and "display" in alt for alt in result["alternatives"])


def test_a_non_exact_condition_match_is_flagged_for_review(monkeypatch):
    """ICD-10 from free text is a curated-crosswalk problem. Anything short of
    an exact name match is a suggestion, and must say so."""
    _stub_responses(monkeypatch, {"icd10cm": [5, [], None, ASTHMA_CANDIDATES]})
    assert ontology.lookup_condition("asthma")["requires_review"] is True


def test_an_exact_name_match_is_not_flagged(monkeypatch):
    _stub_responses(monkeypatch, {
        "icd10cm": [1, [], None, [["I30.9", "Pericarditis"], ["A39.53", "Meningococcal pericarditis"]]],
    })
    result = ontology.lookup_condition("pericarditis")
    assert result["code"] == "I30.9"
    assert result["requires_review"] is False


def test_ranking_prefers_fewer_added_qualifiers():
    ranked = [code for code, _ in ontology._rank_icd_candidates("asthma", ASTHMA_CANDIDATES)]
    # "Unspecified asthma, uncomplicated" adds nothing the query did not ask
    # for: both words mark the absence of a qualifier.
    assert ranked[0] == "J45.909"
    # Everything that adds a qualifier ranks below it, in code-length order.
    assert ranked.index("J45.909") < ranked.index("J45.20") < ranked.index("J45.991")


# ── Entity linking and confidence ─────────────────────────────────────────────

def test_only_medications_receive_a_confidence(monkeypatch):
    """RxNorm resolves a drug to one concept, so its score means something. An
    ICD-10 suggestion does not, and writing a confidence from it would claim an
    assurance we do not have."""
    _stub_responses(monkeypatch, {
        "rxcui.json": {"idGroup": {"rxnormId": ["17767"]}},
        "icd10cm": [5, [], None, ASTHMA_CANDIDATES],
    })
    entities = ontology.link_entities([
        {"text": "amlodipine", "category": "medication", "confidence": 0.0},
        {"text": "asthma", "category": "condition", "confidence": 0.0},
    ])
    assert entities[0]["confidence"] == 1.0
    assert entities[1]["confidence"] == 0.0
    assert entities[1]["ontology"]["system"] == "ICD10CM"


def test_uncategorised_entities_are_left_alone(monkeypatch):
    _stub_responses(monkeypatch, {"rxcui.json": {"idGroup": {"rxnormId": ["1"]}}})
    entities = ontology.link_entities([{"text": "chest pain", "category": "symptom"}])
    assert "ontology" not in entities[0]


def test_repeated_terms_hit_the_cache_not_the_network(monkeypatch):
    calls = _stub_responses(monkeypatch, {"rxcui.json": {"idGroup": {"rxnormId": ["17767"]}}})
    for _ in range(4):
        ontology.link_term("amlodipine", "medication")
    assert len(calls) == 1


def test_a_miss_is_cached_too(monkeypatch):
    """Otherwise every transcript pays a request for every unknown term."""
    calls = _stub_responses(monkeypatch, {"rxcui.json": {"idGroup": {}}, "approximateTerm.json": {}})
    ontology.link_term("wibblefloop", "medication")
    ontology.link_term("wibblefloop", "medication")
    assert ontology.cache_stats()["misses_cached"] == 1
    assert len(calls) == 2   # one exact + one approximate, on the first call only


def test_linking_can_be_switched_off(monkeypatch):
    monkeypatch.setattr(ontology, "ONTOLOGY_ENABLED", False)
    entities = ontology.link_entities([{"text": "amlodipine", "category": "medication"}])
    assert "ontology" not in entities[0]


def test_counts_separate_the_two_systems(monkeypatch):
    _stub_responses(monkeypatch, {
        "rxcui.json": {"idGroup": {"rxnormId": ["17767"]}},
        "icd10cm": [5, [], None, ASTHMA_CANDIDATES],
    })
    entities = ontology.link_entities([
        {"text": "amlodipine", "category": "medication"},
        {"text": "asthma", "category": "condition"},
        {"text": "chest pain", "category": "symptom"},
    ])
    counts = ontology.ontology_counts(entities)
    assert counts == {"linkable": 2, "linked": 2, "rxnorm": 1, "icd10cm": 1}
