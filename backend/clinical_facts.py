"""The fact table: every clinical claim, with the transcript text that supports it.

The pipeline's central weakness has been that generation reads the raw
transcript and is trusted to stay faithful to it. Nothing structural stops the
model asserting a drug, a diagnosis or a vital sign the conversation never
contained, and the checks bolted on afterwards can only guess — the lexical
`_ungrounded_terms` proxy flags any medication in the note that is not in the
transcript, which cannot tell a fabricated prescription from a legitimately
proposed differential.

A fact table fixes that at the source rather than after it. Every clinical
statement becomes a row carrying the span of transcript that supports it, so
provenance exists *by construction*: a note rendered from these rows can cite
every claim, and a claim with no row is visibly unsupported rather than
plausibly worded.

Two producers, deliberately different in how much they are trusted:

**Entity-derived facts** are free and exact. The extraction pass already knows
each entity's character offsets and its assertion attributes, so the evidence
is the sentence it sits in — no model involved, nothing to verify.

**LLM-derived facts** cover what entities cannot: onset, severity, duration,
what the patient believes and fears, what was agreed. The model must return a
verbatim quote for every fact, and `_verify_evidence` checks that quote actually
occurs in the transcript. A fact whose citation cannot be located is marked
unverified and kept out of the note. That check is the whole point: it turns
"the model says so" into "the model says so and here is where".
"""

from __future__ import annotations

import os
import re
from dataclasses import asdict, dataclass, field
from typing import Any, Iterable

from rapidfuzz import fuzz

from clinical_assertions import DEFAULT_ASSERTIONS

# Fact types. Kept coarse on purpose: these are the distinctions that change
# where a fact belongs in a SOAP note, not a clinical ontology.
FACT_TYPES = (
    "symptom",
    "condition",
    "medication",
    "test",
    "procedure",
    "finding",          # examination or measurement actually performed
    "allergy",
    "social",           # smoking, alcohol, occupation, living situation
    "family_history",
    "patient_concern",  # ideas, concerns and expectations
    "plan_action",      # what was agreed or arranged
    "demographic",
)

# A quote has to be close to verbatim, not identical: models normalise
# punctuation and casing, and ASR text is messy. Below this the citation is
# treated as invented rather than paraphrased.
MIN_EVIDENCE_SIMILARITY = 88.0

# The LLM pass can be switched off to get an entity-only table: useful for
# tests, for offline runs, and for measuring how much the model actually adds.
FACT_TABLE_LLM_ENABLED = os.getenv("FACT_TABLE_LLM", "1") not in ("0", "false", "False")

_WHITESPACE = re.compile(r"\s+")
_SENTENCE_SPLIT = re.compile(r"(?<=[.?!])\s+")


@dataclass
class ClinicalFact:
    """One clinical statement and the transcript text that supports it."""

    fact_type: str
    value: str
    evidence: str = ""
    evidence_start: int | None = None
    evidence_end: int | None = None
    # Assertion axes, carried through from the entity layer so a denied symptom
    # stays denied all the way to the note.
    negated: bool = False
    temporality: str = "current"
    experiencer: str = "patient"
    uncertain: bool = False
    source: str = "entity"          # entity | llm
    verified: bool = True           # evidence located in the transcript
    confidence: float = 0.0
    ontology: dict[str, Any] | None = None
    detail: str = ""                # onset, severity, duration and so on

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @property
    def is_assertable(self) -> bool:
        """True when this fact may be written into the note as fact.

        Unverified facts are withheld rather than deleted: they stay in the
        table so a reviewer can see what the model claimed and could not
        support.
        """
        return self.verified


def normalise(text: str) -> str:
    return _WHITESPACE.sub(" ", str(text)).strip()


def _normalise_for_match(text: str) -> str:
    return _WHITESPACE.sub(" ", re.sub(r"[^a-z0-9 ]", " ", str(text).lower())).strip()


# ── Evidence location ─────────────────────────────────────────────────────────

def locate_evidence(quote: str, transcript: str) -> tuple[int, int, float] | None:
    """Find `quote` in `transcript`, exactly or near enough.

    Returns `(start, end, similarity)` into the original transcript, or None.
    Exact match is tried first because it is both cheapest and strongest; the
    fuzzy pass exists because models reliably normalise punctuation and casing
    when quoting, and rejecting a citation over a comma would discard true facts.
    """
    quote = normalise(quote)
    if not quote or not transcript:
        return None

    index = transcript.find(quote)
    if index != -1:
        return index, index + len(quote), 100.0

    lowered_transcript = transcript.lower()
    index = lowered_transcript.find(quote.lower())
    if index != -1:
        return index, index + len(quote), 99.0

    # Fall back to the best-matching window of comparable length. Sentences are
    # the natural unit: a model quoting a transcript quotes an utterance.
    target = _normalise_for_match(quote)
    if not target:
        return None

    best: tuple[int, int, float] | None = None
    position = 0
    for sentence in _SENTENCE_SPLIT.split(transcript):
        start = transcript.find(sentence, position)
        if start == -1:
            start = position
        position = start + len(sentence)

        similarity = fuzz.partial_ratio(target, _normalise_for_match(sentence))
        if best is None or similarity > best[2]:
            best = (start, start + len(sentence), similarity)

    if best and best[2] >= MIN_EVIDENCE_SIMILARITY:
        return best
    return None


