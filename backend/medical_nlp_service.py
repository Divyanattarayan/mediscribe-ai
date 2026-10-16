"""Dedicated Medical Information Extraction Service for MediScribe AI.

Extracts structured clinical information from consultation transcripts:
- Symptoms (patient-reported complaints)
- Confirmed diagnoses and medical conditions
- Medication mentions vs. new prescriptions vs. discontinued therapies
- Explicit allergy mentions and reactions (with NKDA detection)
- Temporal durations and timing associated with clinical findings
- Positive findings vs. negative/denied findings
- Uncertain or ambiguous statements flagged for clinician review
- Clinical gaps / unconfirmed information without hallucinating missing data

Model architecture:
- Primary: spaCy pipeline with linguistic parsing (part-of-speech, dependency parsing, sentencizer)
- Specialized clinical gazetteers (RxNorm medications, conditions, symptoms, procedures)
- Contextual assertion resolution (NegEx-inspired scoping, uncertainty triggers, temporality)
- Transparent limitations documentation (not a replacement for clinical judgment)
"""

from __future__ import annotations

import logging
import os
import re
from typing import Any, Dict, List, Optional, Tuple

import spacy
from spacy.language import Language

from medical_categories import (
    CONDITIONS,
    MEDICATIONS,
    PROCEDURES,
    SYMPTOMS,
)

logger = logging.getLogger("mediscribe.medical_nlp")

AI_EXTRACTION_DISCLAIMER = (
    "AI-Generated Medical Extraction: This structured information is extracted using automated NLP techniques "
    "and linguistic analysis. It is NOT a clinical-grade diagnostic tool. Negation detection, assertion scoping, "
    "and entity boundaries may miss nuances, double negatives, or unusual phrasing. A licensed clinician must "
    "independently review and verify all findings."
)

MODEL_LIMITATIONS = [
    "General spaCy models (like en_core_web_sm) are not trained specifically on clinical records; medical entities are augmented with curated clinical gazetteers.",
    "Negation detection uses syntactic scoping and NegEx heuristics, which may not capture complex double negatives or long-distance clauses.",
    "Tamil-English or multilingual code-switching has not been calibrated on this extraction pipeline and requires thorough manual review.",
    "Dosage and timing associations are heuristic and must be checked against the clinician's prescription intent.",
    "Missing facts (e.g. unstated allergies or vitals) are recorded as gaps and are never fabricated.",
]

BIOMEDICAL_MODEL_INSTRUCTIONS = (
    "For specialized biomedical NER with scispaCy:\n"
    "1. Run: pip install scispacy\n"
    "2. Run: pip install https://s3-us-west-2.amazonaws.com/ai2-s2-scispacy/releases/v0.5.4/en_ner_bc5cdr_md-0.5.4.tar.gz\n"
    "The service will automatically detect and load en_ner_bc5cdr_md when installed."
)


# ── Negation and Assertion Trigger Sets ────────────────────────────────────────

NEGATION_FORWARD_TRIGGERS = (
    "denies", "denied", "denying", "no", "not", "without", "negative for",
    "no signs of", "no evidence of", "no complaint of", "no history of",
    "never had", "rules out", "ruled out", "free of", "cleared of",
    "declined", "unremarkable for", "not experiencing", "nothing like",
    "hasn't had", "haven't had", "does not report", "did not report",
)

NEGATION_BACKWARD_TRIGGERS = (
    "was ruled out", "is ruled out", "was negative", "is negative",
    "is denied", "was denied", "unremarkable", "not seen", "not observed",
)

UNCERTAINTY_TRIGGERS = (
    "possible", "possibly", "probable", "probably", "suspected", "suspect",
    "suspicious for", "consider", "rule out", "unclear if", "questionable",
    "borderline", "equivocal", "may have", "might have", "could be",
    "differential includes", "evaluating for", "presumed", "apparent",
)

HISTORICAL_TRIGGERS = (
    "history of", "past medical history", "pmh", "previously had", "prior",
    "in the past", "years ago", "months ago", "as a child", "childhood",
    "resolved", "formerly", "used to have", "status post", "s/p",
)

PRESCRIBED_TRIGGERS = (
    "prescribe", "prescribed", "prescribing",
    "starting on", "start on", "started on",
    "starting", "start", "started",
    "initiating", "initiate", "initiated",
    "let's begin", "let's start", "recommend starting",
    "increase dose to", "write a prescription for",
    "order", "ordering", "give", "given", "dispense",
    "am starting", "will start", "going to start",
)

