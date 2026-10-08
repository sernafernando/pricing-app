"""Shared wiring for the ml-ads tests (ml-billing-balance, design "Test wiring").

Importing `app.models.ml_ads` here registers the `ml_ads_*` tables in `Base.metadata` during test
collection, before the session `engine` fixture of `tests/conftest.py` runs `create_all`; neither
the shared conftest nor `app/models/__init__.py` is edited (same precedent as `ml_billing`).
"""

from __future__ import annotations

import pytest
from sqlalchemy.orm import sessionmaker

from app.core.database import Base
from app.models import ml_ads as _ml_ads  # noqa: F401  (registers the tables in Base.metadata)
from app.models.worker_job_state import WorkerJobState

ADS_TABLES = [table for name, table in Base.metadata.tables.items() if name.startswith("ml_ads_")]

# Snapshot of the real Postgres column types, taken at collection time: `tests/conftest.py` takes its
# own snapshot before these tables are imported, so `_restore_pristine_pg_types` cannot undo what the
# SQLite `engine` fixture does to them (JSONB -> JSON, BigInteger primary keys -> Integer).
_PRISTINE_TYPES = {column: column.type for table in ADS_TABLES for column in table.columns}


def restore_pg_types() -> None:
    for column, column_type in _PRISTINE_TYPES.items():
        column.type = column_type


@pytest.fixture()
def pg_ads_engine():
    """Postgres engine with only the `ml_ads_*` tables and `worker_job_state`, created and dropped per test.

    Per-test DDL (three small tables) keeps the migration round trip in `test_models_migration.py`
    free of any ordering dependency with the model-built tables.
    """
    from sqlalchemy import create_engine

    from tests.conftest import (
        POSTGRES_TEST_URL,
        _patch_pg_types_for_sqlite,
        _postgres_reachable,
        _restore_pristine_pg_types,
    )

    if not _postgres_reachable():
        pytest.skip(f"PostgreSQL not reachable at {POSTGRES_TEST_URL}")

    tables = [*ADS_TABLES, WorkerJobState.__table__]
    _restore_pristine_pg_types(tables)
    restore_pg_types()
    eng = create_engine(POSTGRES_TEST_URL)
    # Per-table DDL, not `Base.metadata.create_all(tables=...)`: the latter walks the whole shared
    # metadata (enum bookkeeping) and can collide with other module-scoped Postgres fixtures.
    for table in tables:
        table.create(bind=eng, checkfirst=True)
    yield eng
    for table in reversed(tables):
        table.drop(bind=eng, checkfirst=True)
    _patch_pg_types_for_sqlite()
    eng.dispose()


@pytest.fixture()
def pg_ads_db(pg_ads_engine):
    """Transactional Postgres session over the ads tables, rolled back after each test."""
    connection = pg_ads_engine.connect()
    transaction = connection.begin()
    session = sessionmaker(bind=connection)()
    yield session
    session.close()
    transaction.rollback()
    connection.close()
