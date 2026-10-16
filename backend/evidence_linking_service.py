"""Evidence-Linked SOAP Note Statements Service.

Analyzes generated SOAP note statements against the consultation transcript,
identifying supporting transcript excerpts, character offsets, similarity metrics,
and flagging unsupported, ambiguous, or conflicting evidence.

Core Guardrails:
1. Preserve original transcript and segment data.
2. For each statement, locate exact supporting transcript excerpt.
3. Unsupported statements explicitly display: "Evidence not found — review required."
4. Never fabricate or paraphrase transcript quotes — quotes are strictly verified slices.
5. Flag contradictory statements (e.g. transcript denies symptom but note asserts it).
6. Evidence mapping is stored separately from the clinical SOAP prose.
7. Prominently disclaim that evidence linking does NOT guarantee clinical accuracy.
"""

from __future__ import annotations

import logging
import re
from dataclasses import asdict, dataclass
from typing import Any, Dict, List, Optional, Tuple

from rapidfuzz import fuzz

logger = logging.getLogger("mediscribe.evidence_linking")

EVIDENCE_DISCLAIMER = (
    "Evidence linking identifies supporting transcript passages only and does not "
    "verify or guarantee clinical accuracy or medical correctness. Clinician judgement is always required."
)

UNSUPPORTED_MESSAGE = "Evidence not found — review required."
CONFLICTING_MESSAGE = "Conflicting evidence detected in dialogue — transcript contradicts this statement."
AMBIGUOUS_MESSAGE = "Ambiguous evidence in transcript — statement matches qualified or uncertain dialogue."

# Delimiters for decomposing section text into individual statements
_SENTENCE_DELIM = re.compile(r"(?<=[.!?])\s+|\n+")

# Common clinical negation patterns
_NEGATION_CUES = [
    r"\bdenies\b",
    r"\bdenied\b",
    r"\bno\b",
    r"\bnot\b",
    r"\bwithout\b",
    r"\bnever\b",
    r"\bnegative\s+for\b",
    r"\bruled?\s+out\b",
    r"\bstopped\b",
    r"\bdiscontinued\b",
    r"\bno\s+longer\b",
    r"\bfree\s+of\b",
]
_NEGATION_RE = re.compile("|".join(_NEGATION_CUES), re.IGNORECASE)

# Ambiguity / uncertainty cues
_UNCERTAINTY_CUES = [
    r"\bmaybe\b",
    r"\bpossibly\b",
    r"\bnot\s+sure\b",
    r"\bunclear\b",
    r"\bcan't\s+remember\b",
    r"\bunsure\b",
    r"\bmight\s+be\b",
    r"\bcould\s+be\b",
    r"\bquestionable\b",
]
_UNCERTAINTY_RE = re.compile("|".join(_UNCERTAINTY_CUES), re.IGNORECASE)

# Stop words to ignore during key clinical token matching
_STOP_WORDS = {
    "a", "an", "the", "and", "or", "but", "in", "on", "at", "to", "for", "of",
    "with", "by", "from", "up", "about", "into", "over", "after", "is", "are",
    "was", "were", "be", "been", "being", "have", "has", "had", "do", "does",
    "did", "patient", "reports", "states", "stated", "reported", "notes", "noted",
    "pt", "dr", "doctor", "clinician", "he", "she", "they", "i", "we", "his", "her",
    "their", "my", "our", "this", "that", "these", "those", "also", "well", "as",
}

# Scaffolding boilerplate statements to skip
_SCAFFOLDING_PATTERNS = [
    re.compile(r"^not\s+documented", re.IGNORECASE),
    re.compile(r"^none\s+(?:reported|documented|stated)", re.IGNORECASE),
    re.compile(r"^n/?a$", re.IGNORECASE),
    re.compile(r"^recording\s+captures", re.IGNORECASE),
]


def _extract_content_tokens(text: str) -> set[str]:
    """Extract lowercased alphanumeric content tokens without stop words."""
    words = re.findall(r"[a-zA-Z0-9]+(?:[-/][a-zA-Z0-9]+)?", text.lower())
    return {w for w in words if w not in _STOP_WORDS and len(w) > 1}


def _is_scaffolding(text: str) -> bool:
    """Return True if statement is documentation scaffolding rather than clinical fact."""
    cleaned = text.strip()
    if not cleaned or len(cleaned) < 3:
        return True
    return any(p.search(cleaned) for p in _SCAFFOLDING_PATTERNS)


