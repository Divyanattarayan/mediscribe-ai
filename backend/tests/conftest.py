"""Shared pytest fixtures for the MediScribe AI backend suite.

Design goals:
- The suite must start in well under a second. The heavy ML dependencies
  (`faster_whisper.WhisperModel`, the scispaCy NER model) are stubbed here
  *before* any backend module is imported, so no model files are ever loaded.
- No PostgreSQL required. `get_db` is overridden to hand out sessions bound to
  an in-memory SQLite database that is recreated for every test.
"""

from __future__ import annotations

import os
import sys
import types
from pathlib import Path

import pytest

# ── Make `backend/` importable regardless of the working directory ────────────
BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

# ── Environment variables required by database.py / auth.py at import time ─────
os.environ.setdefault("JWT_SECRET_KEY", "test-secret-not-for-production-0123456789")
os.environ.setdefault("DATABASE_URL", "sqlite://")
os.environ.setdefault("GROQ_API_KEY", "test-groq-key")

# No test may reach the network. These three stages call out to a model or to
# the NLM APIs when enabled, and a suite that quietly depends on either is both
# slow and flaky — a failing test would mean "the internet is down", not "the
# code is wrong". Tests that need this behaviour stub it explicitly.
os.environ.setdefault("FACT_TABLE_LLM", "0")
os.environ.setdefault("CLAIM_VERIFICATION", "0")
os.environ.setdefault("ONTOLOGY_LINKING", "0")

# Rate-limit pacing is real wall-clock sleeping, and tests stub the client
# anyway, so there is no quota to protect here — without this a handful of
# provider tests sat out a 12.5 second interval each and the suite went from
# 19 seconds to over a minute. Tests covering the pacing set their own interval.
os.environ.setdefault("GEMINI_MIN_REQUEST_INTERVAL", "0")
os.environ.setdefault("CEREBRAS_MIN_REQUEST_INTERVAL", "0")


# ── Stub heavy ML modules before `transcription` / `entity_extraction` load ───
def _install_ml_stubs() -> None:
    if "faster_whisper" not in sys.modules:
        fw = types.ModuleType("faster_whisper")

        class _StubWhisperModel:  # noqa: D401 - test stub
            def __init__(self, *args, **kwargs) -> None:
                pass

            def transcribe(self, *args, **kwargs):
                raise RuntimeError("faster-whisper is stubbed in the test suite")

        fw.WhisperModel = _StubWhisperModel
        sys.modules["faster_whisper"] = fw

    # entity_extraction.py calls spacy.load("en_ner_bc5cdr_md") at import time.
    import spacy

    _real_load = spacy.load

    def _patched_load(name, *args, **kwargs):
        if isinstance(name, str) and ("bc5cdr" in name or "en_core_sci" in name):
            return spacy.blank("en")
        return _real_load(name, *args, **kwargs)

    spacy.load = _patched_load


_install_ml_stubs()

# ── Rebind the app's engine to a shared in-memory SQLite database ─────────────
# database.get_db() resolves SessionLocal from the database module namespace at
# call time, so rebinding here is enough — no dependency override needed, and
# auth.get_current_user (which also Depends(get_db)) picks it up automatically.
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import database  # noqa: E402

database.engine = create_engine(
    "sqlite://",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
database.SessionLocal = sessionmaker(
    bind=database.engine, autoflush=False, autocommit=False
)

import models  # noqa: E402
import main  # noqa: E402

_test_engine = database.engine
_TestingSessionLocal = database.SessionLocal


@pytest.fixture(autouse=True)
def _fresh_database():
    """Recreate every table before each test so cases are fully isolated."""
    models.Base.metadata.drop_all(bind=_test_engine)
    models.Base.metadata.create_all(bind=_test_engine)
    yield
    models.Base.metadata.drop_all(bind=_test_engine)


@pytest.fixture
def client():
    from fastapi.testclient import TestClient

    with TestClient(main.app) as test_client:
        yield test_client


@pytest.fixture
def db_session():
    session = _TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()


# ── Convenience helpers ──────────────────────────────────────────────────────

_DEFAULT_PASSWORD = "correct horse battery"


def register(client, email: str, password: str = _DEFAULT_PASSWORD, **extra):
    payload = {
        "email": email,
        "password": password,
        "first_name": extra.get("first_name", "Test"),
        "last_name": extra.get("last_name", "User"),
        "specialty": extra.get("specialty", "general"),
    }
    return client.post("/api/auth/register", json=payload)


def auth_header(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def make_user(client):
    """Return a factory that registers a user and returns (token, user_dict)."""

    created = {"n": 0}

    def _factory(email: str | None = None, password: str = _DEFAULT_PASSWORD):
        created["n"] += 1
        email = email or f"user{created['n']}@example.com"
        response = register(client, email, password)
        assert response.status_code == 201, response.text
        body = response.json()
        return body["access_token"], body["user"]

    return _factory
