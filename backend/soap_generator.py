"""
SOAP note generation from categorized medical entities.

Primary path: an LLM via `groq_client` (see `GROQ_MODEL`) for clinical prose.
Fallback path: rule-based generation, if that call fails for any reason.

Model access and JSON handling live in `groq_client`, shared with the other
stages that call a model.
"""
from dotenv import load_dotenv
load_dotenv()

import json
import re
from datetime import datetime, timezone
from claim_verification import VerificationReport, verify_note
from documentation_style import DEFAULT_STYLE_PROFILE, resolve_style_profile
from groq_client import GROQ_MODEL, chat_json
from medical_categories import CONDITIONS, MEDICATIONS
from transcript_facts import classify_encounter_type, parse_clinician, parse_date_of_birth

INSUFFICIENT_SECTION_TEXT = "Not enough information in the recording to complete this section."

# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def generate_soap_note(
    transcription: str,
    categorized_entities: dict,
    clinical_representation: dict | None = None,
    style_profile: dict | None = None,
    fact_table: list | None = None,
) -> dict:
    """
    Generate a SOAP note from transcribed text and categorized medical entities.

    Attempts Groq generation first. If the API call fails for any
    reason (network error, invalid key, malformed JSON response, etc.) the
    function falls back to the rule-based generator so the rest of the
    pipeline always receives a valid SOAP dict.

    Args:
        transcription: Full transcription text.
        categorized_entities: Dict of entity lists keyed by category name
                              (symptoms, conditions, medications, procedures).

    Returns:
        Dict with keys: generated_at, subjective, objective, assessment, plan.
        Each section value is either a clinical prose string (Groq path) or
        a structured dict (fallback path) — the frontend handles both shapes.
    """
    resolved_style_profile = resolve_style_profile(overrides=style_profile or DEFAULT_STYLE_PROFILE)
    try:
        soap = _generate_with_groq(
            transcription,
            categorized_entities,
            clinical_representation,
            resolved_style_profile,
            fact_table,
        )
        soap = _validate_and_repair_soap_note(transcription, soap, clinical_representation or {})
        if resolved_style_profile["include_bullets_in_plan"]:
            soap["plan"] = _format_plan_with_bullets(str(soap.get("plan", "")))
        soap["generated_at"] = datetime.now().isoformat()
        soap["source"] = f"groq-{GROQ_MODEL}"
        soap["resolved_style_profile"] = resolved_style_profile
        print(f"SOAP note generated via Groq {GROQ_MODEL}")
        return soap
    except Exception as exc:
        print(f"Groq SOAP generation failed: {exc}")
        print("Falling back to rule-based SOAP generation")
        soap = _generate_fallback(
            transcription,
            categorized_entities,
            clinical_representation or {},
            resolved_style_profile,
        )
        soap = _validate_and_repair_soap_note(transcription, soap, clinical_representation or {})
        if resolved_style_profile["include_bullets_in_plan"]:
            soap["plan"] = _format_plan_with_bullets(str(soap.get("plan", "")))
        soap["generated_at"] = datetime.now().isoformat()
        soap["source"] = "rule-based-fallback"
        soap["resolved_style_profile"] = resolved_style_profile
        return soap


# ---------------------------------------------------------------------------
# Groq LLM path (see GROQ_MODEL)
# ---------------------------------------------------------------------------

def _build_entity_summary(categorized_entities: dict) -> str:
    """
    Render the categorized entities for the prompt, grouped by what each
    mention actually asserts.

    Assertion state is the difference between "reports chest pain" and "denies
    chest pain". Before assertion detection existed, both arrived at the model
    as the bare string "chest pain" under `Symptoms`, and the note asserted the
    symptom either way. Denied, historical, family and hypothetical mentions are
    therefore listed in their own blocks with explicit wording, never mixed into
    the active list.
    """
    label_map = {
        "symptoms": "Symptoms",
        "conditions": "Conditions / Diagnoses",
        "medications": "Medications",
        "procedures": "Procedures",
        "anatomical": "Anatomical Sites",
        "modifiers": "Clinical Modifiers",
    }

    active: list[str] = []
    denied: list[str] = []
    historical: list[str] = []
    hypothetical: list[str] = []
    family: list[str] = []
    uncertain: list[str] = []

    for key, label in label_map.items():
        entities = categorized_entities.get(key, [])
        if not entities:
            continue

        current_terms = []
        for entity in entities:
            text = entity.get("text", "")
            if not text:
                continue
            if entity.get("negated"):
                denied.append(text)
            elif entity.get("experiencer") == "family":
                family.append(text)
            elif entity.get("temporality") == "hypothetical":
                hypothetical.append(text)
            elif entity.get("temporality") == "historical":
                historical.append(text)
            else:
                current_terms.append(text)
            if entity.get("uncertain"):
                uncertain.append(text)

        if current_terms:
            active.append(f"{label}: {', '.join(_unique(current_terms))}")

    lines = list(active)
    for terms, heading in (
        (denied, "Explicitly DENIED by the patient (must not be documented as present)"),
        (historical, "Historical / resolved, not active problems"),
        (family, "Family history only (NOT the patient's own history)"),
        (hypothetical, "Mentioned hypothetically or conditionally, not as findings"),
        (uncertain, "Raised as possible or uncertain, not confirmed"),
    ):
        if terms:
            lines.append(f"{heading}: {', '.join(_unique(terms))}")

    return "\n".join(lines) if lines else "No specific entities extracted."


