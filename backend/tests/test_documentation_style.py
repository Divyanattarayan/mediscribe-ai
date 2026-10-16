"""Pure-function coverage for encounter/style normalisation."""

import pytest

from documentation_style import (
    DEFAULT_STYLE_PROFILE,
    normalize_encounter_type,
    normalize_note_style_preset,
    normalize_preferred_focus,
    resolve_style_profile,
    serialize_style_profile,
)


@pytest.mark.parametrize("value", ["balanced", "concise", "detailed"])
def test_known_presets_pass_through(value):
    assert normalize_note_style_preset(value) == value


@pytest.mark.parametrize("value", [None, "", "fancy", "verbose", 123])
def test_unknown_presets_fall_back_to_default(value):
    assert normalize_note_style_preset(value) == DEFAULT_STYLE_PROFILE["note_style_preset"]


@pytest.mark.parametrize("value", [None, "", "unknown", "acute"])
def test_unknown_focus_falls_back_to_general(value):
    assert normalize_preferred_focus(value) == "general"


def test_unknown_encounter_type_falls_back_to_follow_up():
    assert normalize_encounter_type("wild guess") == "follow_up"
    assert normalize_encounter_type(None) == "follow_up"


def test_known_encounter_types_pass_through():
    for value in ("acute_visit", "follow_up", "counselling_education", "medication_review"):
        assert normalize_encounter_type(value) == value


def test_serialize_from_none_is_the_default_profile():
    assert serialize_style_profile(None) == DEFAULT_STYLE_PROFILE
    # Must be a copy, not the shared dict.
    assert serialize_style_profile(None) is not DEFAULT_STYLE_PROFILE


def test_serialize_from_object_reads_attributes():
    class FakeUser:
        note_style_preset = "concise"
        preferred_focus = "plan_driven"
        include_bullets_in_plan = True
        include_patient_friendly_language = False

    assert serialize_style_profile(FakeUser()) == {
        "note_style_preset": "concise",
        "preferred_focus": "plan_driven",
        "include_bullets_in_plan": True,
        "include_patient_friendly_language": False,
    }


def test_overrides_layer_over_user_defaults():
    class FakeUser:
        note_style_preset = "detailed"
        preferred_focus = "general"
        include_bullets_in_plan = False
        include_patient_friendly_language = False

    resolved = resolve_style_profile(
        user=FakeUser(),
        overrides={"preferred_focus": "assessment_driven", "include_bullets_in_plan": True},
    )
    assert resolved["note_style_preset"] == "detailed"  # untouched
    assert resolved["preferred_focus"] == "assessment_driven"  # overridden
    assert resolved["include_bullets_in_plan"] is True  # overridden


def test_none_valued_overrides_are_ignored():
    resolved = resolve_style_profile(
        user=None,
        overrides={"note_style_preset": None, "preferred_focus": "symptom_driven"},
    )
    assert resolved["note_style_preset"] == DEFAULT_STYLE_PROFILE["note_style_preset"]
    assert resolved["preferred_focus"] == "symptom_driven"


def test_invalid_override_values_normalise_instead_of_raising():
    resolved = resolve_style_profile(user=None, overrides={"note_style_preset": "chaotic"})
    assert resolved["note_style_preset"] == DEFAULT_STYLE_PROFILE["note_style_preset"]
