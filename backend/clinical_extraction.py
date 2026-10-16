"""
Structured clinical extraction layer.

Builds an intermediate representation from the transcript before SOAP note
generation so downstream prompts are grounded in normalized clinical facts
instead of raw conversational text alone.
"""
from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone

from dotenv import load_dotenv

load_dotenv()

try:
    from groq import Groq
except ImportError:  # pragma: no cover
    Groq = None  # type: ignore

from groq_client import chat_json
from clinical_assertions import is_active_patient_finding
from transcript_facts import classify_encounter_type, parse_clinician, parse_date_of_birth


def extract_clinical_representation(
    transcription: str,
    categorized_entities: dict,
    encounter_type: str | None = None,
) -> dict:
    """
    Return a normalized intermediate clinical representation.

    Prefer LLM extraction when available, but always fall back to local
    heuristics so the pipeline keeps working without network/API access.
    """
    try:
        structured = _extract_with_groq(transcription, categorized_entities)
        return _postprocess_representation(structured, transcription, categorized_entities, encounter_type)
    except Exception as exc:
        print(f"Structured extraction via Groq failed: {exc}")
        return _postprocess_representation(
            _extract_with_rules(transcription, categorized_entities),
            transcription,
            categorized_entities,
            encounter_type,
        )


def _extract_with_groq(transcription: str, categorized_entities: dict) -> dict:
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key or Groq is None:
        raise EnvironmentError("No Groq client/API key available for structured extraction.")

    patient = _extract_patient_details(transcription)
    user_message = (
        f"Transcript:\n{transcription}\n\n"
        f"Patient metadata:\n{json.dumps(patient, indent=2)}\n\n"
        f"Categorized entities:\n{json.dumps(_compact_entities(categorized_entities), indent=2)}\n\n"
        "Return the structured representation as JSON."
    )

    # Shares the SOAP generator's Groq helper so both stages get the same JSON
    # response format, brace-extraction fallback and token budget. This call was
    # capped at 1400 tokens with no response format and truncated on any
    # reasonably detailed encounter, silently dropping the whole run back to the
    # rules-only representation.
    return chat_json(
        _STRUCTURED_EXTRACTION_PROMPT,
        user_message,
        max_tokens=3000,
        temperature=0.1,
    )


def _extract_with_rules(transcription: str, categorized_entities: dict) -> dict:
    """
    Deterministic fallback representation, used when the LLM extractor is
    unavailable and merged into its output as a floor when it is.

    This function reports what the transcript and the entity extractor already
    contain. It does not infer clinical content. The previous implementation
    did: it carried hardcoded diabetes and pericarditis bundles (a fixed
    five-item monitoring list, a DESMOND referral, "concerns influenced by
    colleague's experience"), all keyed off literal phrases from two demo
    recordings, and emitted them for any transcript containing the word
    "diabetes". Those were removed in the Phase 0 de-overfitting pass;
    condition-specific reasoning belongs to the LLM path, which has the
    transcript in front of it.
    """
    text_lower = transcription.lower()
    patient = _extract_patient_details(transcription)
    clinician = _extract_clinician_details(transcription)
    encounter_type = classify_encounter_type(transcription)

    # Assertion state decides which bucket a mention belongs in. A denied
    # symptom is a negative finding, a relative's diagnosis is family history,
    # and a childhood illness is not an active problem — collapsing all three
    # into one list is how "denies chest pain" became a presenting complaint.
    symptoms = _split_by_assertion(categorized_entities.get("symptoms", []))
    conditions = _split_by_assertion(categorized_entities.get("conditions", []))
    procedures = _dedupe_texts(categorized_entities.get("procedures", []))
    medications = _split_by_assertion(categorized_entities.get("medications", []))

    return {
        "patient": patient,
        "encounter": {
            "type": encounter_type,
            "setting": "primary_care" if "gp surgery" in text_lower else None,
            "history_only": True,
            "clinician_name": clinician.get("name"),
            "clinician_role": clinician.get("role"),
            "visit_reason": None,
            "diagnosis_known_before_visit": None,
        },
        "subjective_data": {
            # Ideas, concerns and expectations are genuinely hard to detect
            # lexically, and guessing them puts words in the patient's mouth.
            # Left to the LLM extractor.
            "current_symptoms": symptoms["active"],
            "historical_symptoms": symptoms["historical"],
            "denied_symptoms": symptoms["denied"],
            "family_history": sorted(set(symptoms["family"] + conditions["family"])),
            "ideas": [],
            "concerns": [],
            "expectations": [],
            "emotional_response": [],
        },
        "objective_data": {
            "tests_reviewed": [],
            "tests_referenced_only": procedures,
            "measurements_documented": [],
            "results_missing": _results_referenced_without_values(transcription),
        },
        "assessment_context": {
            "confirmed_diagnoses": conditions["active"],
            "active_differential_targets": conditions["uncertain"],
            "historical_manifestations": conditions["historical"],
            "denied_diagnoses": conditions["denied"],
            "discussed_future_risks": [],
            "psychosocial_factors": [],
            "health_literacy": None,
        },
        "plan_context": {
            "education_provided": _education_techniques_used(text_lower),
            "medications_actively_discussed": medications["hypothetical"],
            "medications_currently_taken": medications["active"],
            "monitoring_to_arrange": [],
            "referrals_to_consider": [],
            "follow_up_needs": [],
            "safety_netting": _safety_netting_offered(text_lower),
        },
        "history_gaps": _generic_history_gaps(text_lower),
    }


