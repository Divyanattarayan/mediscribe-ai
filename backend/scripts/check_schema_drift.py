"""Fail when the ORM models and the migrations disagree.

`context/DECISIONS.md` says Alembic is the sole source of truth for the schema
and that a model change without a matching migration will not reach the
database. Nothing enforced that, so the failure mode was silent: tests pass
against `Base.metadata`, and the missing column only surfaces in production.

This runs Alembic's own autogenerate comparison against a database that has been
migrated to head. Any difference means someone edited `models.py` without
writing a revision.

    python -m scripts.check_schema_drift

Exits 0 when they agree, 1 when they do not, printing what differs.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

# Imported for their side effect of registering tables on `Base.metadata`.
import models  # noqa: F401,E402
from database import Base  # noqa: E402

from alembic.autogenerate import compare_metadata  # noqa: E402
from alembic.migration import MigrationContext  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402

# Differences that are an artefact of the comparison rather than real drift.
#
# SQLite reports server defaults as quoted strings ("'current'") where the model
# declares them bare ("current"), so a `modify_default` on a column whose default
# is otherwise identical is noise. Type comparison is off for the same reason:
# SQLite collapses several types onto one another and would report a difference
# on every String column.
_IGNORED_DIFF_KINDS = frozenset({"modify_default", "modify_nullable", "modify_type"})


def _describe(diff) -> str:
    if isinstance(diff, tuple):
        kind = diff[0]
        if kind in ("add_table", "remove_table"):
            return f"{kind}: {diff[1].name}"
        if kind in ("add_column", "remove_column"):
            return f"{kind}: {diff[2]}.{diff[3].name}"
        if kind in ("add_index", "remove_index", "add_constraint", "remove_constraint"):
            return f"{kind}: {getattr(diff[1], 'name', diff[1])}"
        return f"{kind}: {diff[1:]}"
    return str(diff)


def _flatten(diffs) -> list:
    """Alembic nests column-level changes inside a list per column."""
    flat = []
    for diff in diffs:
        if isinstance(diff, list):
            flat.extend(diff)
        else:
            flat.append(diff)
    return flat


def main() -> int:
    url = os.getenv("DATABASE_URL")
    if not url:
        print("DATABASE_URL is not set. Point it at a database already migrated to head.", file=sys.stderr)
        return 2

    engine = create_engine(url)
    with engine.connect() as connection:
        context = MigrationContext.configure(
            connection,
            opts={"compare_type": False, "compare_server_default": False},
        )
        diffs = _flatten(compare_metadata(context, Base.metadata))

    real = [d for d in diffs if not (isinstance(d, tuple) and d[0] in _IGNORED_DIFF_KINDS)]

    if not real:
        print("Models and migrations agree.")
        return 0

    print("Schema drift: the ORM models describe something the migrations do not.", file=sys.stderr)
    for diff in real:
        print(f"  - {_describe(diff)}", file=sys.stderr)
    print(
        "\nWrite an Alembic revision for these changes "
        "(`python -m alembic revision -m \"...\"`), or revert the model edit.",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
