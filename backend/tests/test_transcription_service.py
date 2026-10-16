"""Unit tests for the dedicated Faster-Whisper transcription service.

Covers:
- Model configuration and singleton availability
- Validation of audio files (missing, empty, oversized, unsupported formats)
- Synthetic WAV generation and decodability validation
- Transcription processing (duration, confidence, word timestamps)
- Empty speech detection (EmptyAudioError)
- Inference failure handling (TranscriptionError)
- Clinical disclaimers (medical vocabulary, accents, noise, Tamil-English code-switching)
"""

import math
import os
import struct
import wave
import pytest

from transcription_service import (
    TranscriptionService,
    AudioValidationError,
    EmptyAudioError,
    ModelLoadError,
    TranscriptionError,
    TRANSCRIPTION_DISCLAIMER,
    SUPPORTED_AUDIO_EXTENSIONS,
)


def _generate_synthetic_wav(filepath: str, duration_sec: float = 1.0, freq: float = 440.0) -> str:
    """Generate a clean synthetic 16kHz mono PCM WAV file for testing."""
    sample_rate = 16000
    num_samples = int(sample_rate * duration_sec)
    with wave.open(filepath, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sample_rate)
        frames = bytearray()
        for i in range(num_samples):
            # 440Hz sine wave tone
            val = int(32767.0 * 0.4 * math.sin(2.0 * math.pi * freq * (i / sample_rate)))
            frames.extend(struct.pack("<h", val))
        w.writeframes(frames)
    return filepath


# ── Configuration & Availability ─────────────────────────────────────────────

def test_service_initialization_and_config():
    service = TranscriptionService()
    assert service.model_name is not None
    assert service.is_available() is True
    assert "tamil-english" in TRANSCRIPTION_DISCLAIMER.lower()
    assert "clinician" in TRANSCRIPTION_DISCLAIMER.lower()


def test_disclaimer_includes_required_clinical_guidance():
    assert "accuracy" in TRANSCRIPTION_DISCLAIMER.lower()
    assert "noise" in TRANSCRIPTION_DISCLAIMER.lower()
    assert "accents" in TRANSCRIPTION_DISCLAIMER.lower()
    assert "medical" in TRANSCRIPTION_DISCLAIMER.lower()
    assert "tamil-english" in TRANSCRIPTION_DISCLAIMER.lower()


# ── Audio File Validation ─────────────────────────────────────────────────────

def test_validate_missing_file_raises_error(tmp_path):
    service = TranscriptionService()
    missing_file = str(tmp_path / "non_existent.wav")
    with pytest.raises(AudioValidationError) as exc:
        service.validate_audio_file(missing_file)
    assert "does not exist" in str(exc.value)


def test_validate_empty_file_raises_error(tmp_path):
    service = TranscriptionService()
    empty_file = str(tmp_path / "empty.wav")
    with open(empty_file, "wb") as f:
        pass  # 0 bytes

    with pytest.raises(AudioValidationError) as exc:
        service.validate_audio_file(empty_file)
    assert "0 bytes" in str(exc.value)


def test_validate_unsupported_format_raises_error(tmp_path):
    service = TranscriptionService()
    doc_file = str(tmp_path / "clinical_summary.txt")
    with open(doc_file, "wb") as f:
        f.write(b"Dr notes")

    with pytest.raises(AudioValidationError) as exc:
        service.validate_audio_file(doc_file)
    assert "Unsupported audio format" in str(exc.value)


def test_validate_oversized_file_raises_error(tmp_path, monkeypatch):
    service = TranscriptionService()
    oversized_file = str(tmp_path / "large.wav")
    with open(oversized_file, "wb") as f:
        f.write(b"fake audio data")

    # Mock getsize to simulate 55 MB file
    monkeypatch.setattr(os.path, "getsize", lambda p: 55 * 1024 * 1024)

    with pytest.raises(AudioValidationError) as exc:
        service.validate_audio_file(oversized_file)
    assert "exceeds maximum accepted limit of 50 MB" in str(exc.value)


def test_validate_valid_synthetic_wav(tmp_path):
    service = TranscriptionService()
    wav_path = str(tmp_path / "valid_test.wav")
    _generate_synthetic_wav(wav_path, duration_sec=1.5)

    meta = service.validate_audio_file(wav_path)
    assert meta["file_size"] > 0
    assert meta["extension"] == ".wav"


# ── Transcription Execution & Error Handling ─────────────────────────────────

class _MockWord:
    def __init__(self, word: str, start: float, end: float, prob: float):
        self.word = word
        self.start = start
        self.end = end
        self.probability = prob


class _MockSegment:
    def __init__(self, text: str, start: float, end: float, words: list):
        self.text = text
        self.start = start
        self.end = end
        self.words = words


class _MockTranscriptionInfo:
    def __init__(self, duration: float = 3.5, language: str = "en"):
        self.duration = duration
        self.language = language


class _MockWhisperModel:
    def __init__(self, should_fail: bool = False, return_empty: bool = False):
        self.should_fail = should_fail
        self.return_empty = return_empty

    def transcribe(self, *args, **kwargs):
        if self.should_fail:
            raise RuntimeError("CUDA out of memory or inference crash")
        if self.return_empty:
            return iter([]), _MockTranscriptionInfo(duration=1.0)

        words = [
            _MockWord("Patient", 0.0, 0.4, 0.98),
            _MockWord("reports", 0.45, 0.8, 0.95),
            _MockWord("headache", 0.85, 1.4, 0.92),
        ]
        segments = [_MockSegment("Patient reports headache", 0.0, 1.4, words)]
        return iter(segments), _MockTranscriptionInfo(duration=1.4)


def test_transcribe_successful_synthetic_audio(tmp_path, monkeypatch):
    service = TranscriptionService()
    wav_path = str(tmp_path / "synthetic_encounter.wav")
    _generate_synthetic_wav(wav_path, duration_sec=1.4)

    # Inject mock model
    monkeypatch.setattr(service, "get_model", lambda: _MockWhisperModel())

    result = service.transcribe(wav_path, vocabulary=["headache", "migraine"])
    assert result["success"] is True
    assert result["transcription"] == "Patient reports headache"
    assert result["duration"] == "0:01"
    assert result["duration_seconds"] == 1.4
    assert result["asr_confidence"] == 0.95
    assert len(result["words"]) == 3
    assert result["words"][0]["word"] == "Patient"
    assert "disclaimer" in result
    assert result["disclaimer"] == TRANSCRIPTION_DISCLAIMER


def test_transcribe_empty_audio_raises_empty_error(tmp_path, monkeypatch):
    service = TranscriptionService()
    wav_path = str(tmp_path / "silent.wav")
    _generate_synthetic_wav(wav_path, duration_sec=1.0)

    # Model returns zero segments
    monkeypatch.setattr(service, "get_model", lambda: _MockWhisperModel(return_empty=True))

    with pytest.raises(EmptyAudioError) as exc:
        service.transcribe(wav_path)
    assert "No speech was detected" in str(exc.value)


def test_transcribe_inference_crash_raises_transcription_error(tmp_path, monkeypatch):
    service = TranscriptionService()
    wav_path = str(tmp_path / "crash_audio.wav")
    _generate_synthetic_wav(wav_path, duration_sec=1.0)

    # Model raises inference exception
    monkeypatch.setattr(service, "get_model", lambda: _MockWhisperModel(should_fail=True))

    with pytest.raises(TranscriptionError) as exc:
        service.transcribe(wav_path)
    assert "Speech recognition engine failed" in str(exc.value)
