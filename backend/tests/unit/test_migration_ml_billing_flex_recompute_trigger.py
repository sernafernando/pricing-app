"""Migration `20261020_ml_billing_flex_recompute_trigger` (ml-billing-balance PR 9-i).

Graph assertions run everywhere; the DDL assertion needs Postgres.
"""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory

from app.services.order_metrics import triggers_billing_flex

_BACKEND_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_REVISION = "20261020_ml_billing_flex_recompute_trigger"


def _script_directory() -> ScriptDirectory:
    config = Config(os.path.join(_BACKEND_ROOT, "alembic.ini"))
    config.set_main_option("script_location", os.path.join(_BACKEND_ROOT, "alembic"))
    return ScriptDirectory.from_config(config)


def _load_migration():
    path = Path(_BACKEND_ROOT) / "alembic" / "versions" / f"{_REVISION}.py"
    spec = importlib.util.spec_from_file_location("ml_billing_flex_recompute_trigger_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestMigrationGraph:
    def test_single_head_that_contains_this_revision(self) -> None:
        script = _script_directory()
        heads = script.get_heads()
        assert len(heads) == 1
        chain = {r.revision for r in script.walk_revisions(base="base", head=heads[0])}
        assert _REVISION in chain, f"{_REVISION!r} is not an ancestor of the single head {heads[0]!r}"

    def test_has_exactly_one_parent(self) -> None:
        assert isinstance(_script_directory().get_revision(_REVISION).down_revision, str)


class TestFrozenCopy:
    def test_the_frozen_ddl_matches_the_live_module(self) -> None:
        """The migration inlines its own copy; this fails if the two drift apart
        in what they create (a deliberate change then needs a NEW migration)."""
        migration = _load_migration()
        assert migration._UPGRADE_STATEMENTS == triggers_billing_flex._CREATE_STATEMENTS
        assert migration._DROP_STATEMENTS == triggers_billing_flex._DROP_STATEMENTS


@pytest.mark.postgres
class TestMigrationDdl:
    def test_upgrade_then_downgrade_round_trip(self, pg_order_metrics_triggers_engine) -> None:
        migration = _load_migration()
        with pg_order_metrics_triggers_engine.begin() as conn:
            conn.exec_driver_sql(
                "CREATE TEMP TABLE ml_billing_charges (detail_id text, amount numeric, detail_sub_type text)"
            )
            conn.exec_driver_sql("CREATE TEMP TABLE ml_billing_charge_orders (detail_id text, order_id bigint)")
            for statement in migration._UPGRADE_STATEMENTS:
                conn.exec_driver_sql(statement)
            for statement in migration._UPGRADE_STATEMENTS:  # re-applying never collides
                conn.exec_driver_sql(statement)
            names = {
                r[0]
                for r in conn.exec_driver_sql(
                    "SELECT tgname FROM pg_trigger WHERE tgname IN ('trg_order_metrics_billing_flex_link', 'trg_order_metrics_billing_flex_charge')"
                )
            }
            assert names == {"trg_order_metrics_billing_flex_link", "trg_order_metrics_billing_flex_charge"}
            for statement in migration._DROP_STATEMENTS:
                conn.exec_driver_sql(statement)
            assert not conn.exec_driver_sql(
                "SELECT 1 FROM pg_proc WHERE proname = 'order_metrics_enqueue_billing_flex'"
            ).all()
