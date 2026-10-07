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
    """Throwaway Postgres schema holding the REAL core and sub-resource migrations' tables, with
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

    from app.models import ml_publications as models
    from tests.conftest import (
        POSTGRES_TEST_URL,
        _patch_pg_types_for_sqlite,
        _postgres_reachable,
        _restore_pristine_pg_types,
    )

    if not _postgres_reachable():
        pytest.skip(f"PostgreSQL not reachable at {POSTGRES_TEST_URL}")

    # The SQLite `engine` fixture rewrites the shared Column types (JSONB/ARRAY -> JSON, BigInteger PK ->
    # Integer) in place; the ORM writes of the store need the real Postgres types back, whatever ran before.
    store_tables = [
        model.__table__ for model in vars(models).values() if hasattr(model, "__table__") and hasattr(model, "metadata")
    ]
    _restore_pristine_pg_types(store_tables)

    versions = Path(__file__).resolve().parents[3] / "alembic" / "versions"
    migrations = []
    for revision in ("20261006_ml_publications_core", "20261006_ml_publications_subresources"):
        module_spec = importlib.util.spec_from_file_location(f"{revision}_for_tests", versions / f"{revision}.py")
        migration = importlib.util.module_from_spec(module_spec)
        module_spec.loader.exec_module(migration)
        migrations.append(migration)

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
            for migration in migrations:
                migration.upgrade()
    monkeypatch.setattr("app.core.database.SessionLocal", sessionmaker(bind=eng, autocommit=False, autoflush=False))
    try:
        yield eng
    finally:
        _patch_pg_types_for_sqlite()  # leave the shared columns as the SQLite fixture expects them
        eng.dispose()
        with admin.connect() as conn:
            conn.execute(text(f"DROP SCHEMA {schema} CASCADE"))
        admin.dispose()


ITEM_404_SINGLE = "item_single_404_MLA1_20261006.json"


def item_404_single() -> dict:
    """Real single-item `GET /items/MLA1` 404 body `{message, error, status, cause}`."""
    return copy.deepcopy(load_fixture(ITEM_404_SINGLE)["body"])


def item_404_bulk_element() -> dict:
    """Real `/items/bulk` not-found element for MLA1 (`{id, status_code: 404, error}`)."""
    return bulk_call("bulk_full")[2]


def item_with_variations() -> dict:
    """Captured MLA1207279308 (closed, 4 variations without `attributes`)."""
    return copy.deepcopy(load_fixture(ITEM_WITH_VARIATIONS))


# --- Sub-resource captures (description, prices, sale price, promotions, user product, stock, family) ---

SUBRESOURCE_FIXTURES = {
    "description": "description_20261006.json",
    "prices": "prices_20261006.json",
    "sale_price": "sale_price_20261006.json",
    "promotions": "seller_promotions_20261006.json",
    "user_product": "user_product_20261006.json",
    "stock": "user_product_stock_20261006.json",
    "family": "family_20261006.json",
}


def subresource_call(resource: str, name: str) -> dict:
    """One captured call `{name, path, status, headers, body}` of a sub-resource fixture (deep copy)."""
    for call in load_fixture(SUBRESOURCE_FIXTURES[resource])["calls"]:
        if call["name"] == name:
            return copy.deepcopy(call)
    raise KeyError(f"{resource}:{name}")


def subresource_body(resource: str, name: str) -> Any:
    return subresource_call(resource, name)["body"]


# --- Bridge `webhook_latest` (captured 2026-10-06) -----------------------------------------

WEBHOOK_SAMPLES = "webhook_latest_samples.json"
BRIDGE_DDL = "bridge_webhook_latest.sql"


def webhook_row(topic: str, index: int = 0, **overrides: Any) -> dict:
    """One real captured `webhook_latest` row of `topic` (deep copy). `overrides` replace top-level
    columns (real payload, `received_at`/`resource` changed to place it on a test timeline); a
    changed `resource` is mirrored into the payload."""
    rows = [r for r in load_fixture(WEBHOOK_SAMPLES)["samples"] if r["topic"] == topic]
    row = copy.deepcopy(rows[index])
    row.update(overrides)
    if "resource" in overrides:
        row["payload"]["resource"] = overrides["resource"]
    return row


@pytest.fixture()
def bridge_pg(mlpub_pg):
    """A second throwaway schema standing in for the bridge database, holding the real
    `webhook_latest` DDL (copied from the bridge migration). Yields its engine."""
    import uuid

    from sqlalchemy import create_engine, text

    from tests.conftest import POSTGRES_TEST_URL

    schema = f"mlbridge_t_{uuid.uuid4().hex[:8]}"
    admin = create_engine(POSTGRES_TEST_URL, isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(text(f"CREATE SCHEMA {schema}"))
    eng = create_engine(POSTGRES_TEST_URL, connect_args={"options": f"-csearch_path={schema}"}, pool_size=5)
    with eng.begin() as conn:
        conn.exec_driver_sql((FIXTURES_DIR / BRIDGE_DDL).read_text(encoding="utf-8"))
    try:
        yield eng
    finally:
        eng.dispose()
        with admin.connect() as conn:
            conn.execute(text(f"DROP SCHEMA {schema} CASCADE"))
        admin.dispose()


def put_webhook(engine, row: dict) -> None:
    """Upsert one row the way the bridge handler does (one row per (topic, resource), latest wins)."""
    import json

    from sqlalchemy import text

    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO webhook_latest (topic, resource, webhook_id, received_at, payload) "
                "VALUES (:topic, :resource, :webhook_id, CAST(:received_at AS timestamptz), CAST(:payload AS jsonb)) "
                "ON CONFLICT (topic, resource) DO UPDATE SET webhook_id = EXCLUDED.webhook_id, "
                "received_at = EXCLUDED.received_at, payload = EXCLUDED.payload"
            ),
            {
                "topic": row["topic"],
                "resource": row["resource"],
                "webhook_id": row.get("webhook_id"),
                "received_at": str(row["received_at"]),
                "payload": json.dumps(row["payload"]),
            },
        )
