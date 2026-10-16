"""Medical spell correction, which is off by default and should stay off.

Measurement (recorded in the module docstring) showed it corrupting correct
clinical text — `regular` to `irregular`, `feeling` to `peeling` — and tripling
the medical-term error rate on real ASR output, improving 0 of 20 cases. These
tests pin the default and keep the evidence for *why* next to the code, so
re-enabling it is a deliberate act rather than an accident.
"""

import pytest

import spell_correction


SENTENCE = "Doctor: How are you feeling? Your pulse is regular and you are eating well."


def test_correction_is_off_by_default():
    assert spell_correction.SPELL_CORRECTION_ENABLED is False


def test_disabled_correction_returns_the_text_untouched():
    corrected, log = spell_correction.correct_medical_spelling(SENTENCE, verbose=False)
    assert corrected == SENTENCE
    assert log == []


def test_callers_do_not_need_to_know_it_is_disabled():
    """It returns the same `(text, corrections)` shape either way."""
    corrected, log = spell_correction.correct_medical_spelling("anything", verbose=False)
    assert isinstance(corrected, str)
    assert isinstance(log, list)


@pytest.mark.parametrize("word, corruption", [
    ("feeling", "peeling"),
    ("regular", "irregular"),   # inverts the clinical meaning
    ("eating", "sweating"),     # invents a symptom
])
def test_the_corruption_it_causes_when_enabled(monkeypatch, word, corruption):
    """Documents the failure rather than asserting it is fixed.

    If a future change makes these pass through unaltered, the corrector has
    genuinely improved and this test should be updated along with the default.
    """
    monkeypatch.setattr(spell_correction, "SPELL_CORRECTION_ENABLED", True)
    corrected, _ = spell_correction.correct_medical_spelling(
        f"the patient is {word} today", verbose=False
    )
    assert corruption in corrected, (
        f"'{word}' no longer corrupts to '{corruption}' — re-measure before re-enabling"
    )


def test_a_genuine_misspelling_is_still_corrected_when_enabled(monkeypatch):
    """The capability was never worthless, only unsafe: it does fix real
    misspellings. That is why the code is kept rather than deleted."""
    monkeypatch.setattr(spell_correction, "SPELL_CORRECTION_ENABLED", True)
    corrected, log = spell_correction.correct_medical_spelling(
        "started on certraline for depression", verbose=False
    )
    assert "sertraline" in corrected
    assert log