DISCONTINUED_TRIGGERS = (
    "stop", "stopped", "stopping", "discontinue", "discontinued",
    "wean off", "taper off", "no longer taking", "switched from",
    "ceased", "held", "hold",
)

DURATION_REGEX = re.compile(
    r"\b(?:for|over|past|last|since)\s+(\d+\s*(?:to\s*\d+)?\s*(?:hours?|days?|weeks?|months?|years?))\b|"
    r"\b(\d+\s*(?:hours?|days?|weeks?|months?|years?))\s+(?:ago|duration|history)\b|"
    r"\b(since\s+(?:yesterday|this morning|last night|last week|last month))\b",
    re.IGNORECASE,
)

ALLERGY_MENTION_REGEX = re.compile(
    r"\b(?:allergic\s+to|allergy\s+to|allergies(?:\s*:|\s+to)?|reacts?\s+to)\s+([a-zA-Z0-9\s\-]+?)(?=[,;.\n]|and\s+has|$)",
    re.IGNORECASE,
)

NKDA_REGEX = re.compile(
    r"\b(?:nkda|no\s+known\s+drug\s+allergies|no\s+known\s+allergies|no\s+allergies|denies\s+(?:any\s+)?allergies)\b",
    re.IGNORECASE,
)


class MedicalNLPService:
    """Service encapsulating spaCy-driven clinical information extraction."""

    def __init__(self) -> None:
        self._nlp = self._load_pipeline()

    def _load_pipeline(self) -> Language:
        nlp = None
        # Try biomedical scispaCy model first
        try:
            nlp = spacy.load("en_ner_bc5cdr_md")
            logger.info("Loaded biomedical model: en_ner_bc5cdr_md")
        except Exception:
            pass

        # Try standard small English pipeline
        if nlp is None:
            try:
                nlp = spacy.load("en_core_web_sm")
                logger.info("Loaded standard pipeline: en_core_web_sm")
            except Exception:
                pass

        # Fallback to blank English pipeline
        if nlp is None:
            nlp = spacy.blank("en")
            logger.info("Loaded blank English pipeline")

        # Guarantee sentence boundaries are set on the document
        if not nlp.has_pipe("parser") and not nlp.has_pipe("senter") and not nlp.has_pipe("sentencizer"):
            nlp.add_pipe("sentencizer")

        return nlp


    @property
    def model_name(self) -> str:
        return self._nlp.meta.get("name", "unknown") if hasattr(self._nlp, "meta") else "blank_en"

    @property
    def is_biomedical(self) -> bool:
        return "bc5cdr" in self.model_name.lower() or "sci" in self.model_name.lower()

    def process_transcript(self, transcript: str) -> Dict[str, Any]:
        """
        Main entry point: Parse transcript and extract structured clinical information.
        Preserves original transcript text and returns clean structured JSON.
        """
        cleaned_transcript = (transcript or "").strip()
        if not cleaned_transcript:
            return {
                "success": False,
                "error": "Transcript is empty.",
                "original_transcript": "",
                "disclaimer": AI_EXTRACTION_DISCLAIMER,
                "symptoms": [],
                "medical_conditions": [],
                "medications": {"prescribed": [], "current_or_mentioned": [], "discontinued": []},
                "allergies": [],
                "positive_findings": [],
                "negative_findings": [],
                "uncertain_findings": [],
                "durations_and_timing": [],
                "missing_information": ["No transcript provided to analyze."],
                "model_info": self._get_model_info(),
            }

        doc = self._nlp(cleaned_transcript)

        # 1. Extract Allergies
        allergies, allergy_gaps = self._extract_allergies(cleaned_transcript)

        # 2. Extract Timing & Durations
        durations = self._extract_durations(cleaned_transcript)

        # 3. Extract Medical Concepts using linguistic sentence scoping
        symptoms = []
        conditions = []
        medications_prescribed = []
        medications_current = []
        medications_discontinued = []
        positive_findings = []
        negative_findings = []
        uncertain_findings = []

        # Process sentence by sentence for precise assertion scoping
        for sent in doc.sents:
            sent_text = sent.text
            sent_lower = sent_text.lower()

            # Find matching terms in sentence
            matches = self._find_medical_terms(sent_text, sent.start_char)

            for match in matches:
                term = match["text"]
                label = match["label"]
                start = match["start"]
                end = match["end"]

                # Determine assertions (negation, uncertainty, temporality)
                assertions = self._resolve_sentence_assertions(sent_text, start - sent.start_char, end - sent.start_char)

                # Associate duration if mentioned in this sentence
                matched_duration = self._find_closest_duration(durations, start, end)

                entity_record = {
                    "text": term,
                    "label": label,
                    "start": start,
                    "end": end,
                    "negated": assertions["negated"],
                    "uncertain": assertions["uncertain"],
                    "temporality": assertions["temporality"],
                    "experiencer": assertions["experiencer"],
                    "duration": matched_duration,
                    "context_sentence": sent_text.strip(),
                }

                # Route into specific clinical categories
                if assertions["negated"]:
                    negative_findings.append({
                        "finding": term,
                        "type": label,
                        "context": sent_text.strip(),
                        "assertion": "absent_or_denied",
                    })
                elif assertions["uncertain"]:
                    uncertain_findings.append({
                        "finding": term,
                        "type": label,
                        "cue": assertions.get("uncertain_cue", "ambiguous statement"),
                        "context": sent_text.strip(),
                        "requires_review": True,
                    })
                else:
                    positive_findings.append({
                        "finding": term,
                        "type": label,
                        "temporality": assertions["temporality"],
                        "duration": matched_duration,
                    })

                # Specific categorization
                if label == "SYMPTOM":
                    symptoms.append(entity_record)
                elif label == "CONDITION":
                    entity_record["is_confirmed_diagnosis"] = not assertions["uncertain"] and not assertions["negated"]
                    conditions.append(entity_record)
                elif label == "MEDICATION":
                    med_action = self._determine_medication_action(sent_lower, start - sent.start_char)
                    entity_record["action"] = med_action
                    dosage = self._extract_dosage(sent_text, start - sent.start_char, end - sent.start_char)
                    if dosage:
                        entity_record["dosage"] = dosage

                    if med_action == "prescribed":
                        medications_prescribed.append(entity_record)
                    elif med_action == "discontinued":
                        medications_discontinued.append(entity_record)
                    else:
                        medications_current.append(entity_record)

        # 4. Identify Gaps & Missing Information
        missing_info = self._detect_missing_information(
            cleaned_transcript,
            symptoms,
            conditions,
            allergy_gaps,
        )

        return {
            "success": True,
            "original_transcript": cleaned_transcript,
            "disclaimer": AI_EXTRACTION_DISCLAIMER,
            "model_info": self._get_model_info(),
            "positive_findings": self._dedupe_by_key(positive_findings, "finding"),
            "negative_findings": self._dedupe_by_key(negative_findings, "finding"),
            "uncertain_findings": self._dedupe_by_key(uncertain_findings, "finding"),
            "symptoms": self._dedupe_by_key(symptoms, "text"),
            "medical_conditions": self._dedupe_by_key(conditions, "text"),
            "medications": {
                "prescribed": self._dedupe_by_key(medications_prescribed, "text"),
                "current_or_mentioned": self._dedupe_by_key(medications_current, "text"),
                "discontinued": self._dedupe_by_key(medications_discontinued, "text"),
            },
            "allergies": allergies,
            "durations_and_timing": durations,
            "missing_information": missing_info,
        }

    def _get_model_info(self) -> Dict[str, Any]:
        return {
            "spacy_model": self.model_name,
            "is_biomedical": self.is_biomedical,
            "limitations": MODEL_LIMITATIONS,
            "biomedical_installation_instructions": BIOMEDICAL_MODEL_INSTRUCTIONS,
        }

    def _find_medical_terms(self, text: str, offset: int) -> List[Dict[str, Any]]:
        """Search text for medical terms from dictionaries using word-boundary matching."""
        matches = []
        text_lower = text.lower()

        # Dictionary lookups with precedence: CONDITIONS -> MEDICATIONS -> SYMPTOMS -> PROCEDURES
        categories = [
            ("CONDITION", CONDITIONS),
            ("MEDICATION", MEDICATIONS),
            ("SYMPTOM", SYMPTOMS),
            ("PROCEDURE", PROCEDURES),
        ]

        # Track matched character ranges to prevent duplicate overlapping substrings
        occupied_ranges: List[Tuple[int, int]] = []

        for label, term_set in categories:
            # Sort longest terms first so multi-word expressions match before individual words
            sorted_terms = sorted(term_set, key=len, reverse=True)
            for term in sorted_terms:
                term_lower = term.lower()
                # Build pattern that also matches common inflections (ed, ing, s, es)
                # e.g., "fatigue" matches "fatigued", "cough" matches "coughing"
                base_pattern = r"\b" + re.escape(term_lower) + r"(?:ed|ing|s|es|d)?\b"
                for m in re.finditer(base_pattern, text_lower):
                    start = m.start()
                    end = m.end()

                    # Check overlap with longer term
                    overlap = any(s <= start < e or s < end <= e for s, e in occupied_ranges)
                    if not overlap:
                        occupied_ranges.append((start, end))
                        # Normalise the matched text back to the canonical term form
                        matches.append({
                            "text": term,  # use canonical form (not inflected)
                            "label": label,
                            "start": offset + start,
                            "end": offset + end,
                        })

        return sorted(matches, key=lambda x: x["start"])

    def _resolve_sentence_assertions(self, sentence: str, term_start: int, term_end: int) -> Dict[str, Any]:
        """Determine negation, uncertainty, and temporality within a sentence."""
        before_text = sentence[:term_start].lower()
        after_text = sentence[term_end:].lower()

        # Check forward negation (before the term)
        negated = False
        neg_cue = None
        for trigger in NEGATION_FORWARD_TRIGGERS:
            # Ensure trigger occurs within recent tokens before the term
            pattern = r"\b" + re.escape(trigger) + r"\b[\w\s,]{0,40}$"
            if re.search(pattern, before_text):
                # Ensure no clause boundary intervening (e.g., "but", "however")
                between = re.search(pattern, before_text).group(0)
                if not re.search(r"\b(but|however|except|although|aside from)\b", between):
                    negated = True
                    neg_cue = trigger
                    break

        # Check backward negation (after the term)
        if not negated:
            for trigger in NEGATION_BACKWARD_TRIGGERS:
                pattern = r"^\s*(?:is|was|are|were)?\s*" + re.escape(trigger) + r"\b"
                if re.search(pattern, after_text):
                    negated = True
                    neg_cue = trigger
                    break

        # Check uncertainty
        uncertain = False
        uncertain_cue = None
        for trigger in UNCERTAINTY_TRIGGERS:
            pattern = r"\b" + re.escape(trigger) + r"\b"
            if re.search(pattern, before_text) or re.search(pattern, after_text[:30]):
                uncertain = True
                uncertain_cue = trigger
                break

        # Check temporality
        temporality = "current"
        for trigger in HISTORICAL_TRIGGERS:
            pattern = r"\b" + re.escape(trigger) + r"\b"
            if re.search(pattern, before_text) or re.search(pattern, after_text[:30]):
                temporality = "historical"
                break

        # Check experiencer (family vs patient)
        experiencer = "patient"
        if re.search(r"\b(my\s+(?:dad|mom|mum|mother|father|brother|sister|parent|uncle|aunt|family))\b", before_text):
            experiencer = "family"

        return {
            "negated": negated,
            "neg_cue": neg_cue,
            "uncertain": uncertain,
            "uncertain_cue": uncertain_cue,
            "temporality": temporality,
            "experiencer": experiencer,
        }

    def _determine_medication_action(self, sentence_lower: str, term_start: int) -> str:
        """Distinguish newly prescribed medications from existing or discontinued regimens."""
        before = sentence_lower[:term_start]
        after = sentence_lower[term_start:]

        # Discontinued check
        for trig in DISCONTINUED_TRIGGERS:
            if re.search(r"\b" + re.escape(trig) + r"\b", before) or re.search(r"\b" + re.escape(trig) + r"\b", after[:30]):
                return "discontinued"

        # Prescribed check
        for trig in PRESCRIBED_TRIGGERS:
            if re.search(r"\b" + re.escape(trig) + r"\b", before):
                return "prescribed"

        return "current_or_mentioned"

    def _extract_dosage(self, sentence: str, term_start: int, term_end: int) -> Optional[str]:
        """Extract medication dosage mentioned adjacent to a medication name."""
        window = sentence[max(0, term_start - 20):min(len(sentence), term_end + 30)]
        dosage_match = re.search(r"\b\d+(?:\.\d+)?\s*(?:mg|mcg|g|ml|tablets?|capsules?|pills?|units?|drops?)\b", window, re.IGNORECASE)
        return dosage_match.group(0) if dosage_match else None

    def _extract_allergies(self, text: str) -> Tuple[List[Dict[str, Any]], List[str]]:
        """Extract explicit allergy statements and detect NKDA."""
        allergies: List[Dict[str, Any]] = []
        gaps: List[str] = []

        # Check for explicit No Known Allergies
        if NKDA_REGEX.search(text):
            allergies.append({
                "allergen": "No Known Drug Allergies (NKDA)",
                "reaction": None,
                "negated": True,
                "note": "Patient explicitly confirmed no known allergies.",
            })
            return allergies, gaps

        # Check for specific allergy mentions
        for m in ALLERGY_MENTION_REGEX.finditer(text):
            allergen_text = m.group(1).strip()
            # Clean trailing punctuation
            allergen_text = re.sub(r"[,.;]+$", "", allergen_text)
            if allergen_text and len(allergen_text) > 2:
                # Check for reaction in same clause
                reaction = None
                # Search for a reaction clause in the wider sentence context
                # starting from the allergen match (handles "which causes", "causing", "resulting in")
                context_window = text[m.start():m.start() + 150]
                rx_match = re.search(
                    r"(?:which\s+)?(?:causes?|causing|with|resulting in|leads?\s+to|manifesting\s+as)\s+([a-zA-Z\s,]+?)(?=[.;\n]|$)",
                    context_window,
                    re.IGNORECASE,
                )
                if rx_match:
                    reaction = rx_match.group(1).strip().rstrip(",")

                allergies.append({
                    "allergen": allergen_text,
                    "reaction": reaction,
                    "negated": False,
                    "note": "Clinician must verify specific allergy details.",
                })

        if not allergies:
            gaps.append("Allergy status was not explicitly confirmed or denied in the dialogue.")

        return allergies, gaps

    def _extract_durations(self, text: str) -> List[Dict[str, Any]]:
        """Find duration and timing statements in the transcript."""
        durations = []
        for m in DURATION_REGEX.finditer(text):
            val = next(g for g in m.groups() if g is not None).strip()
            durations.append({
                "phrase": val,
                "start": m.start(),
                "end": m.end(),
            })
        return durations

    def _find_closest_duration(self, durations: List[Dict[str, Any]], term_start: int, term_end: int) -> Optional[str]:
        """Associate a duration phrase with a clinical term within a 60-character window."""
        for dur in durations:
            if abs(dur["start"] - term_end) <= 50 or abs(term_start - dur["end"]) <= 50:
                return dur["phrase"]
        return None

    def _detect_missing_information(
        self,
        transcript: str,
        symptoms: List[Dict[str, Any]],
        conditions: List[Dict[str, Any]],
        allergy_gaps: List[str],
    ) -> List[str]:
        """Highlight missing clinical documentation facts rather than fabricating them."""
        gaps: List[str] = list(allergy_gaps)
        text_lower = transcript.lower()

        # Check vitals
        vitals_terms = ["blood pressure", "bp", "pulse", "heart rate", "temperature", "temp", "oxygen saturation", "spo2"]
        if not any(v in text_lower for v in vitals_terms):
            gaps.append("Objective vital signs (BP, heart rate, temperature) were not documented in the encounter.")

        # Check symptom durations
        undated_symptoms = [s["text"] for s in symptoms if not s.get("duration") and not s.get("negated")]
        if undated_symptoms[:3]:
            gaps.append(f"Onset duration was not specified for reported symptoms: {', '.join(undated_symptoms[:3])}.")

        # Check lifestyle/social history
        if not any(t in text_lower for t in ["smoke", "smoking", "alcohol", "drinks", "diet", "exercise"]):
            gaps.append("Social history (smoking status, alcohol, physical activity) was not addressed.")

        return gaps

    def _dedupe_by_key(self, items: List[Dict[str, Any]], key: str) -> List[Dict[str, Any]]:
        seen = set()
        deduped = []
        for item in items:
            val = str(item.get(key, "")).lower()
            if val and val not in seen:
                seen.add(val)
                deduped.append(item)
        return deduped


# Global singleton instance
medical_nlp_service = MedicalNLPService()