def _sentence_around(transcript: str, start: int, end: int) -> tuple[str, int, int]:
    """The sentence containing a span — the natural evidence unit for an entity."""
    left = max(
        transcript.rfind(delimiter, 0, start) for delimiter in (".", "?", "!", "\n")
    )
    sentence_start = 0 if left == -1 else left + 1

    candidates = [
        position
        for position in (
            transcript.find(delimiter, end) for delimiter in (".", "?", "!", "\n")
        )
        if position != -1
    ]
    sentence_end = min(candidates) + 1 if candidates else len(transcript)

    return normalise(transcript[sentence_start:sentence_end]), sentence_start, sentence_end


# ── Entity-derived facts ──────────────────────────────────────────────────────

_CATEGORY_TO_FACT_TYPE = {
    "symptom": "symptom",
    "condition": "condition",
    "medication": "medication",
    "procedure": "procedure",
}

# Entity labels the dictionary scan assigns that the category map does not cover.
_LABEL_TO_FACT_TYPE = {"TEST": "test"}


def facts_from_entities(entities: Iterable[dict[str, Any]], transcript: str) -> list[ClinicalFact]:
    """Turn extracted entities into facts, one per distinct assertion.

    Repeated mentions of the same term under the same assertion collapse into
    one fact — a transcript that says "chest pain" four times contains one
    finding, not four. Two mentions that assert *different* things (denied once,
    hypothetical later) stay separate, because that difference is the whole
    reason the assertion layer exists.
    """
    candidates: list[tuple[tuple, ClinicalFact]] = []

    for entity in entities:
        fact_type = _CATEGORY_TO_FACT_TYPE.get(entity.get("category", ""))
        if fact_type is None:
            fact_type = _LABEL_TO_FACT_TYPE.get(str(entity.get("label", "")).upper())
        if fact_type is None:
            continue

        value = normalise(entity.get("text", ""))
        if not value:
            continue

        if entity.get("experiencer") == "family":
            fact_type = "family_history"

        key = (
            fact_type,
            value.lower(),
            bool(entity.get("negated")),
            entity.get("temporality", "current"),
            entity.get("experiencer", "patient"),
        )

        start, end = int(entity.get("start", 0)), int(entity.get("end", 0))
        evidence, evidence_start, evidence_end = _sentence_around(transcript, start, end)

        candidates.append((key, ClinicalFact(
            fact_type=fact_type,
            value=value,
            evidence=evidence,
            evidence_start=evidence_start,
            evidence_end=evidence_end,
            negated=bool(entity.get("negated", DEFAULT_ASSERTIONS["negated"])),
            temporality=str(entity.get("temporality", DEFAULT_ASSERTIONS["temporality"])),
            experiencer=str(entity.get("experiencer", DEFAULT_ASSERTIONS["experiencer"])),
            uncertain=bool(entity.get("uncertain", False)),
            source="entity",
            verified=True,          # offsets came from the transcript itself
            confidence=float(entity.get("confidence", 0.0)),
            ontology=entity.get("ontology"),
        )))

    # Collapse repeated mentions of the same assertion, keeping the mention with
    # the best evidence. "Any headaches? Yes, most days" asserts one fact twice,
    # and the patient's answer is better support for it than the clinician's
    # question — a question cites what was asked, not what is true.
    chosen: dict[tuple, ClinicalFact] = {}
    for key, fact in candidates:
        existing = chosen.get(key)
        if existing is None or (_is_question(existing.evidence) and not _is_question(fact.evidence)):
            chosen[key] = fact

    facts = [fact for _, fact in candidates if chosen.get(_key_of(fact)) is fact]
    return _resolve_question_answer_pairs(facts)


def _key_of(fact: ClinicalFact) -> tuple:
    return (
        fact.fact_type,
        fact.value.lower(),
        fact.negated,
        fact.temporality,
        fact.experiencer,
    )


def _is_question(sentence: str) -> bool:
    return sentence.strip().endswith("?")


