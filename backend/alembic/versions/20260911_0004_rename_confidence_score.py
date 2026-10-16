"""Rename transcriptions.confidence_score to medical_content_score.

The column never held a confidence. It stores `validate_medical_content`'s
term-density score multiplied by 100 — a measure of how medical the audio
sounded, computed before any note exists. The UI presented it as "Confidence"
with high/medium/low badges and a dashboard average, so a clinician reading
94% would reasonably take it as the system's confidence in the note, which it
has never been.

Renaming rather than dropping: the number is genuinely useful as a gate on
non-clinical audio, and the stored history stays meaningful once it is called
what it is. A real per-note confidence needs the word-level ASR probabilities
and entailment scores that Phase 4 and Phase 3 introduce.

Revision ID: 20260911_0004
Revises: 20260909_0003
Create Date: 2026-09-11
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260911_0004"
down_revision: Union[str, Sequence[str], None] = "20260909_0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TABLE = "transcriptions"
_OLD = "confidence_score"
_NEW = "medical_content_score"


def _columns() -> set[str]:
    bind = op.get_bind()
    return {column["name"] for column in sa.inspect(bind).get_columns(_TABLE)}


def upgrade() -> None:
    columns = _columns()
    if _OLD in columns and _NEW not in columns:
        # Supported by SQLite 3.25+ and PostgreSQL; both keep the data.
        op.alter_column(_TABLE, _OLD, new_column_name=_NEW, existing_type=sa.Float())


def downgrade() -> None:
    columns = _columns()
    if _NEW in columns and _OLD not in columns:
        op.alter_column(_TABLE, _NEW, new_column_name=_OLD, existing_type=sa.Float())
