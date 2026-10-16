"""Normalise extracted entities to standard clinical codes.

Entities leave the extractor as bare strings, which makes them a word list
rather than clinical data: "amlodipine", "Amlodipine 5mg" and "amlodipine
besylate" are three different things to a string comparison and one thing to a
clinician. Attaching a code fixes that, and unlocks the downstream work that
needs identity rather than spelling — coding suggestions, interaction checks,
matching a problem across visits.

**No local knowledge base.** scispaCy's `UMLSEntityLinker` is the usual route
and needs a ~1 GB download; these are the NLM's public REST services instead,
which need no key, no licence and no disk:

    RxNav / RxNorm      medications      rxnav.nlm.nih.gov
    ICD-10-CM           conditions       clinicaltables.nlm.nih.gov
    Conditions (SNOMED) conditions       clinicaltables.nlm.nih.gov

The two sides are not equally reliable, and the module does not pretend they
are. RxNorm resolves a drug name to a single concept, so a medication match is
a verification and fills `confidence`. ICD-10 from a bare diagnosis is not
solvable by search ranking — "diabetes" ranks `Diabetes insipidus` above
`Type 2 diabetes mellitus`, and "hypertension" does not reach `I10` at all —
so conditions come back as a review shortlist with `requires_review` set, and
never fill a confidence.

The trade is network latency per unseen term, which the on-disk cache absorbs:
a clinical vocabulary is small and repeats heavily, so a warm cache answers
almost everything locally. Lookups are best-effort — a failure leaves the entity
unlinked and never breaks the pipeline, because an uncoded note is a worse note
but a crashed request is no note at all.
"""

from __future__ import annotations

import json
import os
import re
import threading
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from rapidfuzz import fuzz

RXNAV_BASE = "https://rxnav.nlm.nih.gov/REST"
CLINICAL_TABLES_BASE = "https://clinicaltables.nlm.nih.gov/api"

# Terms that repeat across every consultation, so the cache earns its keep
# quickly. Lives outside the repo by default; override for a shared location.
CACHE_PATH = Path(
    os.getenv("MEDISCRIBE_ONTOLOGY_CACHE", Path(__file__).resolve().parent / ".ontology_cache.json")
)

REQUEST_TIMEOUT = float(os.getenv("ONTOLOGY_TIMEOUT_SECONDS", "6"))
ONTOLOGY_ENABLED = os.getenv("ONTOLOGY_LINKING", "1") not in ("0", "false", "False")

# RxNav's approximate-match score is on its own opaque scale (a correct match
# for a misspelling scores ~9), so it cannot be thresholded directly. String
# similarity between the query and the concept name is used instead — the same
# rapidfuzz measure the spell-correction stage already relies on, on a scale we
# can reason about.
MIN_NAME_SIMILARITY = float(os.getenv("RXNORM_MIN_SIMILARITY", "80"))

_USER_AGENT = "mediscribe-ai/1.0 (clinical documentation; ontology lookup)"
_NON_WORD = re.compile(r"[^a-z0-9 ]")
_WHITESPACE = re.compile(r"\s+")

_lock = threading.Lock()
_cache: dict[str, Any] | None = None


# ── Cache ─────────────────────────────────────────────────────────────────────

def _load_cache() -> dict[str, Any]:
    global _cache
    if _cache is not None:
        return _cache
    try:
        _cache = json.loads(CACHE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        _cache = {}
    return _cache


def save_cache() -> None:
    """Persist the cache. Safe to call often; a failure is not worth raising."""
    if _cache is None:
        return
    try:
        CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        CACHE_PATH.write_text(json.dumps(_cache, indent=0, sort_keys=True), encoding="utf-8")
    except OSError:
        pass


def cache_stats() -> dict[str, int]:
    cache = _load_cache()
    return {
        "entries": len(cache),
        "linked": sum(1 for value in cache.values() if value),
        "misses_cached": sum(1 for value in cache.values() if not value),
    }


# ── HTTP ──────────────────────────────────────────────────────────────────────

def _get_json(url: str) -> Any | None:
    request = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT) as response:
            return json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError, ValueError):
        # Best-effort by design: an unreachable NLM service must not take the
        # transcription request down with it.
        return None


