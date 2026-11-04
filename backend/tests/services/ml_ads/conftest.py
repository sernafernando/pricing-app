"""Shared wiring for the ml-ads tests (ml-billing-balance, design "Test wiring").

Importing `app.models.ml_ads` here registers the `ml_ads_*` tables in `Base.metadata` during test
collection, before the session `engine` fixture of `tests/conftest.py` runs `create_all`; neither
the shared conftest nor `app/models/__init__.py` is edited (same precedent as `ml_billing`).
"""

from __future__ import annotations

import pytest
from sqlalchemy import Column, MetaData, Table
from sqlalchemy.orm import sessionmaker

from app.core.database import Base
from app.models.auditoria import Auditoria
from app.models import ml_ads as _ml_ads  # noqa: F401  (registers the tables in Base.metadata)
from app.models.producto import ProductoERP
from app.models.worker_job_state import WorkerJobState

ADS_TABLES = [table for name, table in Base.metadata.tables.items() if name.startswith("ml_ads_")]

# Snapshot of the real Postgres column types, taken at collection time: `tests/conftest.py` takes its
# own snapshot before these tables are imported, so `_restore_pristine_pg_types` cannot undo what the
# SQLite `engine` fixture does to them (JSONB -> JSON, BigInteger primary keys -> Integer).
_PRISTINE_TYPES = {column: column.type for table in ADS_TABLES for column in table.columns}


# An aporte write adds its `auditoria` row (ml-ads-aportes-robust S5). The stand-in keeps every column and type but not
# the foreign key to `usuarios`, which these per-test tables do not build. It lives only in `pg_ads_write_engine`'s
# throwaway schema, so a real `auditoria` another test left in the shared database never takes its place.
AUDIT_STANDIN = Table(
    "auditoria",
    MetaData(),
    *(Column(c.name, c.type, primary_key=c.primary_key, nullable=c.nullable) for c in Auditoria.__table__.columns),
)


def restore_pg_types() -> None:
    for column, column_type in _PRISTINE_TYPES.items():
        column.type = column_type


@pytest.fixture()
def pg_ads_engine():
    """Postgres engine with only the `ml_ads_*` tables, `worker_job_state` and `productos_erp`, created and dropped per test.

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

    # `productos_erp`: an aporte's brand must be one of its marcas (ml-ads-aportes-robust S1).
    tables = [*ADS_TABLES, WorkerJobState.__table__, ProductoERP.__table__]
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
def pg_ads_write_engine():
    """Postgres engine for the tests that write aportes: the `pg_ads_engine` tables plus the `auditoria` stand-in, in a
    throwaway schema (whatever other tests left in the shared database is invisible inside it)."""
    from tests.conftest import _patch_pg_types_for_sqlite
    from tests.services.sell._schema import throwaway_schema

    restore_pg_types()
    tables = [*ADS_TABLES, WorkerJobState.__table__, ProductoERP.__table__, AUDIT_STANDIN]
    try:
        with throwaway_schema("ads_write", tables) as engine:
            yield engine
    finally:
        _patch_pg_types_for_sqlite()


@pytest.fixture()
def pg_ads_write_db(pg_ads_write_engine):
    """Transactional session over `pg_ads_write_engine`, rolled back after each test."""
    connection = pg_ads_write_engine.connect()
    transaction = connection.begin()
    session = sessionmaker(bind=connection)()
    yield session
    session.close()
    transaction.rollback()
    connection.close()


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
