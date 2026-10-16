"""TextGrid parsing and streamed audio fetching.

Both sit between a public dataset and the metrics, so a silent bug here would
corrupt every WER number without failing anything. No network and no real
dataset: the TextGrid fixtures are trimmed copies of the PriMock57 format, and
the downloader is exercised against a stubbed `urlopen`.
"""

import io
import urllib.error

import pytest

from eval import audio_source, textgrid

# Trimmed to the fields the parser reads, with the real tag syntax and an empty
# interval (silence) of the kind every PriMock57 file contains.
TEXTGRID = '''File type = "ooTextFile"
Object class = "TextGrid"

xmin = 0
xmax = 60
tiers? <exists>
size = 1
item []:
    item [1]:
        class = "IntervalTier"
        name = "Doctor"
        xmin = 0
        xmax = 60
        intervals: size = 4
        intervals [1]:
            xmin = 0
            xmax = 2.5
            text = ""
        intervals [2]:
            xmin = 2.5
            xmax = 12.0
            text = "Good morning, how can I help?"
        intervals [3]:
            xmin = 20.0
            xmax = 30.0
            text = "<UNIN/> and when you say <UNSURE>diarrhea</UNSURE>, what do you mean?"
        intervals [4]:
            xmin = 40.0
            xmax = 50.0
            text = "   "
'''

PATIENT_TEXTGRID = '''File type = "ooTextFile"
Object class = "TextGrid"
xmin = 0
xmax = 60
tiers? <exists>
size = 1
item []:
    item [1]:
        class = "IntervalTier"
        name = "Patient"
        xmin = 0
        xmax = 60
        intervals: size = 2
        intervals [1]:
            xmin = 13.0
            xmax = 19.0
            text = "I have had diarrhea for three days."
        intervals [2]:
            xmin = 31.0
            xmax = 38.0
            text = "Watery, mostly."
'''


@pytest.fixture
def doctor_grid(tmp_path):
    path = tmp_path / "day1_consultation01_doctor.TextGrid"
    path.write_text(TEXTGRID, encoding="utf-8")
    return path


@pytest.fixture
def patient_grid(tmp_path):
    path = tmp_path / "day1_consultation01_patient.TextGrid"
    path.write_text(PATIENT_TEXTGRID, encoding="utf-8")
    return path


# ── TextGrid ──────────────────────────────────────────────────────────────────

def test_silence_intervals_are_dropped(doctor_grid):
    utterances = textgrid.read_textgrid(doctor_grid)
    assert len(utterances) == 2      # two of four intervals hold speech


def test_utterances_carry_timings_and_speaker(doctor_grid):
    first = textgrid.read_textgrid(doctor_grid)[0]
    assert (first.start, first.end) == (2.5, 12.0)
    assert first.speaker == "Doctor"


def test_unsure_markers_are_stripped_but_the_words_are_kept():
    """The transcriber's best guess is still the best reference available."""
    assert textgrid.clean_transcript_text("say <UNSURE>diarrhea</UNSURE> now") == "say diarrhea now"


def test_unintelligible_regions_are_removed_entirely():
    """There is no reference text for them, so scoring against the tag would
    charge the ASR for words no human could make out."""
    cleaned = textgrid.clean_transcript_text("<UNIN/> and when you say")
    assert "UNIN" not in cleaned
    assert cleaned == "and when you say"


def test_transcript_text_joins_utterances_in_time_order(doctor_grid):
    text = textgrid.transcript_text(doctor_grid)
    assert text.startswith("Good morning")
    assert "<" not in text
    assert text.index("Good morning") < text.index("what do you mean")


def test_merging_channels_interleaves_by_start_time(doctor_grid, patient_grid):
    """Each channel is recorded separately, so the conversation only exists
    once the two are merged in time order."""
    merged = textgrid.merge_channels(doctor_grid, patient_grid)
    lines = merged.splitlines()
    assert lines[0].startswith("Doctor: Good morning")
    assert lines[1].startswith("Patient: I have had diarrhea")
    assert lines[2].startswith("Doctor:")
    assert lines[3].startswith("Patient: Watery")


def test_merged_dialogue_is_speaker_labelled(doctor_grid, patient_grid):
    merged = textgrid.merge_channels(doctor_grid, patient_grid)
    assert all(line.startswith(("Doctor:", "Patient:")) for line in merged.splitlines())


# ── Streamed audio ────────────────────────────────────────────────────────────

class _FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
        return False


def _stub_urlopen(monkeypatch, payload=b"x" * 20_000, error=None):
    calls = []

    def fake_urlopen(request, timeout=None):
        calls.append(request.full_url)
        if error is not None:
            raise error
        return _FakeResponse(payload)

    monkeypatch.setattr(audio_source.urllib.request, "urlopen", fake_urlopen)
    return calls


def test_audio_url_points_at_the_lfs_media_host():
    """A plain raw.githubusercontent URL returns the LFS pointer text, not the
    audio; the media host returns the bytes."""
    url = audio_source.primock57_audio_url("day1_consultation01_doctor.wav")
    assert url.startswith(audio_source.GITHUB_LFS_MEDIA)
    assert url.endswith("/audio/day1_consultation01_doctor.wav")


def test_streamed_audio_is_deleted_after_use(monkeypatch):
    _stub_urlopen(monkeypatch)
    with audio_source.local_audio(None, "https://example.test/a.wav") as path:
        assert path.exists()
        held = path
    assert not held.exists()
    assert not held.parent.exists()


def test_an_existing_local_file_is_used_and_never_deleted(monkeypatch, tmp_path):
    calls = _stub_urlopen(monkeypatch)
    local = tmp_path / "a.wav"
    local.write_bytes(b"y" * 20_000)

    with audio_source.local_audio(str(local), "https://example.test/a.wav") as path:
        assert path == local
    assert local.exists()
    assert calls == []       # nothing was fetched


def test_a_stale_lfs_pointer_is_treated_as_missing(monkeypatch, tmp_path):
    """A pointer file is ~130 bytes of text. Handing that to Whisper would
    produce a transcript of nothing and a silently wrong WER."""
    calls = _stub_urlopen(monkeypatch)
    pointer = tmp_path / "a.wav"
    pointer.write_text("version https://git-lfs.github.com/spec/v1\noid sha256:abc\nsize 14653484\n")

    with audio_source.local_audio(str(pointer), "https://example.test/a.wav") as path:
        assert path != pointer
        assert path.stat().st_size == 20_000
    assert len(calls) == 1


def test_a_cached_file_is_downloaded_once(monkeypatch, tmp_path):
    calls = _stub_urlopen(monkeypatch)
    cache = tmp_path / "cache"

    for _ in range(3):
        with audio_source.local_audio(None, "https://example.test/a.wav", cache_dir=cache) as path:
            assert path.exists()
    assert len(calls) == 1
    assert (cache / "a.wav").exists()      # kept, unlike the streamed case


def test_a_failed_download_leaves_no_partial_file(monkeypatch, tmp_path):
    """A truncated file would be indistinguishable from a real one on the next
    cached run."""
    _stub_urlopen(monkeypatch, error=urllib.error.URLError("boom"))
    destination = tmp_path / "a.wav"

    with pytest.raises(urllib.error.URLError):
        audio_source.download("https://example.test/a.wav", destination)

    assert not destination.exists()
    assert list(tmp_path.glob("*.part")) == []


def test_no_path_and_no_url_is_an_error():
    with pytest.raises(FileNotFoundError):
        with audio_source.local_audio(None, None):
            pass
