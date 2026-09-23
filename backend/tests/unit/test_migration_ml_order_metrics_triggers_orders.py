"""ventas-ml-rediseno PR4.T8 -- migration
`20260923_ml_order_metrics_triggers_orders`.

Graph layer (SQLite CI, always runs): single-head continuation. Round trip
(`@pytest.mark.postgres`): upgrade creates every enqueue function and every
per-order trigger; downgrade removes them all cleanly, leaving the six
input tables and `ml_order_metrics_dirty` themselves untouched.
"""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.config import Config
from alembic.script import ScriptDirectory

_BACKEND_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_REVISION = "20260923_ml_order_metrics_triggers_orders"


def _trigger_names(conn, table_name: str) -> set:
    rows = conn.execute(
        sa.text(
            "SELECT tgname FROM pg_trigger t "
            "JOIN pg_class c ON c.oid = t.tgrelid "
            "WHERE c.relname = :table_name AND NOT t.tgisinternal"
        ),
        {"table_name": table_name},
    ).fetchall()
    return {row[0] for row in rows}


def _script_directory() -> ScriptDirectory:
    config = Config(os.path.join(_BACKEND_ROOT, "alembic.ini"))
    config.set_main_option("script_location", os.path.join(_BACKEND_ROOT, "alembic"))
    return ScriptDirectory.from_config(config)


def _load_migration():
    path = Path(_BACKEND_ROOT) / "alembic" / "versions" / f"{_REVISION}.py"
    spec = importlib.util.spec_from_file_location("ml_order_metrics_triggers_orders_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestMigrationGraph:
    def test_revision_is_registered_and_linked(self) -> None:
        script = _script_directory()
        revision = script.get_revision(_REVISION)
        assert revision is not None
        assert isinstance(revision.down_revision, str), "exactly one parent, never a branch point"
        assert script.get_revision(revision.down_revision) is not None

    def test_is_single_head(self) -> None:
        script = _script_directory()
        heads = script.get_heads()
        assert len(heads) == 1
        head = heads[0]
        chain_revisions = {r.revision for r in script.walk_revisions(base="base", head=head)}
        assert _REVISION in chain_revisions, f"{_REVISION!r} is not an ancestor of the single head {head!r}"


_FUNCTIONS = [
    "order_metrics_enqueue",
    "order_metrics_enqueue_system",
    "order_metrics_enqueue_orders_ops",
    "order_metrics_enqueue_order_items_ops",
    "order_metrics_enqueue_order_item_costos",
    "order_metrics_enqueue_payments_ops",
    "order_metrics_enqueue_payment_charges",
    "order_metrics_enqueue_shipments_ops",
]

_TRIGGERS_BY_TABLE = {
    "ml_orders_ops": [
        "trg_order_metrics_orders_ops_insert",
        "trg_order_metrics_orders_ops_update",
        "trg_order_metrics_orders_ops_delete",
    ],
    "ml_order_items_ops": [
        "trg_order_metrics_items_ops_insert",
        "trg_order_metrics_items_ops_update",
        "trg_order_metrics_items_ops_delete",
    ],
    "ml_order_item_costos": [
        "trg_order_metrics_item_costos_insert",
        "trg_order_metrics_item_costos_update",
        "trg_order_metrics_item_costos_delete",
    ],
    "ml_payments_ops": [
        "trg_order_metrics_payments_ops_insert",
        "trg_order_metrics_payments_ops_update",
        "trg_order_metrics_payments_ops_delete",
    ],
    "ml_payment_charges": [
        "trg_order_metrics_payment_charges_insert",
        "trg_order_metrics_payment_charges_update",
        "trg_order_metrics_payment_charges_delete",
    ],
    "ml_shipments_ops": [
        "trg_order_metrics_shipments_ops_insert",
        "trg_order_metrics_shipments_ops_update",
        "trg_order_metrics_shipments_ops_delete",
    ],
}


@pytest.mark.postgres
class TestMigrationPostgresRoundTrip:
    def test_upgrade_creates_every_function_and_trigger_then_downgrade_removes_all(
        self, pg_order_metrics_triggers_engine
    ) -> None:
        migration = _load_migration()

        # The fixture already applied this DDL via its own explicit
        # `create_triggers(conn)` call (triggers.py) when it built the
        # tables -- drop it first so this test observes the MIGRATION's own
        # create/drop, not a pre-existing copy silently masking a real
        # migration bug.
        with pg_order_metrics_triggers_engine.begin() as conn:
            from app.services.order_metrics.triggers import drop_triggers

            drop_triggers(conn)

        with pg_order_metrics_triggers_engine.connect() as conn:
            from alembic.operations import Operations
            from alembic.runtime.migration import MigrationContext

            ctx = MigrationContext.configure(conn)
            op_obj = Operations(ctx)
            op_obj._install_proxy()
            try:
                migration.upgrade()
                conn.commit()

                inspector = sa.inspect(conn)
                for function_name in _FUNCTIONS:
                    row = conn.execute(
                        sa.text("SELECT 1 FROM pg_proc WHERE proname = :name"), {"name": function_name}
                    ).fetchone()
                    assert row is not None, f"function {function_name!r} missing after upgrade"

                for table_name, trigger_names in _TRIGGERS_BY_TABLE.items():
                    existing = _trigger_names(conn, table_name)
                    for trigger_name in trigger_names:
                        assert trigger_name in existing, f"{trigger_name!r} missing on {table_name!r}"

                migration.downgrade()
                conn.commit()

                inspector = sa.inspect(conn)
                for function_name in _FUNCTIONS:
                    row = conn.execute(
                        sa.text("SELECT 1 FROM pg_proc WHERE proname = :name"), {"name": function_name}
                    ).fetchone()
                    assert row is None, f"function {function_name!r} survived downgrade"

                for table_name, trigger_names in _TRIGGERS_BY_TABLE.items():
                    existing = _trigger_names(conn, table_name)
                    for trigger_name in trigger_names:
                        assert trigger_name not in existing, f"{trigger_name!r} survived downgrade on {table_name!r}"

                # The tables themselves are untouched by this migration.
                assert inspector.has_table("ml_orders_ops")
                assert inspector.has_table("ml_order_metrics_dirty")
            finally:
                op_obj._remove_proxy()
                # Restore the fixture's own trigger DDL for any later test in
                # this module-scoped engine's lifetime.
                try:
                    with pg_order_metrics_triggers_engine.begin() as conn2:
                        from app.services.order_metrics.triggers import create_triggers

                        create_triggers(conn2)
                except Exception:  # noqa: BLE001 -- cleanup must never mask the real failure
                    pass
