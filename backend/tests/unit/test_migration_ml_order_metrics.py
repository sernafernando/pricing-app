"""ventas-ml-rediseno PR1.T3 — migration `20260922_ml_order_metrics`.

Graph layer (SQLite CI, always runs): confirms the migration is a
single-head continuation of the chain. Table-shape round-trip
(`@pytest.mark.postgres`, real Postgres): `ml_order_metrics_dirty.claim_token`
is a real Postgres UUID and `worker_job_state.detail` is JSONB, so this half
does not compile under SQLite (same reason PR1's models use
`postgresql.UUID`/`JSONB` directly, without the dialect-agnostic patch the
ORM-level SQLite test suite applies) -- upgrade creates every PR1.T2 column
plus the four indexes, downgrade removes all three tables and the
`ml_orders_ops` index cleanly.
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
_REVISION = "20260922_ml_order_metrics"


def _script_directory() -> ScriptDirectory:
    config = Config(os.path.join(_BACKEND_ROOT, "alembic.ini"))
    config.set_main_option("script_location", os.path.join(_BACKEND_ROOT, "alembic"))
    return ScriptDirectory.from_config(config)


def _load_migration():
    path = Path(_BACKEND_ROOT) / "alembic" / "versions" / f"{_REVISION}.py"
    spec = importlib.util.spec_from_file_location("ml_order_metrics_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestMigrationGraph:
    def test_revision_is_registered_and_linked(self) -> None:
        # The PARENT is not pinned by name: a rebase onto a main that added
        # migrations legitimately moves it, and pinning it turns every such
        # rebase into a false failure. What must hold is that the parent
        # exists in the graph and that this revision hangs off a single
        # linear parent (never a fork).
        script = _script_directory()
        revision = script.get_revision(_REVISION)
        assert revision is not None
        assert isinstance(revision.down_revision, str), "exactly one parent, never a branch point"
        assert script.get_revision(revision.down_revision) is not None

    def test_is_single_head(self) -> None:
        # Asserting the head IS this exact revision breaks the moment a
        # later migration continues the chain -- what must hold FOREVER is
        # that the graph never forks, and that this revision stays reachable
        # from whatever the head becomes.
        script = _script_directory()
        heads = script.get_heads()
        assert len(heads) == 1
        head = heads[0]
        chain_revisions = {r.revision for r in script.walk_revisions(base="base", head=head)}
        assert _REVISION in chain_revisions, f"{_REVISION!r} is not an ancestor of the single head {head!r}"


@pytest.mark.postgres
class TestMigrationPostgresRoundTrip:
    def test_upgrade_creates_every_column_and_index_then_downgrade_removes_all(self, pg_engine) -> None:
        from alembic.operations import Operations
        from alembic.runtime.migration import MigrationContext

        migration = _load_migration()

        with pg_engine.begin() as conn:
            # Never drop a table this test did not create -- only create
            # (and later drop) it when it is not already there.
            ml_orders_ops_preexisted = sa.inspect(conn).has_table("ml_orders_ops")
            if not ml_orders_ops_preexisted:
                conn.execute(
                    sa.text(
                        "CREATE TABLE ml_orders_ops ("
                        "order_id BIGINT PRIMARY KEY, seller_id BIGINT, date_created TIMESTAMPTZ"
                        ")"
                    )
                )

        with pg_engine.connect() as conn:
            ctx = MigrationContext.configure(conn)
            op_obj = Operations(ctx)
            op_obj._install_proxy()
            try:
                migration.upgrade()
                conn.commit()

                inspector = sa.inspect(conn)

                metrics_columns = {c["name"] for c in inspector.get_columns("ml_order_metrics")}
                assert metrics_columns == {
                    "order_id",
                    "neto",
                    "neto_sin_iva",
                    "iva_reconcilia",
                    "costo_mercaderia",
                    "total_gauss",
                    "markup_pct",
                    "gauss_status",
                    "provisional_falta",
                    "unresolved_reason",
                    "formula_version",
                    "computed_at",
                }

                dirty_columns = {c["name"] for c in inspector.get_columns("ml_order_metrics_dirty")}
                assert dirty_columns == {
                    "order_id",
                    "version",
                    "reason",
                    "enqueued_at",
                    "claimed_at",
                    "claimed_by",
                    "claim_token",
                    "attempts",
                    "last_error",
                    "suspect",
                }
                claim_token_type = next(
                    c["type"] for c in inspector.get_columns("ml_order_metrics_dirty") if c["name"] == "claim_token"
                )
                assert "UUID" in str(claim_token_type).upper()

                job_state_columns = {c["name"] for c in inspector.get_columns("worker_job_state")}
                assert job_state_columns == {
                    "name",
                    "last_run_at",
                    "last_success_at",
                    "state",
                    "detail",
                    "heartbeat_at",
                }

                index_names_metrics = {i["name"] for i in inspector.get_indexes("ml_order_metrics")}
                assert "ix_ml_order_metrics_status" in index_names_metrics
                assert "ix_ml_order_metrics_total_gauss" in index_names_metrics

                index_names_dirty = {i["name"] for i in inspector.get_indexes("ml_order_metrics_dirty")}
                assert "ix_ml_order_metrics_dirty_enqueued_at" in index_names_dirty

                index_names_orders = {i["name"] for i in inspector.get_indexes("ml_orders_ops")}
                assert "ix_ml_orders_ops_seller_date" in index_names_orders

                migration.downgrade()
                conn.commit()

                remaining_tables = set(sa.inspect(conn).get_table_names())
                assert "ml_order_metrics" not in remaining_tables
                assert "ml_order_metrics_dirty" not in remaining_tables
                assert "worker_job_state" not in remaining_tables
                index_names_orders_after = {i["name"] for i in sa.inspect(conn).get_indexes("ml_orders_ops")}
                assert "ix_ml_orders_ops_seller_date" not in index_names_orders_after
            finally:
                op_obj._remove_proxy()
                # Best-effort cleanup: drop only what THIS test created (in
                # dependency order, CASCADE for anything an earlier
                # assertion failure may have left half-upgraded), and never
                # let a cleanup failure mask the original assertion error
                # that sent us here.
                try:
                    with pg_engine.begin() as conn2:
                        conn2.execute(sa.text("DROP TABLE IF EXISTS ml_order_metrics_dirty CASCADE"))
                        conn2.execute(sa.text("DROP TABLE IF EXISTS ml_order_metrics CASCADE"))
                        conn2.execute(sa.text("DROP TABLE IF EXISTS worker_job_state CASCADE"))
                        if not ml_orders_ops_preexisted:
                            conn2.execute(sa.text("DROP TABLE IF EXISTS ml_orders_ops CASCADE"))
                        else:
                            # A failed run (assertion error between upgrade
                            # and downgrade) can leave the index the
                            # migration adds to the PRE-EXISTING table
                            # behind -- drop it too, or the next run's
                            # `create index` half of `upgrade()` collides
                            # with a leftover from THIS run instead of
                            # starting clean.
                            conn2.execute(sa.text("DROP INDEX IF EXISTS ix_ml_orders_ops_seller_date"))
                except Exception:  # noqa: BLE001 -- cleanup must never mask the real failure
                    pass