# Results are "referenced without values" when the transcript talks about a
# test having happened but never states a number. Detected structurally — the
# test name comes from the transcript, not from a hardcoded list.
_RESULT_REFERENCE = re.compile(
    r"\b(blood test|blood tests|test results|results|scan|x-?ray|biopsy|swab|"
    r"hba1c|ecg|ekg|bloods)\b",
    flags=re.IGNORECASE,
)
_NUMERIC_VALUE = re.compile(r"\b\d+(?:\.\d+)?\s*(?:%|mmol|mg|mmhg|bpm|kg|cm|units?)?\b", re.IGNORECASE)


def _results_referenced_without_values(transcription: str) -> list[str]:
    """Name any test the transcript refers to without ever stating a value.

    Sentence-scoped so a number elsewhere in the transcript does not count as
    that test's result.
    """
    referenced: list[str] = []
    for sentence in re.split(r"(?<=[.?!])\s+", transcription):
        matches = _RESULT_REFERENCE.findall(sentence)
        if not matches:
            continue
        if _NUMERIC_VALUE.search(sentence):
            continue
        referenced.extend(match.lower() for match in matches)
    return _dedupe_strings(referenced)


# Generic consultation techniques, not conditions: these describe *how* the
# clinician communicated, and apply to any specialty.
_EDUCATION_TECHNIQUES = (
    ("summaris", "Teach-back used to confirm patient understanding."),
    ("summariz", "Teach-back used to confirm patient understanding."),
    ("does that make sense", "Understanding checked during the explanation."),
    ("leaflet", "Written information provided."),
    ("write that down", "Written information provided."),
)

_SAFETY_NETTING_PHRASES = (
    "give us a call",
    "book in to speak",
    "come back if",
    "come straight back",
    "get in touch if",
    "ring the surgery",
    "call 999",
    "go to a and e",
)


def _education_techniques_used(text_lower: str) -> list[str]:
    return _dedupe_strings(
        [description for marker, description in _EDUCATION_TECHNIQUES if marker in text_lower]
    )


def _safety_netting_offered(text_lower: str) -> list[str]:
    if any(phrase in text_lower for phrase in _SAFETY_NETTING_PHRASES):
        return ["Advised to make contact or seek review if concerns persist or worsen."]
    return []


