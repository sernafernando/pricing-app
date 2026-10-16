"""Migration `20261027_tp_metrics_columns`, executed against Postgres.

Runs the real upgrade()/downgrade() inside a throwaway schema of the Postgres
test DB holding minimal copies of the three tables it touches, the enqueue
function the trigger calls, and the item-costos UPDATE trigger as
`20260923_ml_order_metrics_triggers_orders` created it.
"""

from __future__ import annotations

import importlib.util
import uuid
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text

_BACKEND_ROOT = Path(__file__).resolve().parents[2]
_MIGRATION = _BACKEND_ROOT / "alembic" / "versions" / "20261027_tp_metrics_columns.py"

_TP_COLUMNS = {"costo_tp", "total_tp", "markup_tp", "tp_incompleto", "tg_tp", "mtg_tp", "mcosto_tp"}


def _load_migration():
    spec = importlib.util.spec_from_file_location("tp_metrics_columns_migration", _MIGRATION)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


SCHEMA_DDL = [
    "CREATE TABLE ml_order_metrics (order_id BIGINT PRIMARY KEY, total_gauss NUMERIC(14, 2))",
    "CREATE TABLE ml_sale_lines (item_row_id INTEGER PRIMARY KEY, tg NUMERIC NOT NULL)",
    """
    CREATE TABLE ml_order_item_costos (
        id SERIAL PRIMARY KEY,
        order_id BIGINT NOT NULL,
        costo_unitario_ars NUMERIC(14, 4) NOT NULL,
        iva_pct NUMERIC(5, 2) NOT NULL,
        precio_unitario NUMERIC(14, 2) NOT NULL,
        costo_tp_unitario_ars NUMERIC(14, 4)
    )
    """,
    """
    CREATE FUNCTION order_metrics_enqueue_order_item_costos() RETURNS TRIGGER AS $trg$
    BEGIN
        RETURN NEW;
    END;
    $trg$ LANGUAGE plpgsql
    """,
]


@pytest.fixture()
def engine():
    from tests.conftest import POSTGRES_TEST_URL, _postgres_reachable

    if not _postgres_reachable():
        pytest.skip(f"PostgreSQL not reachable at {POSTGRES_TEST_URL}")
    schema = f"tp_metrics_{uuid.uuid4().hex[:8]}"
    admin_engine = create_engine(POSTGRES_TEST_URL, isolation_level="AUTOCOMMIT")
    with admin_engine.connect() as conn:
        conn.execute(text(f"CREATE SCHEMA {schema}"))
    eng = create_engine(POSTGRES_TEST_URL, connect_args={"options": f"-csearch_path={schema}"})
    with eng.begin() as conn:
        for ddl in SCHEMA_DDL:
            conn.execute(text(ddl))
        conn.execute(text(_load_migration()._PREVIOUS_UPDATE_TRIGGER_SQL))
    try:
        yield eng
    finally:
        eng.dispose()
        with admin_engine.connect() as conn:
            conn.execute(text(f"DROP SCHEMA {schema} CASCADE"))
        admin_engine.dispose()


def _run(engine, step: str) -> None:
    from alembic.operations import Operations
    from alembic.runtime.migration import MigrationContext

    migration = _load_migration()
    with engine.connect() as conn:
        ctx = MigrationContext.configure(conn)
        with ctx.begin_transaction(), Operations.context(ctx):
            getattr(migration, step)()


def _tp_columns(engine) -> set:
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT column_name, is_nullable FROM information_schema.columns "
                "WHERE table_schema = current_schema() AND table_name IN ('ml_order_metrics', 'ml_sale_lines')"
            )
        ).all()
    assert all(nullable == "YES" for name, nullable in rows if name in _TP_COLUMNS)
    return {name for name, _nullable in rows} & _TP_COLUMNS


def _function_source(engine, name: str):
    """The body of function `name` in this schema, or None."""
    with engine.connect() as conn:
        return conn.execute(
            text("SELECT prosrc FROM pg_proc WHERE proname = :name AND pronamespace = current_schema()::regnamespace"),
            {"name": name},
        ).scalar()


def _update_trigger(engine) -> str:
    """The definition of the item-costos UPDATE trigger in this schema."""
    with engine.connect() as conn:
        return conn.execute(
            text(
                "SELECT pg_get_triggerdef(t.oid) FROM pg_trigger t "
                "JOIN pg_class c ON c.oid = t.tgrelid "
                "WHERE c.relnamespace = current_schema()::regnamespace "
                "AND t.tgname = 'trg_order_metrics_item_costos_update'"
            )
        ).scalar_one()


@pytest.mark.postgres
class TestTpMetricsColumnsMigration:
    def test_upgrade_adds_the_columns_and_watches_the_tp_cost(self, engine) -> None:
        assert _tp_columns(engine) == set()
        assert "costo_tp_unitario_ars" not in _update_trigger(engine)

        _run(engine, "upgrade")

        assert _tp_columns(engine) == _TP_COLUMNS
        assert "costo_tp_unitario_ars" in _update_trigger(engine)
        assert _function_source(engine, "order_metrics_enqueue_tp_cost") is not None
        assert "order_metrics_enqueue_tp_cost" in _function_source(engine, "order_metrics_enqueue_order_item_costos")

    def test_downgrade_drops_the_columns_and_stops_watching_the_tp_cost(self, engine) -> None:
        _run(engine, "upgrade")

        _run(engine, "downgrade")

        assert _tp_columns(engine) == set()
        trigger = _update_trigger(engine)
        assert "costo_tp_unitario_ars" not in trigger
        assert "costo_unitario_ars" in trigger
        assert _function_source(engine, "order_metrics_enqueue_tp_cost") is None
        restored = _function_source(engine, "order_metrics_enqueue_order_item_costos")
        assert restored.strip() == _load_migration()._PREVIOUS_ITEM_COSTOS_FUNCTION_BODY.strip()