def _resolve_question_answer_pairs(facts: list[ClinicalFact]) -> list[ClinicalFact]:
    """Drop the clinician's question when the patient answered it.

    "Any nausea? No nausea at all." mentions nausea twice: the question asserts
    nothing, the answer denies it. Both become facts, and the un-negated one
    from the question then contradicts the real finding — it reaches the note as
    a present symptom the patient explicitly denied.

    A question is an enquiry, not an assertion, so where the same value appears
    in both an interrogative and a declarative sentence, the declarative wins. A
    term that is *only* ever asked about is kept: something was raised, and
    dropping it silently would lose that.
    """
    by_value: dict[tuple[str, str], list[ClinicalFact]] = {}
    for fact in facts:
        by_value.setdefault((fact.fact_type, fact.value.lower()), []).append(fact)

    resolved: list[ClinicalFact] = []
    for group in by_value.values():
        statements = [fact for fact in group if not _is_question(fact.evidence)]
        resolved.extend(statements or group)

    # Preserve the original ordering, which follows the transcript.
    order = {id(fact): index for index, fact in enumerate(facts)}
    return sorted(resolved, key=lambda fact: order[id(fact)])


# ── LLM-derived facts ─────────────────────────────────────────────────────────

FACT_EXTRACTION_PROMPT = """You are a clinical information extraction assistant.

Extract the clinical facts stated in the transcript. Return ONLY valid JSON:

{"facts": [{"fact_type": "...", "value": "...", "detail": "...", "evidence": "...",
            "negated": false, "temporality": "current", "experiencer": "patient",
            "uncertain": false}]}

fact_type must be one of: symptom, condition, medication, test, procedure,
finding, allergy, social, family_history, patient_concern, plan_action,
demographic.

Rules:
- `evidence` MUST be a VERBATIM quote copied from the transcript, word for word.
  Every fact is checked against the transcript and any fact whose quote cannot
  be found there is discarded. Do not paraphrase, summarise or reconstruct it.
- `value` is the fact in concise clinical language; `detail` holds qualifiers
  such as onset, duration, severity, radiation, frequency or dose.
- `negated` is true when the transcript states the finding is ABSENT.
- `temporality` is "historical" for resolved or past items, "hypothetical" for
  conditional or safety-netting mentions, otherwise "current".
- `experiencer` is "family" when the fact belongs to a relative, not the patient.
- `uncertain` is true when the fact is raised as possible rather than confirmed.
- Extract what was said. Do not infer diagnoses, add standard-of-care items, or
  record anything the transcript does not contain.
- A medication explained during education is NOT a medication the patient takes;
  record it only if the transcript says they take it.
"""


def parse_llm_facts(payload: dict[str, Any], transcript: str) -> list[ClinicalFact]:
    """Validate model-produced facts and locate each one's citation.

    A fact whose quote cannot be found in the transcript is kept with
    `verified=False` rather than dropped, so the failure is inspectable instead
    of invisible.
    """
    facts: list[ClinicalFact] = []

    for raw in payload.get("facts", []) or []:
        if not isinstance(raw, dict):
            continue
        value = normalise(raw.get("value", ""))
        fact_type = str(raw.get("fact_type", "")).strip().lower()
        if not value or fact_type not in FACT_TYPES:
            continue

        quote = normalise(raw.get("evidence", ""))
        located = locate_evidence(quote, transcript) if quote else None

        temporality = str(raw.get("temporality", "current")).lower()
        if temporality not in ("current", "historical", "hypothetical"):
            temporality = "current"
        experiencer = "family" if str(raw.get("experiencer", "")).lower() == "family" else "patient"

        facts.append(ClinicalFact(
            fact_type="family_history" if experiencer == "family" and fact_type in (
                "condition", "symptom") else fact_type,
            value=value,
            detail=normalise(raw.get("detail", "")),
            evidence=transcript[located[0]:located[1]] if located else quote,
            evidence_start=located[0] if located else None,
            evidence_end=located[1] if located else None,
            negated=bool(raw.get("negated", False)),
            temporality=temporality,
            experiencer=experiencer,
            uncertain=bool(raw.get("uncertain", False)),
            source="llm",
            verified=located is not None,
            confidence=round(located[2] / 100.0, 3) if located else 0.0,
        ))

    return facts


# ── Merging ───────────────────────────────────────────────────────────────────

def merge_facts(
    entity_facts: list[ClinicalFact],
    llm_facts: list[ClinicalFact],
) -> list[ClinicalFact]:
    """Combine both producers, preferring the entity-derived row on a clash.

    Entity facts carry exact offsets and assertion attributes resolved by
    ConText rather than by a model's self-report, so where both describe the
    same thing the entity row wins — but the model's `detail` (onset, severity,
    dose) is carried across, since that is exactly what entities cannot express.
    """
    merged: list[ClinicalFact] = list(entity_facts)
    index = {(fact.fact_type, fact.value.lower()): fact for fact in merged}

    for fact in llm_facts:
        key = (fact.fact_type, fact.value.lower())
        existing = index.get(key)
        if existing is None:
            merged.append(fact)
            index[key] = fact
            continue
        if fact.detail and not existing.detail:
            existing.detail = fact.detail

    return merged


