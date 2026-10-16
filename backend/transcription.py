"""Speech recognition, via a local Whisper backend.

Every decoding choice here is an environment variable rather than a literal,
because each one is a hypothesis the evaluation harness can test:

    python -m eval run --suite primock57 --stages asr --limit 6

A change to any of these is only worth keeping if it moves `medical_term_recall`
on real consultation audio, and the defaults below are the ones that did.

Two of them replace settings that were actively harmful:

**The prompt no longer names diagnoses.** It used to hold a fixed sentence
listing "chest pain, palpitations, pericarditis, ECG, troponin, diabetes,
HbA1c, metformin, thrush" — the vocabulary of the two demo recordings the
project was originally built around — and Whisper conditions decoding on that
text, so every user's audio was pushed toward those conditions whatever the
patient had. Same overfitting Phase 0 removed from note generation, left behind
in the ASR stage.

Removing it entirely measured *worst* of any variant, so the prompt is not gone,
only condition-neutral: generic consultation vocabulary, plus whatever terms the
caller's own history supplies (`decoder_vocabulary.py`).

The disease list did lead on the channels used for tuning (medical-term error
0.129 against 0.137). It did not survive a held-out check on fourteen unseen
channels, where the gap fell to 0.146 against 0.148 and the generic prompt was
marginally ahead on recall — the dev-set advantage was not real. Since the two
measure the same, the one that cannot mislead a decoder about a patient it has
never seen is the one that ships.

**`condition_on_previous_text` stays True — for the models we ship.** Feeding
each window the previous window's output is a known repetition-loop trigger on
long or silent audio, and PriMock57's per-speaker channels are mostly silence,
so turning it off looked like an obvious win. Measured over six channels on
`base.en` it is not: it buys slightly fewer spurious medical terms (0.33 -> 0.17
per channel) at the cost of more missed ones (1.83 -> 2.00), and the
medical-term error rate gets worse overall (0.141 -> 0.148).

That result is **per-model, not universal**, which the model comparison below
made expensive to learn. Carried over to `distil-small.en` unchanged, the
setting sent the decoder into exactly the repetition loop it is known for:
medical-term recall 0.303, WER 0.761, 550 deletions a channel, transcripts
stuttering "Are you stop? Or should you stop?". With it off the same checkpoint
scored 0.807. Treat this flag as a property of the checkpoint. The distilled
models, whose decoders are shallower, are the ones to re-check.

**The model is `small.en`, chosen 2026-09-11** over `base.en`, `distil-small.en`
and `large-v3-turbo` on identical audio and identical decoder settings
(`eval/results/baseline-asr-model-probe.json`, three channels):

    model             disk    recall   med-err     WER   x realtime
    large-v3-turbo    1.6G    0.9500    0.1092  0.1567        1.93
    small.en          464M    0.9278    0.1092  0.1924        1.02
    base.en           141M    0.8908    0.1685  0.2301        0.11

`small.en` ties `large-v3-turbo` on medical-term error rate at a third of the
disk and half the time, and this machine is CPU-only, so a model at ~2x realtime
cannot serve an interactive upload. Turbo's remaining edge is 2.2 points of
recall.

Read that as a deliberate trade rather than a settled result: **three channels
cannot resolve a 2.2 point gap**, and the choice was made on disk and latency
with that understood. The 20-channel figures in the README still describe
`base.en` and are stale for this model; nothing here should be quoted as a
quality claim until that run happens.
"""

from __future__ import annotations

import os

try:
    from faster_whisper import WhisperModel  # type: ignore
except ImportError:  # pragma: no cover - optional fast path
    WhisperModel = None

try:  # pragma: no cover - optional dependency for fallback path only
    import torch  # type: ignore
except ImportError:  # pragma: no cover
    torch = None

try:  # pragma: no cover - optional fallback
    import whisper  # type: ignore
except ImportError:  # pragma: no cover
    whisper = None


def _flag(name: str, default: str) -> bool:
    return os.getenv(name, default) not in ("0", "false", "False")