def _postprocess_representation(
    rep: dict,
    transcription: str,
    categorized_entities: dict,
    encounter_type: str | None = None,
) -> dict:
    heuristic_rep = _extract_with_rules(transcription, categorized_entities)
    patient = rep.setdefault("patient", {})
    encounter = rep.setdefault("encounter", {})
    subjective = rep.setdefault("subjective_data", {})
    objective = rep.setdefault("objective_data", {})
    assessment = rep.setdefault("assessment_context", {})
    plan = rep.setdefault("plan_context", {})

    extracted_patient = _extract_patient_details(transcription)
    for key, value in extracted_patient.items():
        patient.setdefault(key, value)
    for key, value in heuristic_rep.get("patient", {}).items():
        if patient.get(key) in (None, "", []):
            patient[key] = value

    extracted_clinician = _extract_clinician_details(transcription)
    for key, value in extracted_clinician.items():
        encounter.setdefault(f"clinician_{key}", value)
    for key, value in heuristic_rep.get("encounter", {}).items():
        if encounter.get(key) in (None, "", []):
            encounter[key] = value

    encounter["type"] = encounter_type or encounter.get("type") or classify_encounter_type(transcription)
    encounter.setdefault("history_only", True)

    for key in ("current_symptoms", "historical_symptoms", "denied_symptoms", "family_history",
                "ideas", "concerns", "expectations", "emotional_response"):
        subjective.setdefault(key, [])
    for key in ("tests_reviewed", "tests_referenced_only", "measurements_documented", "results_missing"):
        objective.setdefault(key, [])
    for key in ("confirmed_diagnoses", "active_differential_targets", "historical_manifestations",
                "denied_diagnoses", "discussed_future_risks", "psychosocial_factors"):
        assessment.setdefault(key, [])
    assessment.setdefault("health_literacy", None)
    for key in ("education_provided", "medications_actively_discussed", "medications_currently_taken", "monitoring_to_arrange", "referrals_to_consider", "follow_up_needs", "safety_netting"):
        plan.setdefault(key, [])
    rep.setdefault("history_gaps", [])

    # Deduplicate list values while preserving order.
    for section in (subjective, objective, assessment, plan):
        for key, value in list(section.items()):
            if isinstance(value, list):
                section[key] = _dedupe_strings(value)

    for section_name in ("subjective_data", "objective_data", "assessment_context", "plan_context"):
        target = rep.get(section_name, {})
        source = heuristic_rep.get(section_name, {})
        for key, value in source.items():
            if isinstance(value, list):
                # `target[key]` came from the LLM and is only *usually* a list;
                # concatenating a dict to a list raised and lost the entire
                # structured representation over one off-schema field.
                target[key] = _dedupe_strings(_as_list(target.get(key)) + value)
            elif target.get(key) in (None, "", []):
                target[key] = value

    rep["history_gaps"] = _dedupe_strings(
        _as_list(rep.get("history_gaps")) + heuristic_rep.get("history_gaps", [])
    )
    rep["source_entities"] = _compact_entities(categorized_entities)
    rep["structured_at"] = datetime.now(timezone.utc).isoformat()
    return rep


def _extract_patient_details(transcription: str) -> dict:
    details = {
        "name": None,
        "date_of_birth": None,
        "age_years": None,
    }
    name_match = re.search(
        r"(?:it's|it is)\s+([A-Z][a-z]+(?:,\s*[A-Z][a-z]+)?(?:\s+[A-Z][a-z]+)?)",
        transcription,
    )
    if name_match:
        name = name_match.group(1).replace(",", " ").strip()
        parts = name.split()
        if len(parts) >= 2 and parts[0].lower() == parts[1].lower():
            parts = parts[1:]
        details["name"] = " ".join(parts)

    dob, age = parse_date_of_birth(transcription)
    details["date_of_birth"] = dob
    details["age_years"] = age

    return details


def _extract_clinician_details(transcription: str) -> dict:
    return parse_clinician(transcription)


def _split_by_assertion(entities: list[dict]) -> dict[str, list[str]]:
    """Bucket entity texts by what each mention asserts.

    Buckets are mutually exclusive apart from `uncertain`, which overlays the
    others: "possible pericarditis" is both an active finding and an uncertain
    one, and the assessment needs to know both.
    """
    buckets: dict[str, list[str]] = {
        "active": [], "denied": [], "historical": [], "hypothetical": [], "family": [], "uncertain": [],
    }
    for entity in entities:
        text = entity.get("text", "")
        if not text:
            continue
        if entity.get("negated"):
            buckets["denied"].append(text)
        elif entity.get("experiencer") == "family":
            buckets["family"].append(text)
        elif entity.get("temporality") == "hypothetical":
            buckets["hypothetical"].append(text)
        elif entity.get("temporality") == "historical":
            buckets["historical"].append(text)
        else:
            buckets["active"].append(text)
        if entity.get("uncertain") and is_active_patient_finding(entity):
            buckets["uncertain"].append(text)

    return {name: _dedupe_strings(values) for name, values in buckets.items()}


