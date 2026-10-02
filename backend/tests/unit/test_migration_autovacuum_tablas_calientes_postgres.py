"""The hot tables get per-table autovacuum thresholds (2% instead of the 20%
default), so dead rows are cleaned before they bloat the tables and force
index-only scans back to the heap. Measured in production 2026-10-02: the
ERP-synced tables sat at 12-19% dead rows and had never been autovacuumed."""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path

import pytest
from sqlalchemy import create_engine, inspect as sa_inspect, text

_BACKEND_ROOT = Path(__file__).resolve().parents[2]
_MIGRATION = _BACKEND_ROOT / "alembic" / "versions" / "20261002_autovacuum_tablas_calientes.py"

# A table the migration targets that this test creates when no other fixture
# left it, plus one that never exists, to prove a missing table is skipped.
_PROBE_TABLE = "ml_payment_charges"


def _load_migration():
    spec = importlib.util.spec_from_file_location("autovacuum_tablas_calientes", _MIGRATION)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture()
def autocommit_conn():
    from tests.conftest import POSTGRES_TEST_URL, _postgres_reachable

    if not _postgres_reachable():
        pytest.skip(f"PostgreSQL not reachable at {POSTGRES_TEST_URL}")
    engine = create_engine(os.environ.get("POSTGRES_TEST_URL", POSTGRES_TEST_URL), isolation_level="AUTOCOMMIT")
    with engine.connect() as conn:
        created = not sa_inspect(conn).has_table(_PROBE_TABLE)
        if created:
            conn.execute(text(f"CREATE TABLE {_PROBE_TABLE} (id INTEGER PRIMARY KEY)"))
        try:
            yield conn
        finally:
            if created:
                conn.execute(text(f"DROP TABLE {_PROBE_TABLE}"))
            else:
                conn.execute(
                    text(
                        f"ALTER TABLE {_PROBE_TABLE} RESET (autovacuum_vacuum_scale_factor, autovacuum_analyze_scale_factor)"
                    )
                )
    engine.dispose()


def _run(conn, step: str, after=None):
    from alembic.operations import Operations
    from alembic.runtime.migration import MigrationContext

    migration = _load_migration()
    engine = create_engine(str(conn.engine.url.render_as_string(hide_password=False)))
    try:
        with engine.connect() as migration_conn:
            ctx = MigrationContext.configure(migration_conn)
            with ctx.begin_transaction(), Operations.context(ctx):
                getattr(migration, step)()
                if after is not None:
                    return after(migration_conn)
    finally:
        engine.dispose()


def _options(conn, table: str) -> dict:
    raw = conn.execute(
        text("SELECT reloptions FROM pg_class WHERE oid = to_regclass(:t)"),
        {"t": table},
    ).scalar()
    return dict(item.split("=", 1) for item in (raw or []))


@pytest.mark.postgres
class TestAutovacuumHotTablesMigration:
    def test_sets_the_two_percent_thresholds_on_an_existing_table(self, autocommit_conn) -> None:
        _run(autocommit_conn, "upgrade")

        options = _options(autocommit_conn, _PROBE_TABLE)
        assert options["autovacuum_vacuum_scale_factor"] == "0.02"
        assert options["autovacuum_analyze_scale_factor"] == "0.02"

    def test_a_missing_table_is_skipped_not_an_error(self, autocommit_conn) -> None:
        migration = _load_migration()
        assert any(
            autocommit_conn.execute(text("SELECT to_regclass(:t)"), {"t": t}).scalar() is None for t in migration.TABLES
        ), "the test DB should lack at least one ERP table to exercise the skip"

        _run(autocommit_conn, "upgrade")  # does not raise

    def test_downgrade_resets_to_the_server_defaults(self, autocommit_conn) -> None:
        _run(autocommit_conn, "upgrade")
        _run(autocommit_conn, "downgrade")

        options = _options(autocommit_conn, _PROBE_TABLE)
        assert "autovacuum_vacuum_scale_factor" not in options
        assert "autovacuum_analyze_scale_factor" not in options

    def test_the_lock_timeout_does_not_leak_to_later_migrations(self, autocommit_conn) -> None:
        default = autocommit_conn.execute(text("SHOW lock_timeout")).scalar()

        inside = _run(autocommit_conn, "upgrade", after=lambda c: c.execute(text("SHOW lock_timeout")).scalar())

        assert inside == default

    def test_a_view_with_a_listed_name_is_skipped(self, autocommit_conn) -> None:
        migration = _load_migration()
        name = next(
            t
            for t in migration.TABLES
            if autocommit_conn.execute(text("SELECT to_regclass(:t)"), {"t": t}).scalar() is None
        )
        autocommit_conn.execute(text(f"CREATE VIEW {name} AS SELECT 1 AS x"))
        try:
            _run(autocommit_conn, "upgrade")  # an ALTER TABLE on a view would raise
        finally:
            autocommit_conn.execute(text(f"DROP VIEW {name}"))

    def test_targets_the_tables_measured_in_production(self) -> None:
        tables = set(_load_migration().TABLES)
        for hot in (
            "tb_commercial_transactions",
            "tb_item_transaction_serials",
            "tb_item_serials",
            "tb_mercadolibre_orders_shipping",
            "tb_sale_order_detail_history",
            "tb_sale_order_header_history",
            "ml_payment_charges",
            "ml_ventas_metricas",
            "ml_orders_ops",
            "ml_order_metrics",
        ):
            assert hot in tables