WHISPER_BACKEND = os.getenv("WHISPER_BACKEND", "faster-whisper")
WHISPER_MODEL = os.getenv("WHISPER_MODEL", "small.en")
WHISPER_COMPUTE_TYPE = os.getenv("WHISPER_COMPUTE_TYPE", "int8")
WHISPER_BEAM_SIZE = int(os.getenv("WHISPER_BEAM_SIZE", "3"))

# Voice-activity detection drops non-speech before decoding. On per-speaker
# channels that is most of the file.
WHISPER_VAD_FILTER = _flag("WHISPER_VAD_FILTER", "1")

# Left on: turning it off measured worse. See the module docstring.
WHISPER_CONDITION_ON_PREVIOUS = _flag("WHISPER_CONDITION_ON_PREVIOUS", "1")

# Condition-neutral clinical framing. Beats no prompt clearly, and matches a
# diagnosis-listing prompt on held-out audio — see the module docstring.
DEFAULT_INITIAL_PROMPT = (
    "English clinical consultation between a doctor and a patient. "
    "Common terms include date of birth, symptoms, examination, medication, "
    "dose, blood test, results, referral, follow-up, appointment, GP surgery, "
    "medical history, allergies, and lifestyle."
)
WHISPER_INITIAL_PROMPT = os.getenv("WHISPER_INITIAL_PROMPT", DEFAULT_INITIAL_PROMPT)

# Word-level timings and probabilities. These are what a real per-word
# confidence and transcript-to-note evidence linking need; the cost is a modest
# slowdown, so it is switchable.
WHISPER_WORD_TIMESTAMPS = _flag("WHISPER_WORD_TIMESTAMPS", "1")

if torch is not None and os.cpu_count():
    torch.set_num_threads(max(1, os.cpu_count()))

print("Loading transcription model...")

_backend_name = "openai-whisper"
_fw_model = None
_ow_model = None

if WHISPER_BACKEND == "faster-whisper" and WhisperModel is not None:
    _fw_model = WhisperModel(
        WHISPER_MODEL,
        device="cpu",
        compute_type=WHISPER_COMPUTE_TYPE,
        cpu_threads=max(1, os.cpu_count() or 1),
    )
    _backend_name = "faster-whisper"
else:
    if whisper is None:
        raise RuntimeError(
            "WHISPER_BACKEND is set to openai-whisper, but the optional "
            "'openai-whisper' package is not installed."
        )
    _ow_model = whisper.load_model(WHISPER_MODEL)

print(
    f"Transcription model loaded successfully! backend={_backend_name}, "
    f"model={WHISPER_MODEL}, vad={WHISPER_VAD_FILTER}, "
    f"condition_on_previous={WHISPER_CONDITION_ON_PREVIOUS}"
)


def build_initial_prompt(vocabulary: list[str] | None = None) -> str | None:
    """Decoder biasing text for one request.

    Whisper conditions decoding on this string, so terms in it are more likely
    to be produced. That is worth doing with words this *particular* encounter
    is likely to contain — a clinician's specialty, a patient's known
    medications — and actively harmful with a fixed list, which pushes every
    recording toward one demo's diagnoses.

    Returns None when there is nothing specific to bias toward, which leaves
    the decoder unbiased rather than biased wrongly.
    """
    base = WHISPER_INITIAL_PROMPT.strip()

    terms = [term.strip() for term in (vocabulary or []) if term and term.strip()]
    if not terms:
        return base or None

    unique: list[str] = []
    seen: set[str] = set()
    for term in terms:
        key = term.lower()
        if key not in seen:
            seen.add(key)
            unique.append(term)

    # The generic framing stays: it is what measured well on its own, and the
    # caller's terms are an addition to it rather than a replacement for it.
    addition = "Also expect: " + ", ".join(unique[:60]) + "."
    return f"{base} {addition}".strip() if base else addition


def _word_confidence(segments: list) -> float | None:
    """Mean per-word probability across the transcript.

    This is the first genuine confidence the pipeline can offer. Everything
    previously labelled "confidence" was either a hardcoded 0.0 or the
    validator's medical-term density, which is computed before any transcription
    quality is known.
    """
    probabilities = [
        word.probability
        for segment in segments
        for word in (getattr(segment, "words", None) or [])
        if getattr(word, "probability", None) is not None
    ]
    if not probabilities:
        return None
    return round(sum(probabilities) / len(probabilities), 4)


