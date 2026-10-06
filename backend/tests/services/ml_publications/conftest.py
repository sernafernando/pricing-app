"""Loader helpers for the real ML captures under tests/fixtures/ml_publications/.

Every payload used by the ml_publications tests comes from these files (real
production captures, 2026-10-06). Tests that need a transition mutate a deep
copy of a real payload by exactly one field and say so in their docstring.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest

FIXTURES_DIR = Path(__file__).resolve().parents[2] / "fixtures" / "ml_publications"

BULK_CAPTURE = "items_bulk_capture_20261006_015628.json"
ITEM_SAMPLES = "items_bulk_samples_20261006.json"
ITEM_WITH_VARIATIONS = "item_with_variations_MLA1207279308.json"


def load_fixture(name: str) -> Any:
    with (FIXTURES_DIR / name).open(encoding="utf-8") as handle:
        return json.load(handle)


def bulk_call(name: str) -> Any:
    """Body of one named call of the `/items/bulk` capture (deep copy)."""
    for call in load_fixture(BULK_CAPTURE)["calls"]:
        if call["name"] == name:
            return copy.deepcopy(call["body"])
    raise KeyError(name)


def sample_item(item_id: str) -> dict:
    """Full item body (the `body` of a 200 `/items/bulk` element) captured for `item_id`."""
    for element in load_fixture(ITEM_SAMPLES)["elements"]:
        if element["id"] == item_id:
            return copy.deepcopy(element["body"])
    raise KeyError(item_id)


def bulk_item(item_id: str) -> dict:
    """Full item body from the first `/items/bulk` capture (MLA935110613, MLA934406852)."""
    for element in bulk_call("bulk_full"):
        if element.get("id") == item_id:
            return copy.deepcopy(element["body"])
    raise KeyError(item_id)


@pytest.fixture
def fixture_loader():
    return load_fixture


KEYED_ARRAYS = "keyed_arrays_promotions_visits_20261006.json"


def keyed_sample(name: str) -> Any:
    """Real promotions list / visits body used to exercise the natural-key overrides."""
    return copy.deepcopy(load_fixture(KEYED_ARRAYS)[name])


# --- Postgres schema for the infrastructure tests (settings store, queue) -----------------


@pytest.fixture()
def mlpub_pg(monkeypatch):
    """Throwaway Postgres schema holding the REAL core migration's tables, with
    `get_background_db()` (what the store's primitives use) pointed at it.

    Yields the engine; every connection it hands out has the schema first on
    its `search_path`, so concurrent sessions opened by the code under test
    see the same tables.
    """
    import importlib.util
    import uuid

    from alembic.operations import Operations
    from alembic.runtime.migration import MigrationContext
    from sqlalchemy import create_engine, text
    from sqlalchemy.orm import sessionmaker

    from tests.conftest import POSTGRES_TEST_URL, _postgres_reachable

    if not _postgres_reachable():
        pytest.skip(f"PostgreSQL not reachable at {POSTGRES_TEST_URL}")

    migration_path = Path(__file__).resolve().parents[3] / "alembic" / "versions" / "20261006_ml_publications_core.py"
    module_spec = importlib.util.spec_from_file_location("ml_publications_core_for_tests", migration_path)
    migration = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(migration)

    schema = f"mlpub_t_{uuid.uuid4().hex[:8]}"
    admin = create_engine(POSTGRES_TEST_URL, isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(text(f"CREATE SCHEMA {schema}"))
    eng = create_engine(
        POSTGRES_TEST_URL,
        connect_args={"options": f"-csearch_path={schema}"},
        pool_size=10,
    )
    with eng.connect() as conn:
        ctx = MigrationContext.configure(conn)
        with ctx.begin_transaction(), Operations.context(ctx):
            migration.upgrade()
    monkeypatch.setattr("app.core.database.SessionLocal", sessionmaker(bind=eng, autocommit=False, autoflush=False))
    try:
        yield eng
    finally:
        eng.dispose()
        with admin.connect() as conn:
            conn.execute(text(f"DROP SCHEMA {schema} CASCADE"))
        admin.dispose()
