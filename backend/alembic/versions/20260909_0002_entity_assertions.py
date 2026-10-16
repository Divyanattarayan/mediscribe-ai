"""Add assertion attributes to medical_entities.

Negation, temporality, experiencer and uncertainty are what make a mention
mean something: "denies chest pain" and "reports chest pain" produce the same
row without them. Stored per entity so history rows keep the reading the
pipeline actually made, and so a later model change can be compared against
what an earlier one asserted.

Defaults match `clinical_assertions.DEFAULT_ASSERTIONS`, which is also what
rows written before this migration effectively meant: an unqualified,
current, patient-experienced mention.

Revision ID: 20260909_0002
Revises: 20260504_0001
Create Date: 2026-09-09
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260909_0002"
down_revision: Union[str, Sequence[str], None] = "20260504_0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _column_exists(table_name: str, column_name: str) -> bool:
    bind = op.get_bind()
    return any(column["name"] == column_name for column in sa.inspect(bind).get_columns(table_name))


_NEW_COLUMNS = (
    sa.Column("negated", sa.Boolean(), nullable=False, server_default=sa.false()),
    sa.Column("temporality", sa.String(), nullable=False, server_default="current"),
    sa.Column("experiencer", sa.String(), nullable=False, server_default="patient"),
    sa.Column("uncertain", sa.Boolean(), nullable=False, server_default=sa.false()),
    # Records whether ConText actually resolved this mention or whether it fell
    # back to the defaults, so a run with degraded assertion coverage is
    # visible in the data rather than indistinguishable from a clean one.
    sa.Column("assertion_source", sa.String(), nullable=False, server_default="default"),
)


def upgrade() -> None:
    for column in _NEW_COLUMNS:
        if not _column_exists("medical_entities", column.name):
            op.add_column("medical_entities", column.copy())


def downgrade() -> None:
    for column in reversed(_NEW_COLUMNS):
        if _column_exists("medical_entities", column.name):
            op.drop_column("medical_entities", column.name)
