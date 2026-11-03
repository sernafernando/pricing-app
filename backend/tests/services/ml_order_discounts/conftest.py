"""Shared wiring for the per-sale discounts tests (same pattern as `tests/services/ml_ads/conftest.py`).

Importing the models registers the tables in `Base.metadata` at collection time; the Postgres engine creates
only these tables and `ml_payments_ops` (the source of the pending orders), per test.
"""

from __future__ import annotations

import json
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import inspect as sa_inspect, text
from sqlalchemy.orm import sessionmaker

from app.models import ml_order_discounts as models
from app.models.ml_payments import MlPaymentOps

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "ml_order_discounts"
TABLES = [
    models.MlOrderDiscounts.__table__,
    models.MlOrderDiscountLine.__table__,
    models.MlOrderDiscountsState.__table__,
    MlPaymentOps.__table__,
]
_PRISTINE_TYPES = {column: column.type for table in TABLES for column in table.columns}


def restore_pg_types() -> None:
    for column, column_type in _PRISTINE_TYPES.items():
        column.type = column_type


def fixture(name: str) -> Any:
    return json.loads((FIXTURES / f"{name}.json").read_text())


@pytest.fixture()
def pg_discounts_engine():
    from sqlalchemy import create_engine

    from tests.conftest import (
        POSTGRES_TEST_URL,
        _patch_pg_types_for_sqlite,
        _postgres_reachable,
        _restore_pristine_pg_types,
    )

    if not _postgres_reachable():
        pytest.skip(f"PostgreSQL not reachable at {POSTGRES_TEST_URL}")
    _restore_pristine_pg_types(TABLES)
    restore_pg_types()
    eng = create_engine(POSTGRES_TEST_URL)
    # `ml_payments_ops` may already exist (other modules' fixtures, with tables referencing it): reuse it emptied
    # and drop it only when this fixture created it.
    created = [table for table in TABLES if not sa_inspect(eng).has_table(table.name)]
    for table in TABLES:
        table.create(bind=eng, checkfirst=True)
    with eng.begin() as conn:
        conn.execute(text("TRUNCATE " + ", ".join(table.name for table in TABLES) + " CASCADE"))
    yield eng
    for table in reversed(TABLES):
        if table in created or table is not MlPaymentOps.__table__:
            table.drop(bind=eng, checkfirst=True)
    _patch_pg_types_for_sqlite()
    eng.dispose()


@pytest.fixture()
def session_factory(pg_discounts_engine):
    """A `get_background_db`-like factory: commit on success, rollback on error, close."""
    maker = sessionmaker(bind=pg_discounts_engine, expire_on_commit=False)

    @contextmanager
    def factory():
        db = maker()
        try:
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    return factory
