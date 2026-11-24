"""The app's tables on Postgres for router tests whose code runs Postgres-only SQL (costo SI's `generado` expands the
steps' JSONB with `jsonb_array_elements`; production runs on Postgres only).

A test module that imports `engine` from here gets it instead of the conftest's SQLite one, so the conftest `db` (one
SAVEPOINT per test, rolled back) and `client` run on a throwaway Postgres schema holding the app's tables, without the
pgvector ones (the test database has no `vector` extension). Mark the module `pytest.mark.postgres`.
"""

from __future__ import annotations

from typing import Iterator

import pytest
from pgvector.sqlalchemy import Vector
from sqlalchemy import Engine, text

import app.main  # noqa: F401 - registers every model in Base.metadata
from app.core.database import Base
from tests.conftest import _PRISTINE_PG_COLUMN_TYPES, _patch_pg_types_for_sqlite
from tests.services.sell._schema import throwaway_schema


def _tables():
    def vector(column) -> bool:
        # The SQLite suite may have patched the type already: judge by the real one.
        return isinstance(_PRISTINE_PG_COLUMN_TYPES.get(column, column.type), Vector)

    return [t for t in Base.metadata.sorted_tables if not any(vector(c) for c in t.columns)]


def _sin_semilla(engine: Engine) -> None:
    # The routers' autouse `_bom_sincronizado` seeds the bill of materials in each test, as on SQLite.
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM combo_componentes"))


@pytest.fixture(scope="module")
def engine() -> Iterator[Engine]:
    """`throwaway_schema` puts the real Postgres types back on every app column (`_restore_pristine_pg_types`); they
    stay for this module's tests and are patched for SQLite again after it, or the session's SQLite `engine` would
    bind a list to a Postgres ARRAY in every later module (`ml_group_metrics.member_order_ids`)."""
    try:
        with throwaway_schema("routers_pg", _tables(), after=_sin_semilla) as eng:
            yield eng
    finally:
        _patch_pg_types_for_sqlite()