def _transcribe_with_faster_whisper(audio_file_path: str, vocabulary: list[str] | None) -> dict:
    assert _fw_model is not None

    segment_iterator, info = _fw_model.transcribe(
        audio_file_path,
        task="transcribe",
        language="en",
        beam_size=WHISPER_BEAM_SIZE,
        best_of=1,
        condition_on_previous_text=WHISPER_CONDITION_ON_PREVIOUS,
        vad_filter=WHISPER_VAD_FILTER,
        initial_prompt=build_initial_prompt(vocabulary),
        word_timestamps=WHISPER_WORD_TIMESTAMPS,
    )

    # faster-whisper streams segments lazily; `info.duration` is only final once
    # the iterator is drained.
    segments = list(segment_iterator)
    text = " ".join(segment.text.strip() for segment in segments if segment.text).strip()

    words = [
        {"word": word.word, "start": word.start, "end": word.end, "probability": word.probability}
        for segment in segments
        for word in (getattr(segment, "words", None) or [])
    ]

    return {
        "text": text,
        "language": info.language or "en",
        "duration": getattr(info, "duration", None),
        "words": words,
        "confidence": _word_confidence(segments),
    }


def _transcribe_with_openai_whisper(audio_file_path: str, vocabulary: list[str] | None) -> dict:
    assert _ow_model is not None

    result = _ow_model.transcribe(
        audio_file_path,
        task="transcribe",
        language="en",
        temperature=0.0,
        best_of=1,
        condition_on_previous_text=WHISPER_CONDITION_ON_PREVIOUS,
        fp16=False,
        initial_prompt=build_initial_prompt(vocabulary),
    )

    segments = result.get("segments") or []
    return {
        "text": result["text"],
        "language": result.get("language", "en"),
        "duration": segments[-1].get("end") if segments else None,
        "words": [],
        "confidence": None,
    }


def transcribe_audio(audio_file_path: str, vocabulary: list[str] | None = None) -> dict:
    """
    Transcribe an audio file using a local Whisper backend.

    `vocabulary` biases decoding toward terms this encounter is likely to
    contain — see `build_initial_prompt`.

    Prefer faster-whisper on CPU for better throughput with similar quality.
    Fall back to openai-whisper if faster-whisper is not installed.
    """
    try:
        print(f"Transcribing: {audio_file_path}")

        if _backend_name == "faster-whisper":
            outcome = _transcribe_with_faster_whisper(audio_file_path, vocabulary)
        else:
            outcome = _transcribe_with_openai_whisper(audio_file_path, vocabulary)

        print("=" * 50)
        print(f"SUCCESS! Transcribed {len(outcome['text'])} characters")
        if outcome.get("confidence") is not None:
            print(f"Mean word probability: {outcome['confidence']}")
        print("=" * 50)

        return {
            "success": True,
            "error": None,
            "backend": _backend_name,
            "model": WHISPER_MODEL,
            **outcome,
        }

    except Exception as e:
        import traceback

        print("=" * 50)
        print("TRANSCRIPTION ERROR:")
        print(traceback.format_exc())
        print("=" * 50)

        return {
            "success": False,
            "text": None,
            "language": None,
            "duration": None,
            "words": [],
            "confidence": None,
            "error": str(e),
            "backend": _backend_name,
            "model": WHISPER_MODEL,
        }


def transcribe_audio_realtime(
    audio_file_path: str, vocabulary: list[str] | None = None
) -> tuple[str, float | None]:
    """
    Simplified wrapper: returns ``(transcript_text, audio_duration_seconds)``.

    ``audio_duration_seconds`` is derived from the decoded audio by the ASR
    backend and is authoritative — unlike the client-supplied
    ``X-Audio-Duration-Seconds`` header, which is only a pre-flight hint.
    """
    result = transcribe_audio(audio_file_path, vocabulary)

    if result["success"]:
        return result["text"], result["duration"]
    raise Exception(f"Transcription failed: {result['error']}")
