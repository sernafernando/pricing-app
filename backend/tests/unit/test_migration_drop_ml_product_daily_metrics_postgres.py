"""Phase two of removing the daily rollup: the migration drops
`ml_product_daily_metrics` (with its indexes), is a no-op when the table is
already gone, and downgrade recreates it empty with its original shape."""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path

import pytest
from sqlalchemy import create_engine, inspect as sa_inspect, text

_BACKEND_ROOT = Path(__file__).resolve().parents[2]
_MIGRATION = _BACKEND_ROOT / "alembic" / "versions" / "20261005_drop_ml_product_daily_metrics.py"
_TABLE = "ml_product_daily_metrics"


def _load_migration():
    spec = importlib.util.spec_from_file_location("drop_ml_product_daily_metrics", _MIGRATION)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture()
def conn():
    from tests.conftest import POSTGRES_TEST_URL, _postgres_reachable

    if not _postgres_reachable():
        pytest.skip(f"PostgreSQL not reachable at {POSTGRES_TEST_URL}")
    engine = create_engine(os.environ.get("POSTGRES_TEST_URL", POSTGRES_TEST_URL), isolation_level="AUTOCOMMIT")
    with engine.connect() as connection:
        existed = sa_inspect(connection).has_table(_TABLE)
        try:
            yield connection
        finally:
            # Leave the shared test DB as found.
            present = sa_inspect(connection).has_table(_TABLE)
            if present and not existed:
                connection.execute(text(f"DROP TABLE {_TABLE}"))
            elif existed and not present:
                _run(connection, "downgrade")
    engine.dispose()


def _run(connection, step: str, after=None):
    from alembic.operations import Operations
    from alembic.runtime.migration import MigrationContext

    migration = _load_migration()
    engine = create_engine(str(connection.engine.url.render_as_string(hide_password=False)))
    try:
        with engine.connect() as migration_conn:
            ctx = MigrationContext.configure(migration_conn)
            with ctx.begin_transaction(), Operations.context(ctx):
                getattr(migration, step)()
                if after is not None:
                    return after(migration_conn)
    finally:
        engine.dispose()


def _has_table(connection) -> bool:
    return connection.execute(text("SELECT to_regclass(:t)"), {"t": _TABLE}).scalar() is not None


@pytest.mark.postgres
class TestDropDailyRollupMigration:
    def test_upgrade_drops_the_table_and_its_indexes(self, conn) -> None:
        if not _has_table(conn):
            _run(conn, "downgrade")
        assert _has_table(conn)

        _run(conn, "upgrade")

        assert not _has_table(conn)
        assert conn.execute(text("SELECT to_regclass('ix_ml_product_daily_metrics_mla_day')")).scalar() is None

    def test_upgrade_is_a_no_op_when_the_table_is_already_gone(self, conn) -> None:
        if _has_table(conn):
            _run(conn, "upgrade")

        _run(conn, "upgrade")  # does not raise

        assert not _has_table(conn)

    def test_downgrade_recreates_it_empty_with_its_unique_key(self, conn) -> None:
        if _has_table(conn):
            _run(conn, "upgrade")

        _run(conn, "downgrade")

        assert _has_table(conn)
        uniques = sa_inspect(conn).get_unique_constraints(_TABLE)
        assert {"product_item_id", "mla", "day"} == set(uniques[0]["column_names"])

    def test_the_lock_timeout_does_not_leak_to_later_migrations(self, conn) -> None:
        default = conn.execute(text("SHOW lock_timeout")).scalar()

        inside = _run(conn, "upgrade", after=lambda c: c.execute(text("SHOW lock_timeout")).scalar())

        assert inside == default
