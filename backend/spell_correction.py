"""Medical spell correction — DISABLED BY DEFAULT after measurement.

Fuzzy-matches each word against the medical vocabulary and substitutes the
closest term above a similarity threshold. It ran in the live pipeline,
unmeasured, until 2026-09-11. Measuring it gave an unambiguous verdict.

**Applied to PriMock57's human transcripts**, which are correct by definition,
every change it makes is a false correction. It altered 309 of 34,367 words
(0.90%), and the frequent ones are not cosmetic:

    feeling  -> peeling   (51x)
    regular  -> irregular (24x)   <- inverts the clinical meaning
    start    -> stat      (17x)
    eating   -> sweating  (11x)   <- invents a symptom
    ever     -> fever     (10x)   <- invents a symptom

`regular -> irregular` on a cardiac examination is a patient-safety defect, not
a typo.

**Applied to real ASR output**, which is what it exists for, it does the
opposite of helping. Over the 20 PriMock57 channels in the ASR baseline:

    WER                  0.2713 -> 0.2790   (worse)
    medical-term error   0.1705 -> 0.5105   (three times worse)
    improved 0 cases, made 19 of 20 worse

The cause is structural rather than a badly chosen threshold. `is_medical_word`
skips a ~40-word stoplist, so every other word of four or more characters is
matched against 703 medical terms — and ordinary English is full of near-misses
for clinical vocabulary. Fixing it needs an English lexicon to reject candidates
that are already valid words, not a higher cut-off.

The code is kept and can be switched on with `MEDICAL_SPELL_CORRECTION=1`, so a
future attempt has something to improve and a number to beat. It stays off until
it can be shown to help.
"""

import os
import re

from rapidfuzz import fuzz, process
from medical_categories import SYMPTOMS, MEDICATIONS, CONDITIONS, PROCEDURES, CLINICAL_TERMS

# Off unless explicitly enabled. See the module docstring for the measurement.
SPELL_CORRECTION_ENABLED = os.getenv("MEDICAL_SPELL_CORRECTION", "0") not in ("0", "false", "False")

# Global vocabulary cache (loaded once on startup)
_medical_vocabulary = None

def load_medical_vocabulary():
    """
    Load all medical terms from dictionaries into a single searchable vocabulary.
    This is called once on startup and cached for performance.
    
    Returns:
        set: All medical terms (lowercase) from all categories
    """
    global _medical_vocabulary
    
    if _medical_vocabulary is not None:
        return _medical_vocabulary
    
    vocab = set()
    
    # Combine all dictionary terms
    vocab.update(term.lower() for term in SYMPTOMS)
    vocab.update(term.lower() for term in MEDICATIONS)
    vocab.update(term.lower() for term in CONDITIONS)
    vocab.update(term.lower() for term in PROCEDURES)
    vocab.update(term.lower() for term in CLINICAL_TERMS)
    
    _medical_vocabulary = vocab
    print(f"Loaded medical vocabulary: {len(vocab)} terms")
    
    return vocab


def is_medical_word(word):
    """
    Heuristic to determine if a word might be a medical term.
    This helps us skip common English words and speed up processing.
    
    Args:
        word: Single word to check
        
    Returns:
        bool: True if word might be medical (should be spell-checked)
    """
    # Skip very short words
    if len(word) < 4:
        return False
    
    # Skip common English words (basic list)
    common_words = {
        'patient', 'with', 'that', 'this', 'from', 'have', 'been', 
        'will', 'their', 'about', 'would', 'there', 'which', 'when',
        'them', 'these', 'than', 'some', 'time', 'very', 'what',
        'year', 'also', 'more', 'other', 'only', 'over', 'such',
        'even', 'most', 'made', 'after', 'many', 'where', 'much',
        'before', 'through', 'back', 'years', 'much', 'should',
        'well', 'without', 'against', 'between', 'under', 'while'
    }
    
    if word.lower() in common_words:
        return False
    
    return True


def fuzzy_match_word(word, vocabulary, threshold=85):
    """
    Find the best fuzzy match for a word in the medical vocabulary.
    
    Args:
        word: Word to correct
        vocabulary: Set of valid medical terms
        threshold: Minimum similarity score (0-100) to accept correction
        
    Returns:
        tuple: (corrected_word, confidence_score) or (original_word, 0) if no good match
    """
    # If word is already in vocabulary (exact match), no correction needed
    if word.lower() in vocabulary:
        return word, 100
    
    # Find best match using fuzzy matching
    # process.extractOne returns (match, score, index) or None
    result = process.extractOne(
        word.lower(), 
        vocabulary, 
        scorer=fuzz.ratio,
        score_cutoff=threshold
    )
    
    if result:
        matched_term, score, _ = result
        return matched_term, score
    
    # No good match found
    return word, 0