def _unique(values: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for value in values:
        key = value.strip().lower()
        if not key or key in seen:
            continue
        seen.add(key)
        ordered.append(value.strip())
    return ordered


# Keys the fact table now covers, or that exist for bookkeeping rather than for
# the writer. Dumping them costs prompt budget and adds nothing.
_REDUNDANT_REPRESENTATION_KEYS = frozenset({"source_entities", "structured_at"})


def _build_clinical_representation_summary(clinical_representation: dict | None) -> str:
    """Render the representation compactly.

    This used to be `json.dumps(..., indent=2)` of the whole structure —
    pretty-printed, including every empty list and a duplicate copy of the
    extracted entities. On a free-tier token budget that waste is not abstract:
    the pipeline makes about five model calls per note, and a run of four cases
    exhausted a 200,000 token daily quota. Empty values carry no instruction, so
    they are dropped.
    """
    if not clinical_representation:
        return "No structured clinical representation available."

    def prune(value):
        if isinstance(value, dict):
            pruned = {
                key: prune(item)
                for key, item in value.items()
                if key not in _REDUNDANT_REPRESENTATION_KEYS and item not in (None, "", [], {})
            }
            return {key: item for key, item in pruned.items() if item not in (None, "", [], {})}
        return value

    compact = prune(clinical_representation)
    if not compact:
        return "No structured clinical representation available."
    return json.dumps(compact, separators=(",", ":"))


def _build_style_profile_summary(style_profile: dict | None) -> str:
    resolved = resolve_style_profile(overrides=style_profile or DEFAULT_STYLE_PROFILE)
    preset = resolved["note_style_preset"]
    focus = resolved["preferred_focus"]

    instructions = []
    if preset == "concise":
        instructions.append("Keep each SOAP section concise and avoid unnecessary recap.")
    elif preset == "detailed":
        instructions.append("Provide fuller clinical detail where the transcript supports it.")
    else:
        instructions.append("Use a balanced professional SOAP style.")

    if focus == "symptom_driven":
        instructions.append("Emphasize HPI and subjective symptom organization.")
    elif focus == "assessment_driven":
        instructions.append("Emphasize diagnostic framing and clinical reasoning in assessment.")
    elif focus == "plan_driven":
        instructions.append("Emphasize actionability, follow-up, and next steps in plan.")

    if resolved["include_bullets_in_plan"]:
        instructions.append("Format the plan section using concise bullet-like lines where safe.")
    else:
        instructions.append("Keep the plan section in paragraph form unless clearer structure is needed.")

    if resolved["include_patient_friendly_language"]:
        instructions.append(
            "Where counselling language is already supported by the transcript, use clearer patient-friendly phrasing without simplifying diagnoses inaccurately."
        )

    return json.dumps({
        "resolved_style_profile": resolved,
        "generation_instructions": instructions,
    }, indent=2)


def _extract_patient_context(transcription: str, encounter_type: str | None = None) -> dict:
    """
    Pull lightweight structured context from the transcript to ground the prompt.

    ``encounter_type`` is supplied by the caller and is authoritative —
    ``POST /api/transcribe`` requires it, and it reaches here through the
    clinical representation. Classification from the transcript is only a
    fallback for callers that have nothing to pass.
    """
    context = {
        "patient_name": None,
        "date_of_birth": None,
        "calculated_age_years": None,
        "clinician_name": None,
        "clinician_role": None,
        "history_only_encounter": True,
        "encounter_type": encounter_type or classify_encounter_type(transcription),
        "current_date_utc": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
    }

    name_match = re.search(
        r"name and date of birth\?\s*([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)",
        transcription,
    )
    if name_match:
        context["patient_name"] = name_match.group(1).strip()

    dob, age = parse_date_of_birth(transcription)
    context["date_of_birth"] = dob
    context["calculated_age_years"] = age

    clinician = parse_clinician(transcription)
    context["clinician_name"] = clinician["name"]
    context["clinician_role"] = clinician["role"]

    return context


_SYSTEM_PROMPT = """You are a clinical documentation assistant that enhances
physician SOAP notes to documentation-grade quality. You operate as a
documentation enhancer: you structure and complete the note based on the
transcript, and you add standard-of-care items that are clinically implied
by the presentation only when the symptom pattern strongly supports them.
Do not default to an acute coronary syndrome pathway just because the words
"chest pain" appear.

You must first classify the encounter type from the transcript and prompt
metadata before writing anything. Common encounter types include:
- acute presentation / diagnostic workup
- follow-up review
- counselling / education visit
- medication review
- procedure visit
The SOAP note must be structurally aligned to the encounter type.

CRITICAL OUTPUT RULES:
- Return ONLY valid JSON with exactly four keys: subjective, objective,
  assessment, plan. No markdown fences, no preamble, no text outside the JSON.
- Never repeat the same clinical information across sections.
- Never fabricate patient-specific data (vitals, measurements, test results).
- If a SOAP section does not have enough evidence in the transcript to be
  completed safely, respond with exactly:
  "Not enough information in the recording to complete this section."
  Do not infer, assume, or fabricate clinical content for that section.
- If a specific data point is absent from the transcript but the section still
  has enough evidence to be completed safely, state it as
  "not documented in transcript."
- Normalise all medication names to standard formulary spelling
  (e.g. "lisinopril" not "lysinoprell", "atorvastatin" not "adervastatin").
  If a medication name is phonetically recognisable, correct it silently.
- If a date of birth and computed age are provided in the prompt metadata,
  use that age exactly and do not estimate a different age.
- The prompt metadata also includes the current UTC date. If age is provided,
  treat it as authoritative for that date.
- If patient name or DOB metadata are provided, include them in the opening
  demographics sentence of the Subjective section.
- If clinician name and role are clearly stated in the transcript metadata,
  include them briefly when helpful to orient the note.
- Never treat an educational explanation of a medication or hormone as proof
  that the patient is taking that medication.
- The extracted-entity block groups mentions by what they assert. Honour those
  groupings exactly: terms listed as explicitly denied must be documented as
  negative findings and never as present; terms listed as family history belong
  to a relative and must never become the patient's own history; terms listed as
  historical are resolved or past and must not be written as active problems;
  terms listed as hypothetical or uncertain must keep that hedging.
- Every Assessment item and every Plan action must be grounded in the actual
  purpose of the encounter, not just in diseases or complications mentioned
  during counselling.
- Never introduce medications, investigations, restrictions, or safety advice
  that cannot be traced to the transcript or to the leading diagnosis pattern
  that is strongly supported by the transcript.

SUBJECTIVE:
- Report only what the patient or clinician stated. Zero diagnostic
  interpretation or clinical reasoning in this section.
- Structure the HPI to cover all OPQRST elements for any chief complaint,
  but write as a single fluent clinical paragraph — do not mechanically
  label each element. The paragraph should read as an experienced clinician
  wrote it, not as a template being filled in.
- Begin the Subjective section with a demographics sentence including patient
  name, DOB, and age when available in prompt metadata.
- Cover: onset (when and how it started), triggering event if known,
  quality, radiation, severity (numeric scale if mentioned), timing
  (constant vs intermittent), provocation and palliation.
- Distinguish carefully between onset and progression. If the pain started
  suddenly but worsened gradually thereafter, say exactly that; do not collapse
  it into "gradual onset."
- For each OPQRST element genuinely absent from the transcript, incorporate
  a natural "not documented" statement within the prose rather than a
  labelled line. Example: "Aggravating and relieving factors were not
  documented." Do not say "onset not further documented" if onset was
  already stated — instead flag the triggering event specifically if unknown.
- Include associated symptoms, relevant past medical history, surgical
  history, medications, allergies, family history, and recent illness if
  mentioned.
- Explicitly capture Ideas, Concerns, and Expectations when the patient states
  them. These may be woven naturally into the paragraph, but all three must be
  present if available. If the patient explicitly has no idea what is causing
  the symptoms, state that clearly as the Ideas component.
- If the transcript establishes that an aggravating or relieving factor was
  asked about and the answer was effectively "no difference", document that
  finding rather than saying it was not documented.
- If standard history components such as PMHx, medications, allergies, social
  history, or family history were not asked about in the recording, explicitly
  state that they were "not elicited in this recording" rather than omitting
  them.
- Add a brief "history gaps identified" sentence when a key diagnostic question
  was not asked in the recording. For suspected pericarditis, explicitly note
  if forward-leaning relief was not explored.
- Do not create internal contradictions. Example: if the pain is worse when
  lying down but not worsened by walking/sitting, document positional worsening
  with no clear exertional trigger; do not say position has no effect.

OBJECTIVE:
- Report only measurable, observable findings. Zero diagnostic interpretation.
- If the audio is history-taking only and contains no examination or test
  results, state clearly that this recording captures history-taking only and
  objective findings are pending clinical examination/investigation.
- For counselling / education visits prompted by prior test results, explicitly
  state if the underlying result was referenced but not reviewed in detail in
  the transcript, for example HbA1c or blood test values not documented.
- List all vital signs mentioned. For each standard vital sign not in the
  transcript (heart rate, blood pressure, respiratory rate, oxygen
  saturation, temperature), state it as "not documented in transcript."
- Include ECG details only when an ECG is actually mentioned in the transcript
  or is clearly part of the active acute cardiac workup. Do not include ECG
  templating language in non-cardiac counselling encounters.
- Do not use phrases like "consistent with" or "indicative of" — those
  belong in Assessment only.
- Write as a single fluent clinical paragraph in third-person.

ASSESSMENT:
- Provide a prioritised numbered problem list from most to least urgent.
- For each problem: state the diagnosis using precise clinical terminology,
  then one sentence of reasoning drawn strictly from the S and O data.
  Use precision language scaled to the strength of evidence:
  "highly concerning for", "likely", "consistent with", "suspicious for."
- Match the diagnosis to the symptom pattern. For chest pain:
  pressure-like exertional radiating pain with diaphoresis supports ACS;
  sharp pleuritic positional pain after a recent viral illness in a young
  patient supports pericarditis. Family history alone must not override the
  actual pain pattern.
- If pericarditis is leading and troponin later proves elevated, state that
  myopericarditis should then be considered and cardiology input may be needed.
- When ranking a differential diagnosis lower, briefly state why. For example,
  if ACS is lower on the list, note the absence of classic pressure-like,
  exertional, radiating, or diaphoresis-associated features when supported by
  the transcript.
- Observe strict diagnostic taxonomy: never list a subtype parallel to its
  parent category. For ACS, the working diagnosis should specify the likely
  subtype (STEMI vs NSTEMI vs unstable angina) with the others as
  differential within that category.
- For high-risk chief complaints, include a brief differential of the two
  or three most important alternative diagnoses. When ranking alternatives
  lower, use "less likely given current symptom description" or "based on
  currently available information" — never imply exclusion based on absence
  of documentation, as undocumented does not mean absent.
- For counselling / education visits, do not force an acute differential list.
  Instead, assess the established diagnosis, clinically relevant historical
  manifestations, information gaps, health literacy, psychological response,
  and future risk counselling. Historical symptoms that appear to have led to
  diagnosis are not automatically active current problems.
- For diabetes counselling visits, recurrent thrush or urinary infections in
  the history should usually be framed as prior manifestations of
  hyperglycaemia rather than active infections, unless the transcript clearly
  indicates they are ongoing now.
- Do not list future complications discussed in counselling, such as
  neuropathy, retinopathy, or cardiovascular disease, as current differential
  diagnoses unless the transcript describes current features of them.
- Write as a structured paragraph with numbered problems. No bullet points.

PLAN:
- Address each numbered Assessment problem in order.
- State all actions directly and confidently. Do not label any action as
  "per standard protocol" — simply document the action as a clinician would.
- The plan must remain aligned to the leading assessment. Do not generate an
  ACS-only treatment bundle if the assessment favors pericarditis or another
  non-ACS cause.
- For suspected pericarditis, prefer ECG, troponin, CRP/ESR, FBC, and
  echocardiography, with first-line NSAID and colchicine treatment unless the
  transcript gives a reason not to. If pericarditis is the leading diagnosis,
  do not hedge vaguely with "if clinically appropriate."
- If medication dosing is not explicitly supported by the transcript or prompt
  metadata, say that dosing and duration are to be confirmed by the treating
  clinician rather than implying the prescription is complete.
- For pericarditis plans, explicitly mention gastroprotection if an NSAID is
  being used, for example PPI cover where appropriate.
- Include safety-netting for acute chest pain presentations, especially return
  precautions for worsening breathlessness, syncope, spreading pain, or general
  deterioration.
- Include rest and avoidance of strenuous exercise when the leading diagnosis
  is pericarditis or myopericarditis is being considered.
- Include a follow-up timeframe when clinically appropriate.
- For acute or high-risk presentations where ACS is genuinely the leading
  concern, include standard-of-care items clinically implied by the scenario:
  cardiac monitoring, IV access, serial ECGs, troponin and cardiac
  biomarkers, NPO status, supplemental oxygen if hypoxic, anticoagulation
  if indicated.
- Include medications with dose and route, investigations ordered,
  monitoring, disposition, urgency classification, patient counselling, and
  risk discussion where clinically relevant.
- For counselling / education visits, the plan should usually prioritise:
  education delivered, clarification of misconceptions, follow-up, baseline
  investigations still needed, routine monitoring, referrals, lifestyle advice,
  and safety-netting for unanswered questions.
- For a new diagnosis of diabetes discussed in primary care, do not escalate to
  insulin unless the transcript explicitly states insulin is already prescribed
  or initiation is being actively discussed. Do not advise rest or avoidance of
  exercise for routine diabetes counselling. Do not include NSAIDs,
  gastroprotection, colchicine, cardiac monitoring, or ECG/troponin workup
  unless the transcript genuinely supports those actions.
- Write as a single fluent clinical paragraph in third-person."""


_SECTION_REGEN_PROMPT = """You are a clinical documentation assistant performing
targeted SOAP section repair.

Return ONLY valid JSON with exactly one key matching the requested section
name: subjective, objective, assessment, or plan.

Rules:
- Rewrite ONLY the requested section.
- Any issue listed as "unsupported_claims" names statements the transcript does
  not support. Remove or correct exactly those statements. Do not delete
  surrounding content that was not flagged, and do not replace a flagged claim
  with a different unsupported one.
- Use the structured clinical representation as the primary grounding source.
- Do not introduce facts absent from the transcript/representation.
- Resolve the listed section issues directly.
- Keep the section aligned to the encounter type.
- Output a single fluent clinical paragraph unless the section truly lacks
  enough evidence, in which case return:
  "Not enough information in the recording to complete this section."
"""


def _generate_with_groq(
    transcription: str,
    categorized_entities: dict,
    clinical_representation: dict | None = None,
    style_profile: dict | None = None,
    fact_table: list | None = None,
) -> dict:
    """
    Call Groq API and parse the JSON response into a SOAP dict.

    Raises an exception if the API call fails or the response cannot be
    parsed as valid JSON with the required four keys — the caller catches
    this and falls back to rule-based generation.
    """
    entity_summary = _build_entity_summary(categorized_entities)
    patient_context = _extract_patient_context(
        transcription,
        (clinical_representation or {}).get("encounter", {}).get("type"),
    )
    structured_summary = _build_clinical_representation_summary(clinical_representation)
    style_summary = _build_style_profile_summary(style_profile)

    # The fact table leads, because every row in it carries the transcript span
    # that supports it. The transcript still follows, so the model can phrase
    # naturally and catch what extraction missed — constraining it to the table
    # alone trades hallucination for omission, which is not obviously a win and
    # is not a trade to make without measuring both.
    fact_section = ""
    if fact_table:
        from clinical_facts import render_for_prompt

        fact_section = (
            "Verified clinical facts. Each carries the transcript evidence that "
            "supports it; prefer these over your own reading of the transcript, "
            "and honour the grouping exactly.\n"
            f"{render_for_prompt(fact_table)}\n\n"
        )

    user_message = (
        f"{fact_section}"
        f"Transcript:\n{transcription}\n\n"
        f"Prompt metadata:\n{json.dumps(patient_context, indent=2)}\n\n"
        f"Structured clinical representation:\n{structured_summary}\n\n"
        f"Documentation style profile:\n{style_summary}\n\n"
        f"Extracted medical entities:\n{entity_summary}\n\n"
        "Generate the SOAP note as JSON."
    )

    soap = _normalize_soap_sections(
        chat_json(_SYSTEM_PROMPT, user_message, max_tokens=3000, temperature=0.3)
    )

    # Validate the four required keys are present.
    required_keys = {"subjective", "objective", "assessment", "plan"}
    missing = required_keys - soap.keys()
    if missing:
        raise ValueError(f"Groq response missing required SOAP keys: {missing}")

    return soap


def _regenerate_section_with_groq(
    section: str,
    transcription: str,
    current_soap: dict,
    clinical_representation: dict,
    section_issues: list[str],
) -> str:
    payload = {
        "requested_section": section,
        "current_section_text": current_soap.get(section, ""),
        "other_sections": {k: current_soap.get(k, "") for k in ("subjective", "objective", "assessment", "plan") if k != section},
        "section_issues": section_issues,
        "structured_clinical_representation": clinical_representation,
        "prompt_metadata": _extract_patient_context(
            transcription,
            clinical_representation.get("encounter", {}).get("type"),
        ),
    }
    parsed = chat_json(
        _SECTION_REGEN_PROMPT,
        f"Transcript:\n{transcription}\n\nRepair payload:\n{json.dumps(payload, indent=2)}",
        max_tokens=2000,
        temperature=0.1,
    )
    if section not in parsed:
        raise ValueError(f"Section regeneration response missing key: {section}")
    return str(parsed[section]).strip()


# ---------------------------------------------------------------------------
# Rule-based fallback path (preserved from original implementation)
# ---------------------------------------------------------------------------

def _generate_fallback(
    transcription: str,
    categorized_entities: dict,
    clinical_representation: dict | None = None,
    style_profile: dict | None = None,
) -> dict:
    """
    Rule-based SOAP generation used when the GPT call fails.
    Produces a structured dict rather than clinical prose — the frontend
    renders both shapes correctly.
    """
    symptoms = categorized_entities.get("symptoms", [])
    conditions = categorized_entities.get("conditions", [])
    medications = categorized_entities.get("medications", [])
    procedures = categorized_entities.get("procedures", [])
    resolved_style_profile = resolve_style_profile(overrides=style_profile or DEFAULT_STYLE_PROFILE)

    soap = {
        "generated_at": datetime.now().isoformat(),
        "source": "rule-based-fallback",
        "subjective": _fallback_subjective(transcription, symptoms, clinical_representation or {}),
        "objective": _fallback_objective(procedures, clinical_representation or {}),
        "assessment": _fallback_assessment(conditions, clinical_representation or {}),
        "plan": _fallback_plan(medications, procedures, clinical_representation or {}),
    }
    if resolved_style_profile["include_bullets_in_plan"]:
        soap["plan"] = _format_plan_with_bullets(str(soap["plan"]))
    return soap


def _format_plan_with_bullets(plan: str) -> str:
    sentences = _split_sentences(plan)
    if len(sentences) <= 1:
        return plan
    return "\n".join(f"- {sentence}" for sentence in sentences)


def _humanise_label(key: str) -> str:
    label = str(key).replace("_", " ").strip()
    return label[:1].upper() + label[1:] if label else label


def _flatten_section(value) -> str:
    """
    Render a section value as clinical prose.

    The rule-based fallback path builds sections as dicts (see
    `_fallback_assessment` / `_fallback_plan`). Those used to be coerced with
    `str()` downstream, so a fallback note was persisted, and displayed, as a
    raw Python dict repr like ``{'primary_diagnosis': 'heart attack', ...}``.
    Flattening here, before anything else touches the section, keeps that off
    the page.
    """
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        parts = []
        for key, item in value.items():
            text = _flatten_section(item)
            if not text:
                continue
            # A lone "note" key is the fallback's way of saying "nothing here".
            if key == "note" and len(value) == 1:
                return text
            parts.append(f"{_humanise_label(key)}: {text.rstrip('.')}")
        return ". ".join(parts) + "." if parts else ""
    if isinstance(value, (list, tuple, set)):
        return ", ".join(filter(None, (_flatten_section(v) for v in value)))
    return "" if value is None else str(value)


def _normalize_soap_sections(soap: dict) -> dict:
    """
    Ensure all SOAP sections are present, flattened to prose, and never empty.
    This keeps the frontend output deterministic for sparse recordings.
    """
    for section in ("subjective", "objective", "assessment", "plan"):
        value = soap.get(section)
        if value is None:
            soap[section] = INSUFFICIENT_SECTION_TEXT
        else:
            soap[section] = _flatten_section(value).strip() or INSUFFICIENT_SECTION_TEXT
    return soap


def _append_sentence(section_text: str, sentence: str) -> str:
    section_text = section_text.strip()
    sentence = sentence.strip()
    if not section_text:
        return sentence
    if sentence in section_text:
        return section_text
    if not section_text.endswith((".", "!", "?")):
        section_text += "."
    return f"{section_text} {sentence}"


def _cleanup_spacing(text: str) -> str:
    text = re.sub(r"\s{2,}", " ", text)
    text = re.sub(r"\s+([.,;:])", r"\1", text)
    return text.strip()


def _cleanup_numbered_assessment(text: str) -> str:
    text = re.sub(r"\b\d+\.\s*(?=\d+\.|$)", "", text)
    text = re.sub(r"\s{2,}", " ", text)
    return text.strip()


def _split_sentences(text: str) -> list[str]:
    return [sentence.strip() for sentence in re.split(r"(?<=[.?!])\s+", text.strip()) if sentence.strip()]


def _enforce_patient_context(subjective: str, transcription: str) -> str:
    context = _extract_patient_context(transcription)
    name = context.get("patient_name")
    dob = context.get("date_of_birth")
    age = context.get("calculated_age_years")

    if dob:
        subjective = re.sub(
            r"\bdate of birth not documented in transcript\b",
            f"DOB {dob}",
            subjective,
            flags=re.IGNORECASE,
        )

    if age is not None:
        subjective = re.sub(r"\b\d{1,3}-year-old\b", f"{age}-year-old", subjective)
        subjective = re.sub(
            rf"(,\s*a\s+{age}-year-old)(?:,\s*a\s+{age}-year-old)+",
            rf"\1",
            subjective,
            flags=re.IGNORECASE,
        )
        if name and dob and not re.search(re.escape(dob), subjective, flags=re.IGNORECASE):
            subjective = re.sub(
                re.escape(name),
                f"{name} (DOB {dob}), a {age}-year-old",
                subjective,
                count=1,
            )
        elif dob and age is not None and not re.search(rf"\bDOB\s+{re.escape(dob)}\b", subjective, flags=re.IGNORECASE):
            subjective = f"DOB {dob}. {subjective}"
    elif name and dob and "date of birth not documented" in subjective.lower():
        subjective = subjective.replace("date of birth not documented in transcript", f"DOB {dob}")
    return subjective


def _ensure_clinician_context(subjective: str, clinical_representation: dict) -> str:
    encounter = clinical_representation.get("encounter", {})
    clinician_name = encounter.get("clinician_name")
    clinician_role = encounter.get("clinician_role")
    if not clinician_name or clinician_name.lower() in subjective.lower():
        return subjective
    clinician_sentence = f"The consultation was conducted by {clinician_name}"
    if clinician_role:
        clinician_sentence += f", {clinician_role}"
    clinician_sentence += "."
    return _append_sentence(subjective, clinician_sentence)


def _ensure_history_gaps(subjective: str, clinical_representation: dict) -> str:
    history_gaps = clinical_representation.get("history_gaps", [])
    if not history_gaps:
        return subjective
    missing_gaps = [gap for gap in history_gaps if gap.lower() not in subjective.lower()]
    if not missing_gaps:
        return subjective
    if "history gaps identified" in subjective.lower():
        return _append_sentence(subjective, "Additional history gaps include " + "; ".join(missing_gaps[:5]) + ".")
    return _append_sentence(subjective, "History gaps identified include " + "; ".join(history_gaps[:5]) + ".")


# ---------------------------------------------------------------------------
# Generic text hygiene
#
# What used to live here was a ~270-line diagnosis-aware "consistency rules"
# layer: pericarditis and diabetes-counselling branches that appended fixed
# sentences, deleted every sentence matching /ECG|insulin|NSAID|troponin/, and
# in one case rewrote the word "sweating" to "poor diet". Those rules were
# fitted to two demo recordings and silently corrupted notes for every other
# encounter, so they were removed in the Phase 0 de-overfitting pass.
#
# Groundedness is now *detected* (see `_ungrounded_terms`) and handed to the
# regeneration prompt rather than patched over with regex deletion.
# ---------------------------------------------------------------------------

def _sentence_key(sentence: str) -> str:
    """Normalised form used to recognise a sentence we have already seen."""
    key = re.sub(r"[^a-z0-9 ]", " ", sentence.lower())
    return re.sub(r"\s+", " ", key).strip()


def _dedupe_repeated_sentences(text: str) -> str:
    """Drop sentences that repeat earlier content verbatim, ignoring case and
    punctuation. Applies to any section — no clinical vocabulary involved."""
    seen: set[str] = set()
    kept: list[str] = []
    for sentence in _split_sentences(text):
        key = _sentence_key(sentence)
        if not key or key in seen:
            continue
        seen.add(key)
        kept.append(sentence)
    return " ".join(kept)


def _normalise_for_match(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", " ", str(text).lower())).strip()


def _contains_phrase(haystack_normalised: str, phrase_normalised: str) -> bool:
    return f" {phrase_normalised} " in f" {haystack_normalised} "


# Medication and condition names are the terms whose fabrication carries real
# clinical risk, so those are the two dictionaries the groundedness check scans.
# Very short entries are excluded — they produce substring noise rather than
# signal.
_GROUNDING_TERMS: frozenset[str] = frozenset(
    _normalise_for_match(term)
    for term in (MEDICATIONS | CONDITIONS)
    if len(term) > 4
)


def _source_vocabulary(transcription: str, clinical_representation: dict) -> str:
    """Everything the note is allowed to be grounded in: the transcript plus the
    entity texts the extraction stage recovered from it."""
    parts = [transcription]
    for values in (clinical_representation.get("source_entities") or {}).values():
        if isinstance(values, list):
            parts.extend(str(value) for value in values)
    return _normalise_for_match(" ".join(parts))


def _ungrounded_terms(section_text: str, source_normalised: str) -> list[str]:
    """Medication/condition names asserted in a section that appear nowhere in
    the transcript or extracted entities.

    This is a lexical proxy for hallucination, not a proof of it — a note may
    legitimately name a drug class the transcript only implies. It is deliberately
    a *flag*, routed to the regeneration prompt, never an automatic deletion.
    Phase 3 replaces it with claim-level entailment checking.
    """
    section_normalised = _normalise_for_match(section_text)
    if not section_normalised:
        return []
    return sorted(
        term
        for term in _GROUNDING_TERMS
        if _contains_phrase(section_normalised, term)
        and not _contains_phrase(source_normalised, term)
    )


def _validate_and_repair_soap_note(transcription: str, soap: dict, clinical_representation: dict) -> dict:
    """
    Score the generated note, verify its claims against the transcript, and only
    then pay for LLM regeneration of the sections that are still weak.

    Order matters. Verification runs before repair so that a deterministic fix
    is never applied to a section that is about to be regenerated anyway, and
    every stage is accept-if-better: a repair or regeneration is kept only when
    it scores at least as well as what it replaced, judged the same way.
    """
    soap = _normalize_soap_sections(soap)

    # One extra model call per note. It is the only check that can see a claim
    # the transcript does not support but whose vocabulary it does contain.
    verification = verify_note(soap, transcription)
    if verification.ran:
        print(
            f"Claim verification: {len(verification.problems)}/{len(verification.claims)} "
            f"claims unsupported"
        )
    else:
        # Said out loud because the note is now scored by the weaker lexical
        # check. A degradation nobody is told about is how the decommissioned
        # model went unnoticed for months.
        print(f"Claim verification did not run ({verification.error}); falling back to lexical check")
    quality_report = _score_soap_quality(transcription, soap, clinical_representation, verification)

    if not quality_report["passes_threshold"]:
        repaired = _repair_soap_with_rules(
            transcription, dict(soap), clinical_representation, quality_report["section_issues"]
        )
        repaired = _normalize_soap_sections(repaired)
        # Scored against the same verification: the repairs only add facts the
        # representation already holds, so they cannot introduce a new claim.
        repaired_report = _score_soap_quality(
            transcription, repaired, clinical_representation, verification
        )
        if repaired_report["overall_score"] >= quality_report["overall_score"]:
            soap, quality_report = repaired, repaired_report

    if not quality_report["passes_threshold"]:
        print(f"SOAP validator flagged issues: {quality_report['section_issues']}")
        regenerated = _regenerate_weak_sections(
            transcription, soap, clinical_representation, quality_report
        )
        regenerated = _normalize_soap_sections(regenerated)

        # Regeneration rewrites prose, so its claims have to be judged afresh
        # rather than against the previous version's verdicts — but only if any
        # prose actually changed. Re-verifying an identical note is a wasted
        # call, and the token budget is tight enough that it matters.
        changed = any(
            str(regenerated.get(section, "")) != str(soap.get(section, ""))
            for section in ("subjective", "objective", "assessment", "plan")
        )
        regenerated_verification = (
            verify_note(regenerated, transcription) if changed else verification
        )
        regenerated_report = _score_soap_quality(
            transcription, regenerated, clinical_representation, regenerated_verification
        )
        if regenerated_report["overall_score"] >= quality_report["overall_score"]:
            soap = regenerated
            quality_report = regenerated_report
            verification = regenerated_verification

    soap["quality_report"] = quality_report
    soap["quality_score"] = quality_report["overall_score"]
    soap["verification"] = verification.to_dict()
    return soap


def _collect_section_issues(
    transcription: str,
    soap: dict,
    clinical_representation: dict,
    verification: VerificationReport | None = None,
) -> dict[str, list[str]]:
    """
    Structural and groundedness checks that hold for any encounter type.

    Deliberately contains no disease names. The previous implementation scored
    notes against checks derived from two demo recordings, so a note about an
    unrelated presentation scored full marks because none of the checks applied.
    Every check below asks a question that is answerable for any consultation:
    is the note internally consistent, does it use the facts the extraction
    stage found, and does it assert drugs or diagnoses the source never mentions.
    """
    patient = clinical_representation.get("patient", {})
    encounter = clinical_representation.get("encounter", {})
    objective_context = clinical_representation.get("objective_data", {})
    subjective_context = clinical_representation.get("subjective_data", {})
    history_gaps = clinical_representation.get("history_gaps", [])

    sections = {
        section: str(soap.get(section, "")).strip()
        for section in ("subjective", "objective", "assessment", "plan")
    }
    issues: dict[str, list[str]] = {section: [] for section in sections}

    source_normalised = _source_vocabulary(transcription, clinical_representation)

    # Groundedness is checked per claim when the verifier ran, and per term when
    # it did not. The lexical proxy cannot tell a fabricated prescription from a
    # proposed differential, so it is the fallback rather than the default — but
    # it is better than no check at all when there is no API key.
    verified = verification is not None and verification.ran
    if verified:
        for section, claims in verification.problems_by_section().items():
            if section in issues and claims:
                issues[section].append("unsupported_claims: " + "; ".join(claims[:3]))

    for section, text in sections.items():
        # A placeholder is the correct output when the transcript lacks the
        # evidence, so it is not scored as a defect. No other check can run
        # meaningfully against it either.
        if not text or text == INSUFFICIENT_SECTION_TEXT:
            continue

        if not verified:
            ungrounded = _ungrounded_terms(text, source_normalised)
            if ungrounded:
                issues[section].append("ungrounded_terms: " + ", ".join(ungrounded[:5]))

    # Cross-section repetition: the same sentence appearing in two sections is a
    # drafting defect regardless of what it says.
    seen_elsewhere: dict[str, str] = {}
    for section, text in sections.items():
        if not text or text == INSUFFICIENT_SECTION_TEXT:
            continue
        for sentence in _split_sentences(text):
            key = _sentence_key(sentence)
            if len(key.split()) < 6:
                continue
            if key in seen_elsewhere and seen_elsewhere[key] != section:
                issues[section].append("duplicated_across_sections")
                break
            seen_elsewhere.setdefault(key, section)

    subjective = sections["subjective"]
    if subjective and subjective != INSUFFICIENT_SECTION_TEXT:
        age = patient.get("age_years")
        dob = patient.get("date_of_birth")
        name = patient.get("name")
        known = [value for value in (name, dob) if value]
        if age is not None:
            known.append(f"{age}-year-old")
        if known and not any(str(value).lower() in subjective.lower() for value in known):
            issues["subjective"].append("missing_demographics")
        if age is not None and f"{age}-year-old" not in subjective and re.search(r"\b\d{1,3}-year-old\b", subjective):
            issues["subjective"].append("age_mismatch")
        clinician_name = encounter.get("clinician_name")
        if clinician_name and clinician_name.lower() not in subjective.lower():
            issues["subjective"].append("missing_clinician_context")
        if subjective_context.get("concerns") and not re.search(r"concern|worri|anxious", subjective, flags=re.IGNORECASE):
            issues["subjective"].append("missing_concerns")
        if subjective_context.get("expectations") and not re.search(r"would like|wants|expects|hoping", subjective, flags=re.IGNORECASE):
            issues["subjective"].append("missing_expectations")
        if history_gaps and not re.search(r"not elicited|not documented|history gap", subjective, flags=re.IGNORECASE):
            issues["subjective"].append("missing_history_gaps")

    objective = sections["objective"]
    if objective and objective != INSUFFICIENT_SECTION_TEXT:
        if encounter.get("history_only") and not re.search(
            r"history[- ]taking only|pending (?:clinical )?examination", objective, flags=re.IGNORECASE
        ):
            issues["objective"].append("missing_history_only_framing")
        missing_results = objective_context.get("results_missing") or []
        if missing_results and not re.search(r"not reviewed|not documented|not available", objective, flags=re.IGNORECASE):
            issues["objective"].append("missing_result_gap")

    assessment = sections["assessment"]
    problem_count = 0
    if assessment and assessment != INSUFFICIENT_SECTION_TEXT:
        problem_count = len(re.findall(r"(?:^|\s)\d+\.\s", assessment))
        if problem_count == 0:
            issues["assessment"].append("missing_problem_list")

    plan = sections["plan"]
    if plan and plan != INSUFFICIENT_SECTION_TEXT:
        if not re.search(r"follow[- ]?up|review in|reassess", plan, flags=re.IGNORECASE):
            issues["plan"].append("missing_follow_up")
        # A plan should say at least as much as the problem list it answers.
        if problem_count >= 2 and len(_split_sentences(plan)) < problem_count:
            issues["plan"].append("plan_shorter_than_problem_list")

    return issues


# Structural weight per section, summing to 100.
_SECTION_WEIGHTS = {"subjective": 25, "objective": 20, "assessment": 30, "plan": 25}

# Penalties are ordered by clinical consequence: asserting a drug or diagnosis
# the source never mentions costs the most.
_ISSUE_PENALTIES = {
    # A claim the transcript does not support is the most serious defect a note
    # can carry, so it costs more than the lexical proxy it replaced.
    "unsupported_claims": 15,
    "ungrounded_terms": 12,
    "age_mismatch": 10,
    "missing_problem_list": 10,
    "duplicated_across_sections": 6,
    "missing_demographics": 6,
    "missing_result_gap": 6,
    "plan_shorter_than_problem_list": 6,
    "missing_history_gaps": 5,
    "missing_history_only_framing": 5,
    "missing_concerns": 4,
    "missing_expectations": 4,
    "missing_follow_up": 4,
    "missing_clinician_context": 3,
}

# Provisional. This score measures structure and lexical groundedness, not
# clinical correctness, so the threshold is a drafting bar and not a safety bar.
# Phase 1 calibrates it against human-rated notes; Phase 3 replaces the
# groundedness proxy with claim-level entailment.
_QUALITY_PASS_THRESHOLD = 85.0


def _issue_penalty(issue: str) -> int:
    return _ISSUE_PENALTIES.get(issue.split(":", 1)[0].strip(), 4)


def _score_soap_quality(
    transcription: str,
    soap: dict,
    clinical_representation: dict,
    verification: VerificationReport | None = None,
) -> dict:
    section_issues = _collect_section_issues(
        transcription, soap, clinical_representation, verification
    )

    section_scores = {}
    for section, max_score in _SECTION_WEIGHTS.items():
        penalties = sum(_issue_penalty(issue) for issue in section_issues[section])
        section_scores[section] = max(0, max_score - penalties)

    overall_score = round(sum(section_scores.values()), 1)

    return {
        "overall_score": overall_score,
        "target_score": _QUALITY_PASS_THRESHOLD,
        "passes_threshold": overall_score >= _QUALITY_PASS_THRESHOLD,
        "section_scores": section_scores,
        "section_issues": section_issues,
        # Says whether groundedness was judged per claim or by the lexical
        # fallback, so a score can be read for what it actually checked.
        "groundedness_check": (
            "claim_entailment" if (verification and verification.ran) else "lexical_terms"
        ),
    }


def _regenerate_weak_sections(transcription: str, soap: dict, clinical_representation: dict, quality_report: dict) -> dict:
    updated = dict(soap)
    section_issues = quality_report.get("section_issues", {})
    section_scores = quality_report.get("section_scores", {})

    for section in ("subjective", "objective", "assessment", "plan"):
        issues = section_issues.get(section, [])
        score = section_scores.get(section, 0)
        # Nothing to fix: no scored issues and the section already scores full marks.
        if not issues and score >= _section_max_score(section):
            continue
        # The transcript genuinely lacks the evidence for this section — there is
        # nothing for a regeneration pass to work with, so leave the placeholder.
        if str(updated.get(section, "")).strip() == INSUFFICIENT_SECTION_TEXT:
            continue

        try:
            regenerated = _regenerate_section_with_groq(
                section,
                transcription,
                updated,
                clinical_representation,
                issues,
            )
            print(f"Regenerated {section} via Groq")
        except Exception as exc:
            print(f"Section regeneration via Groq failed for {section}: {exc}")
            regenerated = _regenerate_section_with_rules(section, transcription, clinical_representation)

        if regenerated:
            updated[section] = regenerated

    return updated


def _section_max_score(section: str) -> int:
    return _SECTION_WEIGHTS[section]


def _sentence_join(parts: list[str]) -> str:
    cleaned = [part.strip().rstrip(".") for part in parts if part and part.strip()]
    if not cleaned:
        return INSUFFICIENT_SECTION_TEXT
    return ". ".join(cleaned) + "."


def _regenerate_section_with_rules(section: str, transcription: str, clinical_representation: dict) -> str:
    """
    Deterministic last resort when LLM section regeneration is unavailable.

    Renders only what the clinical representation already holds. It states
    facts, it does not infer them — the disease-specific phrasing that used to
    live here ("historical manifestations likely related to hyperglycaemia",
    a diabetes-type sentence appended to every assessment) was removed in the
    Phase 0 de-overfitting pass.
    """
    patient = clinical_representation.get("patient", {})
    encounter = clinical_representation.get("encounter", {})
    subjective_data = clinical_representation.get("subjective_data", {})
    objective_data = clinical_representation.get("objective_data", {})
    assessment_context = clinical_representation.get("assessment_context", {})
    plan_context = clinical_representation.get("plan_context", {})
    history_gaps = clinical_representation.get("history_gaps", [])

    if section == "subjective":
        demographic = ""
        if patient.get("name"):
            demographic = patient["name"]
            if patient.get("date_of_birth"):
                demographic += f" (DOB {patient['date_of_birth']})"
            if patient.get("age_years") is not None:
                demographic += f", a {patient['age_years']}-year-old patient"
        clinician_name = encounter.get("clinician_name")
        intro_sentence = demographic
        if clinician_name:
            role_clause = f", {encounter['clinician_role']}" if encounter.get("clinician_role") else ""
            intro_sentence += f" was seen by {clinician_name}{role_clause}"
        if encounter.get("visit_reason"):
            intro_sentence += f" for {encounter['visit_reason'].rstrip('.').lower()}"
        parts = [
            intro_sentence,
            " ".join(subjective_data.get("emotional_response", [])),
            "Reported symptoms include " + "; ".join(subjective_data.get("historical_symptoms", []))
            if subjective_data.get("historical_symptoms") else "",
            "Ideas include " + "; ".join(subjective_data["ideas"]) if subjective_data.get("ideas") else "",
            "Concerns include " + "; ".join(subjective_data["concerns"]) if subjective_data.get("concerns") else "",
            "Expectations include " + "; ".join(subjective_data["expectations"]) if subjective_data.get("expectations") else "",
            "History gaps identified: " + "; ".join(history_gaps[:4]) if history_gaps else "",
        ]
        return _sentence_join(parts)

    if section == "objective":
        parts = [
            "This recording captures history-taking only and objective findings are pending clinical examination and investigation"
            if encounter.get("history_only") else "",
            "Tests referenced but not reviewed in detail include " + "; ".join(objective_data.get("tests_referenced_only", []))
            if objective_data.get("tests_referenced_only") else "",
            "Results not documented in transcript include " + "; ".join(objective_data.get("results_missing", []))
            if objective_data.get("results_missing") else "",
        ]
        return _sentence_join(parts)

    if section == "assessment":
        parts = []
        confirmed = assessment_context.get("confirmed_diagnoses", [])
        for index, diagnosis in enumerate(confirmed, start=1):
            parts.append(f"{index}. {diagnosis[:1].upper()}{diagnosis[1:]}: documented in the transcript")
        if assessment_context.get("historical_manifestations"):
            parts.append(
                "Historical features reported in the history include "
                + "; ".join(assessment_context["historical_manifestations"])
            )
        if assessment_context.get("psychosocial_factors"):
            parts.append("Psychosocial factors relevant to management include " + "; ".join(assessment_context["psychosocial_factors"]))
        return _sentence_join(parts)

    if section == "plan":
        parts = []
        for label, key in (
            ("Education provided today included", "education_provided"),
            ("Monitoring to arrange includes", "monitoring_to_arrange"),
            ("Referrals to arrange or consider include", "referrals_to_consider"),
            ("Follow-up needs include", "follow_up_needs"),
            ("Safety-netting provided:", "safety_netting"),
        ):
            if plan_context.get(key):
                parts.append(f"{label} " + "; ".join(plan_context[key]))
        return _sentence_join(parts)

    return INSUFFICIENT_SECTION_TEXT


def _repair_soap_with_rules(
    transcription: str,
    soap: dict,
    clinical_representation: dict,
    section_issues: dict[str, list[str]],
) -> dict:
    """
    Cheap deterministic repairs, attempted before paying for LLM regeneration.

    Repairs only ever *add* a fact the clinical representation already holds, or
    remove a verbatim duplicate. Nothing here deletes clinical content: the
    previous implementation stripped every sentence matching a fixed vocabulary
    (insulin, NSAIDs, troponin, ECG), which silently dropped true findings.
    Ungrounded terms are therefore not repaired here — they are left flagged so
    the regeneration prompt can address them with the transcript in hand.
    """
    subjective = str(soap.get("subjective", ""))
    objective = str(soap.get("objective", ""))
    assessment = str(soap.get("assessment", ""))
    plan = str(soap.get("plan", ""))

    subjective_issues = section_issues.get("subjective", [])
    objective_issues = section_issues.get("objective", [])

    if "age_mismatch" in subjective_issues or "missing_demographics" in subjective_issues:
        subjective = _enforce_patient_context(subjective, transcription)
    if "missing_clinician_context" in subjective_issues:
        subjective = _ensure_clinician_context(subjective, clinical_representation)
    if "missing_history_gaps" in subjective_issues:
        subjective = _ensure_history_gaps(subjective, clinical_representation)
    if "missing_concerns" in subjective_issues:
        concerns = clinical_representation.get("subjective_data", {}).get("concerns", [])
        if concerns:
            subjective = _append_sentence(subjective, "Concerns include " + "; ".join(concerns) + ".")
    if "missing_expectations" in subjective_issues:
        expectations = clinical_representation.get("subjective_data", {}).get("expectations", [])
        if expectations:
            subjective = _append_sentence(subjective, "Expectations include " + "; ".join(expectations) + ".")

    if "missing_history_only_framing" in objective_issues:
        objective = _append_sentence(
            objective,
            "This recording captures history-taking only; objective findings are pending clinical examination and investigation.",
        )
    if "missing_result_gap" in objective_issues:
        missing_results = clinical_representation.get("objective_data", {}).get("results_missing", [])
        if missing_results:
            objective = _append_sentence(
                objective,
                "Results not documented in the transcript include " + "; ".join(missing_results) + ".",
            )

    soap["subjective"] = _cleanup_spacing(_dedupe_repeated_sentences(subjective))
    soap["objective"] = _cleanup_spacing(_dedupe_repeated_sentences(objective))
    soap["assessment"] = _cleanup_numbered_assessment(_cleanup_spacing(_dedupe_repeated_sentences(assessment)))
    soap["plan"] = _cleanup_spacing(_dedupe_repeated_sentences(plan))
    return soap


def _fallback_subjective(transcription: str, symptoms: list, clinical_representation: dict) -> dict:
    symptom_list = [s["text"] for s in symptoms]
    patient = clinical_representation.get("patient", {})
    encounter = clinical_representation.get("encounter", {})
    subjective_data = clinical_representation.get("subjective_data", {})
    chief_complaint = (
        "Patient reports: " + ", ".join(symptom_list)
        if symptom_list
        else "No specific complaints documented."
    )
    return {
        "patient": patient.get("name") or "Not documented",
        "encounter_type": encounter.get("type") or "follow_up",
        "chief_complaint": chief_complaint,
        "symptoms": subjective_data.get("historical_symptoms") or symptom_list,
        "ideas": subjective_data.get("ideas", []),
        "concerns": subjective_data.get("concerns", []),
        "expectations": subjective_data.get("expectations", []),
        "symptom_count": len(symptom_list),
        "narrative": transcription.strip(),
    }


def _fallback_objective(procedures: list, clinical_representation: dict) -> dict:
    procedure_list = [p["text"] for p in procedures]
    objective_data = clinical_representation.get("objective_data", {})
    if not procedure_list and not objective_data:
        return {"note": INSUFFICIENT_SECTION_TEXT}
    findings = []
    for proc in procedure_list:
        if proc in ("vitals", "vital signs"):
            findings.append("Vital signs monitored")
        elif proc in ("monitor", "monitoring"):
            findings.append("Patient under observation")
        else:
            findings.append(f"{proc.title()} performed")
    return {
        "findings": findings if findings else ["No examination findings documented in transcript"],
        "procedures": objective_data.get("tests_referenced_only", procedure_list),
        "tests_reviewed": objective_data.get("tests_reviewed", []),
        "results_missing": objective_data.get("results_missing", []),
        "procedure_count": len(procedure_list),
    }


def _fallback_assessment(conditions: list, clinical_representation: dict) -> dict:
    condition_list = [c["text"] for c in conditions]
    assessment_context = clinical_representation.get("assessment_context", {})
    confirmed = assessment_context.get("confirmed_diagnoses", [])
    if not condition_list and not confirmed:
        return {"note": INSUFFICIENT_SECTION_TEXT}
    condition_list = confirmed or condition_list
    if condition_list:
        primary_diagnosis = condition_list[0]
        additional_diagnoses = condition_list[1:]
    else:
        primary_diagnosis = "Assessment pending further evaluation"
        additional_diagnoses = []
    return {
        "primary_diagnosis": primary_diagnosis,
        "additional_diagnoses": additional_diagnoses,
        "historical_manifestations": assessment_context.get("historical_manifestations", []),
        "future_risks_discussed": assessment_context.get("discussed_future_risks", []),
        "psychosocial_factors": assessment_context.get("psychosocial_factors", []),
        "health_literacy": assessment_context.get("health_literacy"),
        "all_conditions": condition_list,
        "condition_count": len(condition_list),
    }


def _fallback_plan(medications: list, procedures: list, clinical_representation: dict) -> dict:
    medication_list = [m["text"] for m in medications]
    procedure_list = [p["text"] for p in procedures]
    plan_context = clinical_representation.get("plan_context", {})
    encounter_type = clinical_representation.get("encounter", {}).get("type")
    plan_items = []
    if medication_list and encounter_type != "counselling_education":
        plan_items.append(f"Medications: {', '.join(medication_list)}")
    if procedure_list and encounter_type != "counselling_education":
        plan_items.append(f"Procedures: {', '.join(procedure_list)}")
    if plan_context.get("education_provided"):
        plan_items.append(f"Education: {'; '.join(plan_context['education_provided'])}")
    if plan_context.get("monitoring_to_arrange"):
        plan_items.append(f"Monitoring: {'; '.join(plan_context['monitoring_to_arrange'])}")
    if plan_context.get("follow_up_needs"):
        plan_items.append(f"Follow-up: {'; '.join(plan_context['follow_up_needs'])}")
    if not plan_items:
        return {"note": INSUFFICIENT_SECTION_TEXT}
    return {
        "treatment_plan": plan_items,
        "medications": plan_context.get("medications_currently_taken", medication_list),
        "medications_discussed": plan_context.get("medications_actively_discussed", []),
        "follow_up_procedures": procedure_list,
        "referrals_to_consider": plan_context.get("referrals_to_consider", []),
        "safety_netting": plan_context.get("safety_netting", []),
        "medication_count": len(medication_list),
        "follow_up": "Schedule follow-up appointment as needed",
    }


# ---------------------------------------------------------------------------
# Text formatting utility (kept for export / debug use)
# ---------------------------------------------------------------------------

def format_soap_note_text(soap_note: dict) -> str:
    """
    Format a SOAP note dict as readable plain text.
    Handles both the GPT string shape and the fallback dict shape.
    """
    lines = []
    lines.append("=" * 60)
    lines.append("SOAP NOTE")
    lines.append(f"Generated: {soap_note.get('generated_at', 'unknown')}")
    source = soap_note.get("source", "unknown")
    lines.append(f"Source: {source}")
    lines.append("=" * 60)
    lines.append("")

    for section in ("subjective", "objective", "assessment", "plan"):
        lines.append(f"{section.upper()}:")
        value = soap_note.get(section, "")
        if isinstance(value, str):
            # GPT path — plain prose paragraph
            lines.append(f"  {value}")
        elif isinstance(value, dict):
            # Fallback path — structured dict
            for k, v in value.items():
                if isinstance(v, list):
                    lines.append(f"  {k}: {', '.join(str(i) for i in v)}")
                else:
                    lines.append(f"  {k}: {v}")
        lines.append("")

    lines.append("=" * 60)
    return "\n".join(lines)