@dataclass
class EvidenceStatement:
    id: str
    section: str
    statement: str
    status: str  # "supported" | "unsupported" | "conflicting" | "ambiguous"
    evidence_quote: Optional[str] = None
    evidence_start: Optional[int] = None
    evidence_end: Optional[int] = None
    similarity: float = 0.0
    review_message: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class EvidenceLinkingService:
    """
    Decomposes SOAP sections into statements and grounds each against the verbatim transcript.
    """

    MIN_SUPPORT_SIMILARITY = 50.0

    def _split_into_statements(self, section: str, text: str) -> List[Tuple[str, str]]:
        """
        Split a section text into clean individual clinical assertions.
        Returns list of (id, statement_text).
        """
        raw_chunks = _SENTENCE_DELIM.split(str(text or ""))
        statements: List[Tuple[str, str]] = []
        idx = 1
        for chunk in raw_chunks:
            # Strip bullet prefixes and whitespace
            cleaned = re.sub(r"^[\s*\-•\d.]+", "", chunk).strip()
            if not cleaned or _is_scaffolding(cleaned):
                continue
            stmt_id = f"{section[:4]}_{idx}"
            statements.append((stmt_id, cleaned))
            idx += 1
        return statements

    def _split_transcript_into_sentences(self, transcript: str) -> List[Tuple[int, int, str]]:
        """
        Split transcript into sentences while recording exact character start and end offsets.
        Returns list of (start_offset, end_offset, sentence_text).
        """
        sentences: List[Tuple[int, int, str]] = []
        # Find sentence boundaries: punctuation (. ! ?) followed by whitespace or newline, or double newlines
        matches = list(re.finditer(r"[^.!?\n]+(?:[.!?]+|\n+|$)", transcript))
        for m in matches:
            s_text = m.group(0).strip()
            if not s_text:
                continue
            start = m.start()
            # Adjust start for any leading whitespace stripped
            leading_ws = len(m.group(0)) - len(m.group(0).lstrip())
            start += leading_ws
            end = start + len(s_text)
            sentences.append((start, end, s_text))

        if not sentences and transcript.strip():
            sentences.append((0, len(transcript), transcript.strip()))
        return sentences

    def _detect_polarity_conflict(
        self, statement: str, transcript_sentence: str, shared_tokens: set[str]
    ) -> bool:
        """
        Detect if statement and transcript sentence directly contradict each other regarding shared clinical terms.
        E.g. Statement: 'Patient reports fever.' vs Transcript: 'I do not have any fever.'
             Statement: 'Patient denies chest pain.' vs Transcript: 'I had severe chest pain this morning.'
        """
        if not shared_tokens:
            return False

        stmt_has_neg = bool(_NEGATION_RE.search(statement))
        tr_has_neg = bool(_NEGATION_RE.search(transcript_sentence))

        # Direct polarity mismatch on the same clinical subject
        if stmt_has_neg != tr_has_neg:
            # Verify that the negation in transcript directly qualifies one of the shared terms
            for token in shared_tokens:
                # E.g. "no <token>", "denies <token>", "not <token>"
                pat = re.compile(rf"(?:no|not|denies|denied|without|never|stopped)\s+(?:\w+\s+)?{re.escape(token)}", re.IGNORECASE)
                if tr_has_neg and pat.search(transcript_sentence):
                    return True
                if stmt_has_neg and pat.search(statement):
                    return True

        return False

    def link_soap_evidence(
        self,
        transcript: str,
        soap_note: Dict[str, Any],
        segments: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """
        Analyze all statements in the SOAP note against the transcript.

        Args:
            transcript: Full verbatim consultation transcript.
            soap_note: Dict containing subjective, objective, assessment, plan.
            segments: Optional list of speech recognition segment timing objects.

        Returns:
            Dict containing:
                disclaimer (str),
                supported_count (int),
                unsupported_count (int),
                conflicting_count (int),
                ambiguous_count (int),
                total_statements (int),
                statements (List[Dict])
        """
        if not transcript or not transcript.strip():
            return {
                "disclaimer": EVIDENCE_DISCLAIMER,
                "supported_count": 0,
                "unsupported_count": 0,
                "conflicting_count": 0,
                "ambiguous_count": 0,
                "total_statements": 0,
                "statements": [],
            }

        sentences = self._split_transcript_into_sentences(transcript)
        results: List[EvidenceStatement] = []

        sections = ["subjective", "objective", "assessment", "plan"]
        for sec in sections:
            sec_text = str(soap_note.get(sec) or "")
            statements = self._split_into_statements(sec, sec_text)

            for stmt_id, statement in statements:
                stmt_tokens = _extract_content_tokens(statement)
                if not stmt_tokens:
                    # Generic or unanalyzable statement
                    results.append(
                        EvidenceStatement(
                            id=stmt_id,
                            section=sec,
                            statement=statement,
                            status="unsupported",
                            review_message=UNSUPPORTED_MESSAGE,
                        )
                    )
                    continue

                best_match: Optional[Tuple[int, int, str, float]] = None
                conflicting_sentence: Optional[Tuple[int, int, str, float]] = None
                ambiguous_matches: List[Tuple[int, int, str, float]] = []

                for s_start, s_end, s_text in sentences:
                    s_tokens = _extract_content_tokens(s_text)
                    shared = stmt_tokens.intersection(s_tokens)

                    # Compute matching similarity metrics
                    token_ratio = fuzz.token_set_ratio(statement, s_text)
                    partial_ratio = fuzz.partial_ratio(statement.lower(), s_text.lower())
                    score = (token_ratio * 0.7) + (partial_ratio * 0.3)

                    # Check for polarity conflict
                    if shared and self._detect_polarity_conflict(statement, s_text, shared):
                        conflicting_sentence = (s_start, s_end, s_text, score)

                    # Candidate match
                    if score >= self.MIN_SUPPORT_SIMILARITY and shared:
                        if best_match is None or score > best_match[3]:
                            best_match = (s_start, s_end, s_text, score)

                        if _UNCERTAINTY_RE.search(s_text):
                            ambiguous_matches.append((s_start, s_end, s_text, score))

                # Determine verdict
                if conflicting_sentence is not None:
                    # Contradiction has highest safety priority
                    c_start, c_end, c_quote, c_score = conflicting_sentence
                    # Ensure quote is strict slice of original transcript
                    verbatim_quote = transcript[c_start:c_end]
                    results.append(
                        EvidenceStatement(
                            id=stmt_id,
                            section=sec,
                            statement=statement,
                            status="conflicting",
                            evidence_quote=verbatim_quote,
                            evidence_start=c_start,
                            evidence_end=c_end,
                            similarity=round(c_score, 1),
                            review_message=CONFLICTING_MESSAGE,
                        )
                    )
                elif best_match is not None and best_match[3] >= self.MIN_SUPPORT_SIMILARITY:
                    b_start, b_end, b_quote, b_score = best_match
                    verbatim_quote = transcript[b_start:b_end]

                    if ambiguous_matches and any(m[0] == b_start for m in ambiguous_matches):
                        results.append(
                            EvidenceStatement(
                                id=stmt_id,
                                section=sec,
                                statement=statement,
                                status="ambiguous",
                                evidence_quote=verbatim_quote,
                                evidence_start=b_start,
                                evidence_end=b_end,
                                similarity=round(b_score, 1),
                                review_message=AMBIGUOUS_MESSAGE,
                            )
                        )
                    else:
                        results.append(
                            EvidenceStatement(
                                id=stmt_id,
                                section=sec,
                                statement=statement,
                                status="supported",
                                evidence_quote=verbatim_quote,
                                evidence_start=b_start,
                                evidence_end=b_end,
                                similarity=round(b_score, 1),
                                review_message=None,
                            )
                        )
                else:
                    # Unsupported / Evidence not found
                    results.append(
                        EvidenceStatement(
                            id=stmt_id,
                            section=sec,
                            statement=statement,
                            status="unsupported",
                            evidence_quote=None,
                            evidence_start=None,
                            evidence_end=None,
                            similarity=0.0,
                            review_message=UNSUPPORTED_MESSAGE,
                        )
                    )

        supported_count = sum(1 for r in results if r.status == "supported")
        unsupported_count = sum(1 for r in results if r.status == "unsupported")
        conflicting_count = sum(1 for r in results if r.status == "conflicting")
        ambiguous_count = sum(1 for r in results if r.status == "ambiguous")

        logger.info(
            "Evidence linking complete: %d statements (%d supported, %d unsupported, %d conflicting, %d ambiguous)",
            len(results), supported_count, unsupported_count, conflicting_count, ambiguous_count,
        )

        return {
            "disclaimer": EVIDENCE_DISCLAIMER,
            "supported_count": supported_count,
            "unsupported_count": unsupported_count,
            "conflicting_count": conflicting_count,
            "ambiguous_count": ambiguous_count,
            "total_statements": len(results),
            "statements": [r.to_dict() for r in results],
        }


# Global singleton instance
evidence_linking_service = EvidenceLinkingService()