def correct_medical_spelling(text, threshold=85, verbose=True):
    """
    Correct spelling errors in medical transcription text.
    
    This function:
    1. Splits text into words
    2. For each word that looks medical, tries to find a correction
    3. Only corrects if confidence is above threshold
    4. Logs all corrections made
    
    Args:
        text: Transcription text from Whisper
        threshold: Minimum confidence score (0-100) to make correction (default: 85)
        verbose: If True, print corrections to console
        
    Returns:
        tuple: (corrected_text, corrections_log)
            - corrected_text: Text with spelling corrections applied
            - corrections_log: List of dicts with correction details

    Note: a phrase-normalisation stage used to run ahead of the word-level
    pass. It held eight regexes lifted verbatim from two demo recordings,
    including a patient's name ("Harry Miles" -> "Harry Myles"), and was
    removed in the Phase 0 de-overfitting pass. Any replacement must be
    derived from the evaluation corpus, not from a single recording.
    """
    if not SPELL_CORRECTION_ENABLED:
        # Returns the text untouched rather than raising: callers should not
        # have to know whether this stage is switched on.
        return text, []

    if verbose:
        print("\n" + "=" * 50)
        print("MEDICAL SPELL CORRECTION")
        print("=" * 50)

    # Load vocabulary
    vocab = load_medical_vocabulary()
    
    # Split text into words (preserving spaces and punctuation)
    # We'll use a simple split and rejoin approach
    words = text.split()
    corrected_words = []
    corrections_log = []
    
    for word in words:
        # Remove punctuation for matching, but preserve it
        # Extract actual word without punctuation
        clean_word = re.sub(r'[^\w\s-]', '', word)
        
        # Check if this word should be spell-checked
        if not is_medical_word(clean_word):
            corrected_words.append(word)
            continue
        
        # Try to find correction
        corrected, score = fuzzy_match_word(clean_word, vocab, threshold)
        
        if score >= threshold and corrected.lower() != clean_word.lower():
            # Correction found!
            # Preserve original capitalization pattern
            if clean_word[0].isupper():
                corrected = corrected.capitalize()
            
            # Replace word in original (preserving punctuation)
            corrected_full = word.replace(clean_word, corrected)
            corrected_words.append(corrected_full)
            
            # Log the correction
            correction_info = {
                'original': word,
                'corrected': corrected_full,
                'confidence': round(score, 1)
            }
            corrections_log.append(correction_info)
            
            if verbose:
                print(f"  ✓ '{word}' → '{corrected_full}' (confidence: {score:.1f}%)")
        else:
            # Keep original word
            corrected_words.append(word)
    
    corrected_text = " ".join(corrected_words)
    
    if verbose:
        if corrections_log:
            print(f"\nTotal corrections made: {len(corrections_log)}")
        else:
            print("\nNo corrections needed (all terms recognized)")
        print("=" * 50)
    
    return corrected_text, corrections_log


def test_spell_correction():
    """
    Test function to verify spell correction works with known misspellings.
    Run this to validate the system before integrating.
    """
    print("\n" + "=" * 50)
    print("TESTING SPELL CORRECTION")
    print("=" * 50)
    
    test_cases = [
        "Patient has hypertropium bromide for breathing",
        "Started on certraline for depression",
        "Diagnosed with diabetes malitis",
        "Taking spiranylactone for heart failure",
        "Patient reports chest pain and shortness of breath",
        "Prescribed methamin for diabetes management"
    ]
    
    for test_text in test_cases:
        print(f"\nOriginal: {test_text}")
        corrected, log = correct_medical_spelling(test_text, verbose=False)
        print(f"Corrected: {corrected}")
        if log:
            for correction in log:
                print(f"  → {correction['original']} → {correction['corrected']} ({correction['confidence']}%)")
        else:
            print("  → No corrections needed")
    
    print("\n" + "=" * 50)


# If running this file directly, run tests
if __name__ == "__main__":
    test_spell_correction()
