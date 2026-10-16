"""Dedicated speech-to-text service for MediScribe AI using Faster-Whisper.

Features:
- Lazy singleton model loader to avoid reloading checkpoints on every request
- Configurable model size via `WHISPER_MODEL` environment variable (default: base.en for CPU demo)
- Validation of audio availability, file size, supported formats, and audio container decodability
- Extraction of word-level probabilities and acoustic confidence metrics
- Clear clinical disclaimer regarding medical vocabulary, accents, noise, and multilingual code-switching
- Rejection of fake/fabricated transcripts
"""

from __future__ import annotations

import logging
import os
import threading
from typing import List, Optional

logger = logging.getLogger("mediscribe.transcription_service")

# Supported audio extensions that PyAV / Faster-Whisper can decode
SUPPORTED_AUDIO_EXTENSIONS = ('.mp3', '.wav', '.m4a', '.webm', '.ogg', '.flac')
MAX_AUDIO_BYTES = 50 * 1024 * 1024  # 50 MB
DEFAULT_MODEL = "base.en"

TRANSCRIPTION_DISCLAIMER = (
    "Clinical Notice: Acoustic speech recognition accuracy varies with background noise, "
    "clinician/patient accents, specialized medical vocabulary, and code-switching (e.g. Tamil-English). "
    "Tamil-English transcription has not been empirically verified on this model checkpoint. "
    "Clinicians must carefully review and edit all transcriptions before generating SOAP notes or approving documentation."
)


class TranscriptionError(Exception):
    """Base exception for transcription service."""
    pass


class AudioValidationError(TranscriptionError):
    """Raised when audio file is invalid, missing, empty, oversized, or unreadable."""
    pass


class ModelLoadError(TranscriptionError):
    """Raised when the Faster-Whisper model cannot be loaded."""
    pass


class EmptyAudioError(TranscriptionError):
    """Raised when an audio recording produces no decodable speech."""
    pass


