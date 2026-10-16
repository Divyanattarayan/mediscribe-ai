"""Section flattening for the rule-based fallback path.

The fallback builds sections as dicts. Before this was handled, they reached
`_apply_clinical_consistency_rules`, which coerces with `str()` — so a fallback
note was persisted and shown as a raw Python dict repr.
"""

from soap_generator import INSUFFICIENT_SECTION_TEXT, _flatten_section, _normalize_soap_sections


def test_prose_passes_through_untouched():
    assert _flatten_section('Patient reports chest pain.') == 'Patient reports chest pain.'


def test_dict_becomes_prose_not_a_python_repr():
    out = _flatten_section({'primary_diagnosis': 'heart attack', 'condition_count': 2})
    assert '{' not in out and "'" not in out
    assert out == 'Primary diagnosis: heart attack. Condition count: 2.'


def test_lone_note_key_unwraps():
    assert _flatten_section({'note': INSUFFICIENT_SECTION_TEXT}) == INSUFFICIENT_SECTION_TEXT


def test_lists_are_comma_joined():
    assert _flatten_section({'medications': ['aspirin', 'atorvastatin']}) == 'Medications: aspirin, atorvastatin.'


def test_none_and_empty_fall_back_to_placeholder():
    soap = _normalize_soap_sections({'subjective': None, 'objective': '', 'assessment': {}, 'plan': '  '})
    assert all(v == INSUFFICIENT_SECTION_TEXT for v in soap.values())


def test_every_section_is_a_string_after_normalising():
    soap = _normalize_soap_sections({
        'subjective': 'prose',
        'objective': {'vitals': ['BP 142/88']},
        'assessment': {'note': 'nothing'},
        'plan': ['rest', 'review'],
    })
    assert all(isinstance(v, str) for v in soap.values())
    assert soap['objective'] == 'Vitals: BP 142/88.'
