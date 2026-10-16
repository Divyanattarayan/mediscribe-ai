"""Upload guards on POST /api/transcribe.

The transcription pipeline itself is stubbed (see conftest); these tests only
exercise the request-validation layer that runs before/around it.
"""

import io
from pathlib import Path

import pytest

import main
from tests.conftest import auth_header

BACKEND_DIR = Path(__file__).resolve().parent.parent


def _fake_pipeline(monkeypatch):
    """Neutralise every heavy pipeline call so the endpoint returns quickly."""
    monkeypatch.setattr(
        main,
        "transcribe_audio",
        lambda *a, **k: {
            "success": True,
            "text": "patient reports chest pain and shortness of breath",
            "duration": 120.0,
            "confidence": 0.88,
            "words": [],
            "language": "en",
            "error": None,
        },
    )
    monkeypatch.setattr(main, "correct_medical_spelling", lambda text, **k: (text, []))
    monkeypatch.setattr(
        main,
        "validate_medical_content",
        lambda *a, **k: {"is_valid": False, "confidence_score": 0.0, "reason": "stubbed", "details": {}},
    )


def test_unsupported_extension_is_rejected(client, make_user):
    token, _ = make_user()
    files = {"file": ("notes.txt", io.BytesIO(b"hello"), "text/plain")}
    response = client.post(
        "/api/transcribe",
        headers=auth_header(token),
        files=files,
        data={"encounter_type": "acute_visit"},
    )
    assert response.status_code == 400
    assert ".txt" in response.json()["detail"]


def test_transcribe_requires_authentication(client):
    files = {"file": ("a.mp3", io.BytesIO(b"\x00\x00"), "audio/mpeg")}
    response = client.post("/api/transcribe", files=files, data={"encounter_type": "acute_visit"})
    assert response.status_code in (401, 403)


def test_path_traversal_filename_cannot_escape_upload_dir(client, make_user, monkeypatch):
    """A crafted upload filename must never cause a write outside uploads/."""
    _fake_pipeline(monkeypatch)
    token, _ = make_user()

    sentinel = BACKEND_DIR / "main.py"
    original_bytes = sentinel.read_bytes()

    files = {"file": ("../../main.py.mp3", io.BytesIO(b"\x00" * 32), "audio/mpeg")}
    response = client.post(
        "/api/transcribe",
        headers=auth_header(token),
        files=files,
        data={"encounter_type": "acute_visit"},
    )

    # Filename is display-only metadata now; the upload is handled normally and
    # written under a generated name.
    assert response.status_code == 200
    assert response.json()["filename"] == "../../main.py.mp3"
    assert sentinel.read_bytes() == original_bytes
    assert not (BACKEND_DIR / "main.py.mp3").exists()
    assert not (BACKEND_DIR.parent / "main.py.mp3").exists()


def test_upload_dir_is_empty_after_a_request(client, make_user, monkeypatch):
    """Temp audio is always cleaned up, success or failure."""
    _fake_pipeline(monkeypatch)
    token, _ = make_user()

    upload_dir = BACKEND_DIR / "uploads"
    files = {"file": ("clip.mp3", io.BytesIO(b"\x00" * 64), "audio/mpeg")}
    client.post(
        "/api/transcribe",
        headers=auth_header(token),
        files=files,
        data={"encounter_type": "acute_visit"},
    )

    leftovers = [p for p in upload_dir.glob("*") if p.is_file()] if upload_dir.exists() else []
    assert leftovers == []


def test_removed_download_endpoint_is_gone(client):
    response = client.post("/api/download", json={"content": "x", "filename": "n.txt"})
    assert response.status_code in (404, 405)


def test_oversize_upload_is_rejected(client, make_user, monkeypatch):
    _fake_pipeline(monkeypatch)
    token, _ = make_user()

    big = b"\x00" * (60 * 1024 * 1024)  # 60 MB, over the documented 50 MB cap
    files = {"file": ("big.mp3", io.BytesIO(big), "audio/mpeg")}
    response = client.post(
        "/api/transcribe",
        headers=auth_header(token),
        files=files,
        data={"encounter_type": "acute_visit"},
    )
    assert response.status_code == 413