def _compact_entities(categorized_entities: dict) -> dict:
    compact = {}
    for key, values in categorized_entities.items():
        if not values:
            continue
        rendered = []
        for item in values[:20]:
            text = item.get("text", "")
            if not text:
                continue
            # Carry the assertion into the string. This dict is serialised
            # straight into the extraction and generation prompts, so a bare
            # term here undoes the work the assertion pass just did.
            flags = []
            if item.get("negated"):
                flags.append("denied")
            if item.get("experiencer") == "family":
                flags.append("family history")
            if item.get("temporality") in ("historical", "hypothetical"):
                flags.append(item["temporality"])
            if item.get("uncertain"):
                flags.append("uncertain")
            rendered.append(f"{text} ({', '.join(flags)})" if flags else text)
        compact[key] = rendered
    return compact


def _dedupe_texts(values: list[dict]) -> list[str]:
    return _dedupe_strings([item.get("text", "") for item in values if item.get("text")])


def _as_text(value) -> str:
    """Coerce whatever the extractor returned into a readable string.

    The prompt asks for strings; models sometimes answer with objects or nested
    lists. Rendering them beats crashing the stage, which previously discarded
    the entire LLM representation over one malformed field.
    """
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        return "; ".join(f"{key}: {_as_text(item)}" for key, item in value.items() if item)
    if isinstance(value, (list, tuple, set)):
        return ", ".join(filter(None, (_as_text(item) for item in value)))
    return "" if value is None else str(value)


def _as_list(value) -> list:
    """Coerce a field the model should have returned as a list into one.

    Mirrors `_as_text`: an off-schema value is rendered rather than raised on,
    because losing the whole representation costs far more than one odd field.
    """
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, (tuple, set)):
        return list(value)
    if isinstance(value, dict):
        return [f"{key}: {_as_text(item)}" for key, item in value.items() if item]
    return [value]


def _dedupe_strings(values: list) -> list[str]:
    seen = set()
    deduped = []
    for value in values:
        normalized = _as_text(value).strip()
        if not normalized:
            continue
        lowered = normalized.lower()
        if lowered in seen:
            continue
        seen.add(lowered)
        deduped.append(normalized)
    return deduped


def _generic_history_gaps(text_lower: str) -> list[str]:
    """Standard history components that were never raised in the recording.

    These are the components a clinician is expected to cover in any
    consultation, so the check generalises. The condition-specific gap
    ("relief on leaning forward was not explored") was removed in the Phase 0
    de-overfitting pass.
    """
    gaps = []

    if "allerg" not in text_lower:
        gaps.append("Allergies not elicited in this recording.")
    if "medication" not in text_lower and "taking any" not in text_lower and "tablets" not in text_lower:
        gaps.append("Current medications not elicited in this recording.")
    if not any(term in text_lower for term in ["past medical history", "pmh", "medical problems", "medical history"]):
        gaps.append("Past medical history not elicited in this recording.")
    if "surgery" not in text_lower and "operation" not in text_lower and "surgical" not in text_lower:
        gaps.append("Surgical history not elicited in this recording.")
    if "smok" not in text_lower and "alcohol" not in text_lower and "drugs" not in text_lower:
        gaps.append("Social history not elicited in this recording.")
    if "family history" not in text_lower and "runs in the family" not in text_lower:
        gaps.append("Family history not elicited in this recording.")

    return gaps



_STRUCTURED_EXTRACTION_PROMPT = """You are a clinical information extraction assistant.
Return ONLY valid JSON. Do not write prose outside the JSON.

Extract a grounded intermediate representation from the transcript.
Rules:
- Do not invent facts not supported by the transcript.
- Separate active current problems from historical manifestations and from
  future risks merely discussed during counselling.
- Separate medications currently taken from medications mentioned only as part
  of education or explanation.
- If the encounter is counselling/education rather than acute workup, reflect
  that in encounter.type and keep active_differential_targets empty unless the
  transcript clearly discusses current diagnostic uncertainty.
- If test results are referenced but not actually reviewed in detail, place
  them in tests_referenced_only/results_missing, not tests_reviewed.
- Use concise clinician-readable strings.

Return JSON with these top-level keys exactly:
patient, encounter, subjective_data, objective_data, assessment_context,
plan_context, history_gaps
"""