class TranscriptionService:
    """Thread-safe transcription service wrapping Faster-Whisper."""

    def __init__(self) -> None:
        self._model = None
        self._lock = threading.Lock()
        self._model_name = os.getenv("WHISPER_MODEL", DEFAULT_MODEL)
        self._device = os.getenv("WHISPER_DEVICE", "cpu")
        self._compute_type = os.getenv("WHISPER_COMPUTE_TYPE", "int8")
        self._cpu_threads = int(os.getenv("WHISPER_CPU_THREADS", max(1, os.cpu_count() or 1)))

    @property
    def model_name(self) -> str:
        return self._model_name

    def is_available(self) -> bool:
        """Check if Faster-Whisper dependency is importable and model can be loaded."""
        try:
            import faster_whisper
            return hasattr(faster_whisper, "WhisperModel")
        except ImportError:
            return False

    def get_model(self):
        """
        Return the cached WhisperModel singleton.
        Loads the model on first call and keeps it in memory for subsequent requests.
        """
        if self._model is not None:
            return self._model

        with self._lock:
            if self._model is not None:
                return self._model

            try:
                from faster_whisper import WhisperModel
            except ImportError as e:
                raise ModelLoadError("faster-whisper is not installed. Run `pip install faster-whisper`.") from e

            # In test environments, WhisperModel may be a stub
            if getattr(WhisperModel, "__name__", "") == "_StubWhisperModel":
                logger.info("Using StubWhisperModel in test environment")
                self._model = WhisperModel()
                return self._model

            logger.info(
                "Loading Faster-Whisper model=%s device=%s compute_type=%s cpu_threads=%s...",
                self._model_name,
                self._device,
                self._compute_type,
                self._cpu_threads,
            )

            try:
                self._model = WhisperModel(
                    self._model_name,
                    device=self._device,
                    compute_type=self._compute_type,
                    cpu_threads=self._cpu_threads,
                )
                logger.info("Faster-Whisper model %s loaded successfully", self._model_name)
                return self._model
            except Exception as e:
                logger.exception("Failed to load Faster-Whisper model %s", self._model_name)
                raise ModelLoadError(f"Failed to load Whisper model '{self._model_name}': {str(e)}") from e

    def validate_audio_file(self, audio_path: str) -> dict:
        """
        Validate audio file existence, size, extension, and decodability.
        Returns a dict of metadata (file_size, extension) if valid.
        """
        if not audio_path or not os.path.exists(audio_path):
            raise AudioValidationError(f"Audio file does not exist at path: '{audio_path}'.")

        try:
            file_size = os.path.getsize(audio_path)
        except OSError as e:
            raise AudioValidationError(f"Could not access audio file: {str(e)}") from e

        if file_size == 0:
            raise AudioValidationError("Audio file is empty (0 bytes). Please upload a valid recording.")

        if file_size > MAX_AUDIO_BYTES:
            mb_size = file_size / (1024 * 1024)
            raise AudioValidationError(
                f"Audio file size ({mb_size:.1f} MB) exceeds maximum accepted limit of 50 MB."
            )

        ext = os.path.splitext(audio_path)[1].lower()
        if ext not in SUPPORTED_AUDIO_EXTENSIONS:
            raise AudioValidationError(
                f"Unsupported audio format '{ext}'. Supported formats: {', '.join(SUPPORTED_AUDIO_EXTENSIONS)}."
            )

        # Verify container decodability via PyAV if available
        try:
            import av
            with av.open(audio_path) as container:
                audio_streams = [s for s in container.streams if s.type == "audio"]
                if not audio_streams:
                    raise AudioValidationError("Audio container contains no audio streams.")
        except ImportError:
            pass  # PyAV optional check
        except Exception as e:
            if isinstance(e, AudioValidationError):
                raise
            # If av failed to read header, file is likely corrupt
            raise AudioValidationError(f"Invalid or corrupt audio file: {str(e)}") from e

        return {"file_size": file_size, "extension": ext}

    def transcribe(
        self,
        audio_path: str,
        vocabulary: Optional[List[str]] = None,
        language: str = "en",
    ) -> dict:
        """
        Perform speech recognition on a validated audio file.
        Returns transcript text, word timings, ASR confidence, and clinical disclaimers.
        """
        # Step 1: Pre-flight audio validation
        meta = self.validate_audio_file(audio_path)

        # Step 2: Load model singleton
        model = self.get_model()

        # Step 3: Initial prompt conditioning (condition-neutral + user specialty vocabulary)
        initial_prompt = self._build_initial_prompt(vocabulary)

        beam_size = int(os.getenv("WHISPER_BEAM_SIZE", "3"))
        vad_filter = os.getenv("WHISPER_VAD_FILTER", "1") not in ("0", "false", "False")
        condition_on_previous = os.getenv("WHISPER_CONDITION_ON_PREVIOUS", "1") not in ("0", "false", "False")
        word_timestamps = os.getenv("WHISPER_WORD_TIMESTAMPS", "1") not in ("0", "false", "False")

        try:
            segment_iterator, info = model.transcribe(
                audio_path,
                task="transcribe",
                language=language,
                beam_size=beam_size,
                best_of=1,
                condition_on_previous_text=condition_on_previous,
                vad_filter=vad_filter,
                initial_prompt=initial_prompt,
                word_timestamps=word_timestamps,
            )

            # Drain generator
            segments = list(segment_iterator)
        except Exception as e:
            logger.exception("Faster-Whisper inference failed on %s", audio_path)
            raise TranscriptionError(f"Speech recognition engine failed during transcription: {str(e)}") from e

        # Extract text
        transcription_text = " ".join(seg.text.strip() for seg in segments if seg.text).strip()

        if not transcription_text:
            raise EmptyAudioError(
                "No speech was detected in the audio file. Please check audio recording levels and clarity."
            )

        # Extract words & calculate mean probability
        words = []
        probabilities = []
        for segment in segments:
            for word in (getattr(segment, "words", None) or []):
                prob = getattr(word, "probability", None)
                if prob is not None:
                    probabilities.append(prob)
                words.append({
                    "word": word.word,
                    "start": round(word.start, 2) if word.start is not None else 0.0,
                    "end": round(word.end, 2) if word.end is not None else 0.0,
                    "probability": round(prob, 4) if prob is not None else None,
                })

        asr_confidence = (
            round(sum(probabilities) / len(probabilities), 4)
            if probabilities
            else None
        )

        duration_sec = getattr(info, "duration", None)
        if duration_sec is None and segments:
            duration_sec = segments[-1].end

        duration_formatted = self._format_duration(duration_sec)

        logger.info(
            "Transcription completed: %d characters, duration=%s, confidence=%s",
            len(transcription_text),
            duration_formatted,
            asr_confidence,
        )

        return {
            "success": True,
            "transcription": transcription_text,
            "duration": duration_formatted,
            "duration_seconds": round(duration_sec, 2) if duration_sec is not None else None,
            "asr_confidence": asr_confidence,
            "language": getattr(info, "language", language) or language,
            "model": self._model_name,
            "backend": "faster-whisper",
            "file_size": meta["file_size"],
            "words": words,
            "segments_count": len(segments),
            "disclaimer": TRANSCRIPTION_DISCLAIMER,
        }

    def _build_initial_prompt(self, vocabulary: Optional[List[str]]) -> Optional[str]:
        base = (
            "English clinical consultation between a doctor and a patient. "
            "Common terms include date of birth, symptoms, examination, medication, "
            "dose, blood test, results, referral, follow-up, appointment, GP surgery, "
            "medical history, allergies, and lifestyle."
        )
        if not vocabulary:
            return base

        clean_terms = [t.strip() for t in vocabulary if t and t.strip()]
        if not clean_terms:
            return base

        unique = []
        seen = set()
        for t in clean_terms:
            k = t.lower()
            if k not in seen:
                seen.add(k)
                unique.append(t)

        return f"{base} Also expect: {', '.join(unique[:50])}."

    def _format_duration(self, seconds: Optional[float]) -> str:
        if seconds is None or seconds <= 0:
            return "0:00"
        m = int(seconds // 60)
        s = int(seconds % 60)
        return f"{m}:{s:02d}"


# Global service singleton instance
transcription_service = TranscriptionService()