def fact_table_summary(facts: list[ClinicalFact]) -> dict[str, Any]:
    """Counts for logging and for the API response."""
    assertable = [fact for fact in facts if fact.is_assertable]
    return {
        "total": len(facts),
        "assertable": len(assertable),
        "unverified": len(facts) - len(assertable),
        "from_entities": sum(1 for fact in facts if fact.source == "entity"),
        "from_llm": sum(1 for fact in facts if fact.source == "llm"),
        "negated": sum(1 for fact in assertable if fact.negated),
        "by_type": {
            fact_type: sum(1 for fact in assertable if fact.fact_type == fact_type)
            for fact_type in FACT_TYPES
            if any(fact.fact_type == fact_type for fact in assertable)
        },
    }


def render_for_prompt(facts: list[ClinicalFact]) -> str:
    """Render the assertable facts as the generator's input.

    Grouped by what each fact asserts rather than by clinical category, because
    the distinction that matters to a writer is "may I state this as present"
    — the same grouping the entity summary uses, applied to richer rows.
    """
    if not facts:
        return "No clinical facts extracted."

    buckets: dict[str, list[str]] = {
        "PRESENT": [], "DENIED": [], "HISTORICAL": [], "FAMILY": [],
        "HYPOTHETICAL": [], "UNCERTAIN": [],
    }

    for fact in facts:
        if not fact.is_assertable:
            continue
        line = f"[{fact.fact_type}] {fact.value}"
        if fact.detail:
            line += f" — {fact.detail}"
        if fact.ontology and fact.ontology.get("code"):
            line += f" ({fact.ontology['system']} {fact.ontology['code']})"
        line += f'  | evidence: "{fact.evidence[:160]}"'

        if fact.negated:
            buckets["DENIED"].append(line)
        elif fact.experiencer == "family" or fact.fact_type == "family_history":
            buckets["FAMILY"].append(line)
        elif fact.temporality == "hypothetical":
            buckets["HYPOTHETICAL"].append(line)
        elif fact.temporality == "historical":
            buckets["HISTORICAL"].append(line)
        elif fact.uncertain:
            buckets["UNCERTAIN"].append(line)
        else:
            buckets["PRESENT"].append(line)

    headings = {
        "PRESENT": "PRESENT — may be documented as current findings",
        "DENIED": "DENIED — the patient stated these are ABSENT; document as negatives only",
        "HISTORICAL": "HISTORICAL — past or resolved; not active problems",
        "FAMILY": "FAMILY HISTORY — a relative's, never the patient's own",
        "HYPOTHETICAL": "HYPOTHETICAL — conditional or safety-netting, not findings",
        "UNCERTAIN": "UNCERTAIN — raised as possible, not confirmed",
    }

    sections = [
        f"{headings[name]}:\n" + "\n".join(f"  {line}" for line in lines)
        for name, lines in buckets.items()
        if lines
    ]
    return "\n\n".join(sections)


def facts_to_json(facts: list[ClinicalFact]) -> list[dict[str, Any]]:
    return [fact.to_dict() for fact in facts]


# ── Orchestration ─────────────────────────────────────────────────────────────

def build_fact_table(
    transcript: str,
    entities: list[dict[str, Any]],
    *,
    use_llm: bool | None = None,
) -> list[ClinicalFact]:
    """Build the fact table for one encounter.

    Entity facts are produced first and unconditionally: they need no model, so
    the table degrades to something real rather than to nothing when the LLM
    stage is unavailable. The model then adds what entities cannot express, and
    every one of its facts has to cite the transcript to survive.
    """
    facts = facts_from_entities(entities, transcript)

    if use_llm is None:
        use_llm = FACT_TABLE_LLM_ENABLED
    if not use_llm or not transcript.strip():
        return facts

    try:
        from groq_client import chat_json

        payload = chat_json(
            FACT_EXTRACTION_PROMPT,
            f"Transcript:\n{transcript}\n\nExtract the clinical facts as JSON.",
            max_tokens=4000,
            temperature=0.0,
        )
        llm_facts = parse_llm_facts(payload, transcript)
    except Exception as exc:
        print(f"LLM fact extraction failed, using entity facts only: {type(exc).__name__}: {exc}")
        return facts

    rejected = sum(1 for fact in llm_facts if not fact.verified)
    if rejected:
        # Worth saying out loud: this is the citation check doing its job, and a
        # high count means the model is inventing quotes.
        print(f"Fact table: {rejected}/{len(llm_facts)} LLM facts failed evidence verification")

    return merge_facts(facts, llm_facts)
