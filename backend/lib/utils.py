# backend/lib/utils.py
# Small utility functions used by main.py.

import secrets


def generate_patient_id() -> str:
    """
    Returns a random encounter label, e.g. PT-48213905.

    Uses an 8-digit cryptographically-random suffix rather than 5 digits so
    collisions stay negligible as the transcription table grows (the column has
    no unique constraint). This identifies an encounter, not a longitudinal
    patient record.
    """
    return f"PT-{secrets.randbelow(90_000_000) + 10_000_000}"


def format_duration_mmss(seconds: float | None) -> str | None:
    """Format a duration in seconds as ``M:SS``. Returns ``None`` when unknown."""
    if seconds is None or seconds < 0:
        return None
    total = int(round(seconds))
    return f"{total // 60}:{total % 60:02d}"


def safe_delete_audio_file(audio_path: str | None, base_upload_dir: str = "uploads") -> bool:
    """
    Safely delete an uploaded audio file from disk.

    Verifies that the file path resolves strictly within the designated
    base upload directory before unlinking to prevent path traversal issues.
    Returns True if a file was deleted, False if none existed or deletion failed.
    """
    if not audio_path:
        return False

    import os
    from pathlib import Path
    import logging
    logger = logging.getLogger("mediscribe.storage")

    try:
        resolved_file = Path(audio_path).resolve()
        resolved_base = Path(base_upload_dir).resolve()

        # Ensure the file is strictly inside the uploads directory
        if resolved_base not in resolved_file.parents:
            logger.warning("Refused deletion of file outside upload directory: %s", audio_path)
            return False

        if resolved_file.exists() and resolved_file.is_file():
            resolved_file.unlink()
            logger.info("Successfully deleted audio file: %s", resolved_file.name)
            return True
    except Exception as e:
        logger.warning("Error deleting audio file %s: %s", audio_path, e)
        return False

    return False