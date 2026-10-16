"""Checklist coverage: does the note carry what a clinician said was present?

The model call is stubbed. What is tested is how verdicts become a score, and
in particular that a failed judgement produces *no* metric rather than a
quietly weaker one — two runs reporting `critical_item_coverage` computed by
different methods would not be comparable, and nothing would say so.
"""

import pytest

from eval.metrics import coverage
from eval.primock_checklists import ChecklistItem

ITEMS = [
    ChecklistItem("Diarrhoea", "critical"),
    ChecklistItem("No blood in stool", "critical"),
    ChecklistItem("Abdominal pain - lower", "critical"),
    ChecklistItem("Works as an accountant", "non_critical"),
]


def _stub_judge(monkeypatch, covered_ids):
    def fake(prompt, message, **kwargs):
        return {"findings": [
            {"id": index, "covered": index in covered_ids} for index in range(len(ITEMS))
        ]}
    monkeypatch.setattr(coverage, "chat_json", fake)


def test_coverage_is_split_by_criticality(monkeypatch):
    # Two of three critical items covered; the non-critical one is not.
    _stub_judge(monkeypatch, {0, 1})
    scores = coverage.judged_coverage_scores(ITEMS, {"subjective": "..."})

    assert scores["critical_item_coverage"] == round(2 / 3, 4)
    assert scores["checklist_coverage"] == 0.5
    assert scores["critical_items"] == 3.0


def test_full_coverage_scores_one(monkeypatch):
    _stub_judge(monkeypatch, {0, 1, 2, 3})
    assert coverage.judged_coverage_scores(ITEMS, "note")["critical_item_coverage"] == 1.0


def test_the_ceiling_is_reported_under_its_own_prefix(monkeypatch):
    """So it can never be mistaken for the pipeline's own score."""
    _stub_judge(monkeypatch, {0})
    scores = coverage.ceiling_scores(ITEMS, "the clinician's note")

    assert "ceiling_critical_item_coverage" in scores
    assert "critical_item_coverage" not in scores


def test_a_failed_judgement_produces_no_metric(monkeypatch):
    """Not a lexical fallback: a weaker measurement reported under the same
    name is how two runs silently stop being comparable."""
    def explode(*args, **kwargs):
        raise RuntimeError("groq unavailable")

    monkeypatch.setattr(coverage, "chat_json", explode)
    assert coverage.judged_coverage_scores(ITEMS, "note") == {}


def test_an_empty_note_or_checklist_scores_nothing(monkeypatch):
    _stub_judge(monkeypatch, {0})
    assert coverage.judged_coverage_scores(ITEMS, "   ") == {}
    assert coverage.judged_coverage_scores([], "a note") == {}


def test_irrelevant_items_are_not_scored(monkeypatch):
    """The clinicians marked them as not clinically meaningful."""
    items = ITEMS + [ChecklistItem("Wearing a blue shirt", "irrelevant")]
    _stub_judge(monkeypatch, {0, 1, 2, 3})
    assert coverage.judged_coverage_scores(items, "note")["checklist_items"] == 4.0


def test_malformed_verdicts_are_ignored(monkeypatch):
    monkeypatch.setattr(coverage, "chat_json", lambda *a, **k: {"findings": [
        {"id": "not-an-int", "covered": True},
        "not a dict",
        {"id": 0, "covered": True},
    ]})
    scores = coverage.judged_coverage_scores(ITEMS, "note")
    assert scores["critical_item_coverage"] == round(1 / 3, 4)


# ── The lexical version, kept only as the record of why it was replaced ───────

def test_lexical_matching_misses_clinical_shorthand():
    """Documents the failure that made model judging necessary: the checklist
    writes "Abdominal pain - lower" and a real note writes "LLQ pain"."""
    note_words = coverage._content_words("3/7 hx diarrhea. LLQ pain. Opening bowels x6/day.")
    assert coverage.covers("Diarrhoea", note_words) is True
    assert coverage.covers("Abdominal pain - lower", note_words) is False


def test_british_and_american_spellings_match():
    note_words = coverage._content_words("patient reports diarrhea")
    assert coverage.covers("Diarrhoea", note_words) is True
