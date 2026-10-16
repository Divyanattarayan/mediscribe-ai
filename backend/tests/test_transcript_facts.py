"""Shared transcript parsing helpers."""

from datetime import datetime, timezone

import pytest

from transcript_facts import parse_clinician, parse_date_of_birth

_NOW = datetime(2026, 8, 30, tzinfo=timezone.utc)


@pytest.mark.parametrize(
    "text, expected_dob, expected_age",
    [
        ("my date of birth is 14/03/1979", "14/03/1979", 47),
        ("born on the 2nd of July 1990", "02/07/1990", 36),
        ("it was 5.11.2000 actually", "05/11/2000", 25),
        ("the 21st of the 4th 1968", "21/04/1968", 58),
    ],
)
def test_parse_date_of_birth_formats(text, expected_dob, expected_age):
    dob, age = parse_date_of_birth(text, now=_NOW)
    assert dob == expected_dob
    assert age == expected_age


def test_parse_date_of_birth_absent():
    assert parse_date_of_birth("no dates here at all") == (None, None)


def test_parse_date_of_birth_rejects_impossible_month():
    assert parse_date_of_birth("13/13/1990", now=_NOW) == (None, None)


def test_parse_date_of_birth_rejects_implausible_age():
    dob, age = parse_date_of_birth("01/01/1780", now=_NOW)
    assert dob == "01/01/1780"
    assert age is None


def test_parse_clinician_intro():
    text = "Hello, my name's Sarah, I'm one of the junior doctors working in the department."
    assert parse_clinician(text) == {"name": "Sarah", "role": "junior doctor"}


def test_parse_clinician_absent():
    assert parse_clinician("the patient walked in") == {"name": None, "role": None}
