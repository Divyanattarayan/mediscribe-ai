"""Claim-level verification of a generated note.

The model call is stubbed throughout: what is being tested is how a verdict is
turned into a decision, not whether the model judges well. The behaviour that
matters most is the failure path — a verifier that cannot run must be
distinguishable from one that found nothing wrong.
"""

import pytest

import claim_verification as cv

NOTE = {
    "subjective": "Patient reports chest pain since Tuesday. Denies nausea.",
    "objective": "This recording captures history-taking only.",
    "assessment": "1. Chest pain, likely pericarditis.",
    "plan": "Arrange ECG. Start metformin 500mg twice daily.",
}
TRANSCRIPT = "Patient: I've had chest pain since Tuesday. No nausea. Doctor: I'll arrange an ECG."


@pytest.fixture(autouse=True)
def enabled(monkeypatch):
    monkeypatch.setattr(cv, "CLAIM_VERIFICATION_ENABLED", True)


def _stub(monkeypatch, claims):
    monkeypatch.setattr(cv, "chat_json", lambda *a, **k: {"claims": claims})


def _claim(text, verdict, section="plan"):
    return {"claim": text, "verdict": verdict, "section": section, "evidence": ""}


# ── Verdicts ──────────────────────────────────────────────────────────────────

def test_a_fully_supported_note_reports_no_problems(monkeypatch):
    _stub(monkeypatch, [_claim("chest pain since Tuesday", "supported", "subjective")])
    report = cv.verify_note(NOTE, TRANSCRIPT)
    assert report.ran is True
    assert report.problems == []
    assert report.unsupported_rate == 0.0


def test_unsupported_and_contradicted_claims_both_count_as_problems(monkeypatch):
    _stub(monkeypatch, [
        _claim("chest pain since Tuesday", "supported", "subjective"),
        _claim("started on metformin 500mg twice daily", "unsupported"),
        _claim("the patient reported nausea", "contradicted", "subjective"),
    ])
    report = cv.verify_note(NOTE, TRANSCRIPT)
    assert len(report.problems) == 2
    assert report.unsupported_rate == round(2 / 3, 4)


def test_problems_are_grouped_by_section_for_targeted_regeneration(monkeypatch):
    _stub(monkeypatch, [
        _claim("metformin", "unsupported", "plan"),
        _claim("nausea reported", "contradicted", "subjective"),
    ])
    grouped = cv.verify_note(NOTE, TRANSCRIPT).problems_by_section()
    assert set(grouped) == {"plan", "subjective"}
    assert grouped["plan"] == ["metformin"]


def test_a_claim_with_no_recognised_section_is_still_reported(monkeypatch):
    _stub(monkeypatch, [_claim("something", "unsupported", section="")])
    assert "unattributed" in cv.verify_note(NOTE, TRANSCRIPT).problems_by_section()


def test_malformed_claims_are_ignored(monkeypatch):
    _stub(monkeypatch, [
        {"claim": "", "verdict": "supported"},
        {"claim": "valid", "verdict": "nonsense-verdict"},
        "not a dict",
        _claim("real one", "supported", "plan"),
    ])
    report = cv.verify_note(NOTE, TRANSCRIPT)
    assert len(report.claims) == 1


# ── Failure paths ─────────────────────────────────────────────────────────────

def test_a_verifier_that_cannot_run_is_not_a_clean_bill_of_health(monkeypatch):
    """`ran=False` with no problems must not read the same as "nothing wrong"."""
    def explode(*args, **kwargs):
        raise RuntimeError("groq unavailable")

    monkeypatch.setattr(cv, "chat_json", explode)
    report = cv.verify_note(NOTE, TRANSCRIPT)

    assert report.ran is False
    assert report.problems == []
    assert "groq unavailable" in report.error


def test_a_model_failure_never_raises(monkeypatch):
    """A verification problem must not cost the user their note."""
    monkeypatch.setattr(cv, "chat_json", lambda *a, **k: (_ for _ in ()).throw(ValueError("bad json")))
    assert cv.verify_note(NOTE, TRANSCRIPT).ran is False


def test_verification_can_be_switched_off(monkeypatch):
    monkeypatch.setattr(cv, "CLAIM_VERIFICATION_ENABLED", False)
    report = cv.verify_note(NOTE, TRANSCRIPT)
    assert report.ran is False
    assert "disabled" in report.error


def test_an_empty_note_or_transcript_is_not_verified(monkeypatch):
    _stub(monkeypatch, [_claim("x", "supported")])
    assert cv.verify_note({}, TRANSCRIPT).ran is False
    assert cv.verify_note(NOTE, "").ran is False


def test_a_verifier_returning_nothing_usable_counts_as_not_run(monkeypatch):
    _stub(monkeypatch, [])
    report = cv.verify_note(NOTE, TRANSCRIPT)
    assert report.ran is False
    assert "no usable claims" in report.error


# ── Report shape ──────────────────────────────────────────────────────────────

def test_the_report_records_what_was_checked(monkeypatch):
    _stub(monkeypatch, [
        _claim("supported thing", "supported", "subjective"),
        _claim("invented thing", "unsupported", "plan"),
    ])
    payload = cv.verify_note(NOTE, TRANSCRIPT).to_dict()
    assert payload["ran"] is True
    assert payload["claims_total"] == 2
    assert payload["claims_unsupported"] == 1
    assert payload["problem_claims"][0]["claim"] == "invented thing"
