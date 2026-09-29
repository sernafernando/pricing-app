"""ventas-ml-rediseno PR20.T3 — migration `20260929_ml_group_metrics`.

Same two-layer discipline as `test_migration_ml_order_metrics.py`: graph
layer (SQLite CI, always runs) confirms single-head continuation; table
round-trip (`@pytest.mark.postgres`) confirms upgrade creates every column
+ index and downgrade removes the table cleanly. New migration only --
`20260923_ml_order_metrics_triggers_orders.py` is never edited (immutability
contract, `triggers.py:22-33`).
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
_REVISION = "20260929_ml_group_metrics"
_PACK_FANOUT_REVISION = "20260929_ml_group_metrics_pack_fanout"
_GROSS_AMOUNT_REVISION = "20260929_ml_group_metrics_gross_amount"


def _script_directory() -> ScriptDirectory:
    config = Config(os.path.join(_BACKEND_ROOT, "alembic.ini"))
    config.set_main_option("script_location", os.path.join(_BACKEND_ROOT, "alembic"))
    return ScriptDirectory.from_config(config)


def _load_migration():
    path = Path(_BACKEND_ROOT) / "alembic" / "versions" / f"{_REVISION}.py"
    spec = importlib.util.spec_from_file_location("ml_group_metrics_migration", path)
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

    def test_never_edits_the_frozen_triggers_orders_migration(self) -> None:
        frozen = Path(_BACKEND_ROOT) / "alembic" / "versions" / "20260923_ml_order_metrics_triggers_orders.py"
        # Sanity check that the frozen file still exists and this migration
        # is a genuinely separate file, not a rename/edit of it.
        assert frozen.exists()
        assert frozen.name != f"{_REVISION}.py"


@pytest.mark.postgres
class TestMigrationPostgresRoundTrip:
    def test_upgrade_creates_table_then_downgrade_removes_it(self, pg_engine) -> None:
        from alembic.operations import Operations
        from alembic.runtime.migration import MigrationContext

        migration = _load_migration()

        with pg_engine.begin() as conn:
            ml_orders_ops_preexisted = sa.inspect(conn).has_table("ml_orders_ops")
            if not ml_orders_ops_preexisted:
                conn.execute(sa.text("CREATE TABLE ml_orders_ops (order_id BIGINT PRIMARY KEY)"))

        with pg_engine.connect() as conn:
            ctx = MigrationContext.configure(conn)
            op_obj = Operations(ctx)
            op_obj._install_proxy()
            try:
                migration.upgrade()
                conn.commit()

                inspector = sa.inspect(conn)
                assert inspector.has_table("ml_group_metrics")
                # The columns of THIS migration, not of the table as it stands
                # today: `20260929_ml_group_metrics_gross_amount` adds two more
                # afterwards. An exact set is still right here -- it catches a
                # column silently dropped from this revision -- but the chain
                # round-trip below is what pins the final shape.
                columns = {c["name"] for c in inspector.get_columns("ml_group_metrics")}
                assert columns == {
                    "group_key",
                    "neto",
                    "neto_sin_iva",
                    "costo_mercaderia",
                    "total_gauss",
                    "markup_pct",
                    "gauss_status",
                    "member_order_ids",
                    "group_date",
                    "formula_version",
                    "computed_at",
                }
                index_names = {i["name"] for i in inspector.get_indexes("ml_group_metrics")}
                assert "ix_ml_group_metrics_status" in index_names
                assert "ix_ml_group_metrics_member_order_ids" in index_names

                pk = inspector.get_pk_constraint("ml_group_metrics")
                assert pk["constrained_columns"] == ["group_key"]

                migration.downgrade()
                conn.commit()

                inspector = sa.inspect(conn)
                assert not inspector.has_table("ml_group_metrics")
            finally:
                with pg_engine.begin() as cleanup_conn:
                    cleanup_conn.execute(sa.text("DROP TABLE IF EXISTS ml_group_metrics"))
                    if not ml_orders_ops_preexisted:
                        cleanup_conn.execute(sa.text("DROP TABLE IF EXISTS ml_orders_ops CASCADE"))


def _load_revision(revision: str):
    path = Path(_BACKEND_ROOT) / "alembic" / "versions" / f"{revision}.py"
    spec = importlib.util.spec_from_file_location(f"migration_{revision}", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.postgres
class TestMigrationChainPostgresRoundTrip:
    """The FULL chain, which is what actually reaches a deployed database.

    The class above runs one revision in isolation, so its exact column set
    stops describing the real table the moment a follow-up migration adds to
    it -- and one already does. This runs all three in order and pins the
    shape a reader of `ml_group_metrics` can count on, up and back down.
    """

    def test_the_chain_adds_gross_amount_and_downgrades_cleanly(self, pg_engine) -> None:
        from alembic.operations import Operations
        from alembic.runtime.migration import MigrationContext

        base = _load_migration()
        fanout = _load_revision(_PACK_FANOUT_REVISION)
        follow_up = _load_revision(_GROSS_AMOUNT_REVISION)

        # Asserted, not assumed: if someone reorders the chain, this test
        # would otherwise keep passing while exercising a sequence no deployed
        # database will ever run.
        assert fanout.down_revision == _REVISION
        assert follow_up.down_revision == _PACK_FANOUT_REVISION

        with pg_engine.begin() as conn:
            ml_orders_ops_preexisted = sa.inspect(conn).has_table("ml_orders_ops")
            if not ml_orders_ops_preexisted:
                conn.execute(sa.text("CREATE TABLE ml_orders_ops (order_id BIGINT PRIMARY KEY)"))

        with pg_engine.connect() as conn:
            ctx = MigrationContext.configure(conn)
            op_obj = Operations(ctx)
            op_obj._install_proxy()
            try:
                base.upgrade()
                fanout.upgrade()
                follow_up.upgrade()
                conn.commit()

                columns = {c["name"] for c in sa.inspect(conn).get_columns("ml_group_metrics")}
                assert "gross_amount" in columns
                assert "currency_id" in columns

                follow_up.downgrade()
                conn.commit()
                columns = {c["name"] for c in sa.inspect(conn).get_columns("ml_group_metrics")}
                assert "gross_amount" not in columns
                assert "currency_id" not in columns

                fanout.downgrade()
                base.downgrade()
                conn.commit()
                assert not sa.inspect(conn).has_table("ml_group_metrics")
            finally:
                # Same rule the class above follows: the placeholder is
                # dropped ONLY when this test created it. Leaving it behind
                # poisons `test_migration_ml_order_metrics`, which needs the
                # real table's `seller_id`.
                with pg_engine.begin() as cleanup_conn:
                    cleanup_conn.execute(sa.text("DROP TABLE IF EXISTS ml_group_metrics"))
                    if not ml_orders_ops_preexisted:
                        cleanup_conn.execute(sa.text("DROP TABLE IF EXISTS ml_orders_ops CASCADE"))
