"""Add ontology codes to medical_entities.

Entities were stored as bare strings, which makes them a word list rather than
clinical data. A code turns "amlodipine", "Amlodipine" and "amlodipine
besylate" into one identity, which is what coding suggestions, interaction
checks and cross-visit matching all need.

`ontology_requires_review` is stored rather than inferred because the two
sources differ in kind: an RxNorm medication match is a resolution, while an
ICD-10 condition code is a suggestion from a ranked shortlist. Whoever reads
these rows later has to be able to tell those apart.

Revision ID: 20260909_0003
Revises: 20260909_0002
Create Date: 2026-09-09
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260909_0003"
down_revision: Union[str, Sequence[str], None] = "20260909_0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _column_exists(table_name: str, column_name: str) -> bool:
    bind = op.get_bind()
    return any(column["name"] == column_name for column in sa.inspect(bind).get_columns(table_name))


_NEW_COLUMNS = (
    sa.Column("ontology_system", sa.String(), nullable=True),      # RXNORM | ICD10CM
    sa.Column("ontology_code", sa.String(), nullable=True),
    sa.Column("ontology_display", sa.String(), nullable=True),
    sa.Column(
        "ontology_requires_review", sa.Boolean(), nullable=False, server_default=sa.false()
    ),
)


def upgrade() -> None:
    for column in _NEW_COLUMNS:
        if not _column_exists("medical_entities", column.name):
            op.add_column("medical_entities", column.copy())


def downgrade() -> None:
    for column in reversed(_NEW_COLUMNS):
        if _column_exists("medical_entities", column.name):
            op.drop_column("medical_entities", column.name)