def normalise_term(text: str) -> str:
    return _WHITESPACE.sub(" ", _NON_WORD.sub(" ", str(text).lower())).strip()


# ── Lookups ───────────────────────────────────────────────────────────────────

def lookup_medication(term: str) -> dict[str, Any] | None:
    """Resolve a drug name to an RxNorm concept.

    Tries the exact name first — cheap, unambiguous, and correct for the
    formulary spellings most transcripts contain — then falls back to RxNav's
    approximate matcher for misspellings the ASR introduced.
    """
    cleaned = normalise_term(term)
    if not cleaned:
        return None

    quoted = urllib.parse.quote(cleaned)
    exact = _get_json(f"{RXNAV_BASE}/rxcui.json?name={quoted}&search=2")
    rxcui = ((exact or {}).get("idGroup", {}).get("rxnormId") or [None])[0]
    if rxcui:
        return {
            "system": "RXNORM",
            "code": str(rxcui),
            "display": cleaned,
            "match": "exact",
            "score": 100.0,
        }

    approximate = _get_json(f"{RXNAV_BASE}/approximateTerm.json?term={quoted}&maxEntries=5")
    candidates = (approximate or {}).get("approximateGroup", {}).get("candidate") or []

    # Only some candidates carry a name; the rest are source-specific atoms for
    # the same concept. Take the best-scoring named one and judge it on how
    # closely it actually reads like the term we asked about.
    best = None
    for candidate in candidates:
        name = candidate.get("name")
        if not name:
            continue
        similarity = fuzz.ratio(cleaned, normalise_term(name))
        if best is None or similarity > best[0]:
            best = (similarity, candidate, name)

    if best is None or best[0] < MIN_NAME_SIMILARITY:
        return None

    similarity, candidate, name = best
    return {
        "system": "RXNORM",
        "code": str(candidate.get("rxcui", "")),
        "display": normalise_term(name),
        "match": "approximate",
        "score": round(float(similarity), 1),
    }


def lookup_condition(term: str) -> dict[str, Any] | None:
    """Resolve a condition to an ICD-10-CM code, with a SNOMED-backed display.

    The API returns candidates in its own order, which is *not* the order a
    coder wants: a bare "pericarditis" comes back with `A39.53 Meningococcal
    pericarditis` first, and "hypertension" with `I15.0 Renovascular
    hypertension`. Coding to those would invent a specificity the transcript
    never stated — the same fabrication the rest of the pipeline works to
    prevent.

    `_rank_icd_candidates` therefore prefers the *least* specific code that
    still matches, which is the correct default for an unqualified diagnosis.
    Alternatives are returned alongside it, because the choice belongs to a
    clinician reviewing the note, not to this function.
    """
    cleaned = normalise_term(term)
    if not cleaned:
        return None

    quoted = urllib.parse.quote(cleaned)
    icd = _get_json(
        f"{CLINICAL_TABLES_BASE}/icd10cm/v3/search?sf=code,name&terms={quoted}&maxList=12"
    )
    # Response shape: [total, [codes], null, [[code, name], ...]]
    if not icd or not isinstance(icd, list) or len(icd) < 4 or not icd[3]:
        return None

    ranked = _rank_icd_candidates(cleaned, icd[3])
    if not ranked:
        return None

    code, name = ranked[0]
    exact = normalise_term(name) == cleaned
    result = {
        "system": "ICD10CM",
        "code": str(code),
        "display": str(name),
        "match": "exact" if exact else "search",
        # Mapping free text to ICD-10 is a curated-crosswalk problem, not a
        # string-similarity one. Anything short of an exact name match is a
        # suggestion for a clinician to accept or change, never a decision.
        "requires_review": not exact,
        "score": round(float(fuzz.ratio(cleaned, normalise_term(name))), 1),
        "alternatives": [
            {"code": str(alt_code), "display": str(alt_name)}
            for alt_code, alt_name in ranked[1:4]
        ],
        "total_candidates": icd[0] if isinstance(icd[0], int) else None,
    }

    conditions = _get_json(
        f"{CLINICAL_TABLES_BASE}/conditions/v3/search?terms={quoted}&maxList=1"
    )
    if conditions and isinstance(conditions, list) and len(conditions) >= 4 and conditions[3]:
        result["preferred_term"] = str(conditions[3][0][0])

    return result


