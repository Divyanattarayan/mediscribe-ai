"""Add transcriptions.asr_confidence.

The project has never had a real confidence. `confidence_score` was the
validator's medical-term density (renamed to `medical_content_score` in
20260911_0004), and `MedicalEntity.confidence` was a hardcoded 0.0 until
ontology linking filled it for medications.

This one is genuine: the mean per-word probability the acoustic model assigned
to its own output, available once `word_timestamps=True` (Phase 4). It answers
"how sure was the recogniser about these words", which is the question a
clinician reading a transcript actually has.

Nullable, because it is only produced by the faster-whisper path with word
timestamps enabled; rows transcribed any other way genuinely have no value
rather than a zero.

Revision ID: 20260911_0005
Revises: 20260911_0004
Create Date: 2026-09-11
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260911_0005"
down_revision: Union[str, Sequence[str], None] = "20260911_0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _column_exists(table: str, column: str) -> bool:
    bind = op.get_bind()
    return any(c["name"] == column for c in sa.inspect(bind).get_columns(table))


def upgrade() -> None:
    if not _column_exists("transcriptions", "asr_confidence"):
        op.add_column("transcriptions", sa.Column("asr_confidence", sa.Float(), nullable=True))


def downgrade() -> None:
    if _column_exists("transcriptions", "asr_confidence"):
        op.drop_column("transcriptions", "asr_confidence")