# Words that mark the *absence* of a qualifier rather than adding one. A name
# containing them is the generic concept, so they must not count against it the
# way "mild intermittent" or "renovascular" do.
_NEUTRAL_ICD_MARKERS = frozenset({
    "unspecified", "uncomplicated", "without", "complications", "complication",
    "nos", "other", "acute", "type",
})


def _rank_icd_candidates(term: str, candidates: list) -> list[tuple[str, str]]:
    """Order ICD-10 candidates generic-first.

    Signals, in order of weight:

    1. an exact name match wins outright;
    2. fewest *qualifier* tokens the query did not ask for — "Mild intermittent
       asthma" adds two, "Unspecified asthma, uncomplicated" adds none, because
       words like "unspecified" mark the absence of a qualifier rather than the
       presence of one;
    3. shorter ICD codes sit higher in the hierarchy, which breaks the ties.

    This is a heuristic and it does not always land: a bare "hypertension"
    should code to I10 by convention, and no ordering rule derives that from the
    candidate names alone. That is why nothing consumes the code automatically —
    see the `requires_review` flag on the result.
    """
    query_tokens = set(term.split())

    def sort_key(candidate) -> tuple:
        code, name = (list(candidate) + ["", ""])[:2]
        normalised = normalise_term(name)
        tokens = set(normalised.split())
        qualifiers = tokens - query_tokens - _NEUTRAL_ICD_MARKERS
        return (
            0 if normalised == term else 1,
            len(qualifiers),
            len(str(code)),
            str(code),
        )

    usable = [c for c in candidates if isinstance(c, (list, tuple)) and len(c) >= 2]
    return [(str(c[0]), str(c[1])) for c in sorted(usable, key=sort_key)]


_LOOKUP_BY_CATEGORY = {
    "medication": lookup_medication,
    "condition": lookup_condition,
}


def link_term(term: str, category: str) -> dict[str, Any] | None:
    """Cached lookup for one term. Negative results are cached too, so a term
    that is not in the vocabulary costs one request per process lifetime rather
    than one per transcript."""
    if not ONTOLOGY_ENABLED:
        return None

    lookup = _LOOKUP_BY_CATEGORY.get(category)
    if lookup is None:
        return None

    key = f"{category}:{normalise_term(term)}"
    cache = _load_cache()
    if key in cache:
        return cache[key]

    result = lookup(term)
    with _lock:
        cache[key] = result
    return result


def link_entities(entities: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Attach `ontology` to medication and condition entities, in place.

    `confidence` is only filled from a **medication** match. RxNorm resolves a
    drug name to one concept and either finds it or does not, so the score means
    something. ICD-10 does not work that way: mapping a bare diagnosis to a code
    is a curated-crosswalk problem, and the shortlist this module returns is a
    suggestion for review, not a verification. Writing a confidence from it
    would claim an assurance that does not exist, so condition entities keep
    `confidence` at 0.0 and carry their candidates instead.
    """
    if not ONTOLOGY_ENABLED or not entities:
        return entities

    linked = 0
    for entity in entities:
        category = entity.get("category")
        if category not in _LOOKUP_BY_CATEGORY:
            continue
        match = link_term(entity.get("text", ""), category)
        if not match:
            continue
        entity["ontology"] = match
        if category == "medication":
            entity["confidence"] = round(min(float(match.get("score", 0)) / 100.0, 1.0), 3)
        linked += 1

    if linked:
        save_cache()
    return entities


def ontology_counts(entities: list[dict[str, Any]]) -> dict[str, int]:
    linkable = [e for e in entities if e.get("category") in _LOOKUP_BY_CATEGORY]
    return {
        "linkable": len(linkable),
        "linked": sum(1 for e in linkable if e.get("ontology")),
        "rxnorm": sum(1 for e in linkable if (e.get("ontology") or {}).get("system") == "RXNORM"),
        "icd10cm": sum(1 for e in linkable if (e.get("ontology") or {}).get("system") == "ICD10CM"),
    }
