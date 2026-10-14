"""Migration `20261023_ml_billing_flex_drop_recompute_trigger` (revert of PR #1534).

Graph assertions run everywhere; the DDL assertions need Postgres.
"""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path
from types import ModuleType

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy.engine import Connection

_BACKEND_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_REVISION = "20261023_ml_billing_flex_drop_recompute_trigger"
_CREATING_REVISION = "20261020_ml_billing_flex_recompute_trigger"
_TRIGGERS = {"trg_order_metrics_billing_flex_link", "trg_order_metrics_billing_flex_charge"}
_FUNCTION = "order_metrics_enqueue_billing_flex"


def _script_directory() -> ScriptDirectory:
    config = Config(os.path.join(_BACKEND_ROOT, "alembic.ini"))
    config.set_main_option("script_location", os.path.join(_BACKEND_ROOT, "alembic"))
    return ScriptDirectory.from_config(config)


def _load(revision: str) -> ModuleType:
    path = Path(_BACKEND_ROOT) / "alembic" / "versions" / f"{revision}.py"
    spec = importlib.util.spec_from_file_location(f"migration_{revision}", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _existing_triggers(conn: Connection) -> set[str]:
    rows = conn.exec_driver_sql(
        "SELECT tgname FROM pg_trigger WHERE tgname IN "
        "('trg_order_metrics_billing_flex_link', 'trg_order_metrics_billing_flex_charge')"
    )
    return {r[0] for r in rows}


def _function_exists(conn: Connection) -> bool:
    return bool(conn.exec_driver_sql(f"SELECT 1 FROM pg_proc WHERE proname = '{_FUNCTION}'").all())


class TestMigrationGraph:
    def test_single_head_runs_the_drop_after_the_create(self) -> None:
        script = _script_directory()
        heads = script.get_heads()
        assert len(heads) == 1
        chain = [r.revision for r in script.walk_revisions(base="base", head=heads[0])]
        assert _REVISION in chain and _CREATING_REVISION in chain
        # walk_revisions goes head -> base, so the drop must come first in the list.
        assert chain.index(_REVISION) < chain.index(_CREATING_REVISION)

    def test_has_exactly_one_parent(self) -> None:
        assert isinstance(_script_directory().get_revision(_REVISION).down_revision, str)


class TestFrozenCopy:
    def test_drops_exactly_what_the_creating_migration_created(self) -> None:
        assert _load(_REVISION)._DROP_STATEMENTS == _load(_CREATING_REVISION)._DROP_STATEMENTS

    def test_downgrade_recreates_the_creating_migration_ddl(self) -> None:
        assert _load(_REVISION)._RECREATE_STATEMENTS == _load(_CREATING_REVISION)._UPGRADE_STATEMENTS


@pytest.mark.postgres
class TestMigrationDdl:
    def test_after_upgrade_the_triggers_and_function_are_gone(self, pg_order_metrics_triggers_engine) -> None:
        creating = _load(_CREATING_REVISION)
        dropping = _load(_REVISION)
        with pg_order_metrics_triggers_engine.connect() as conn:
            tx = conn.begin()
            try:
                conn.exec_driver_sql(
                    "CREATE TEMP TABLE ml_billing_charges (detail_id text, amount numeric, detail_sub_type text)"
                )
                conn.exec_driver_sql("CREATE TEMP TABLE ml_billing_charge_orders (detail_id text, order_id bigint)")
                for statement in creating._UPGRADE_STATEMENTS:
                    conn.exec_driver_sql(statement)
                assert _existing_triggers(conn) == _TRIGGERS

                for statement in dropping._DROP_STATEMENTS:
                    conn.exec_driver_sql(statement)
                assert _existing_triggers(conn) == set()
                assert not _function_exists(conn)

                for statement in dropping._DROP_STATEMENTS:  # re-applying is a no-op
                    conn.exec_driver_sql(statement)

                for statement in dropping._RECREATE_STATEMENTS:  # downgrade
                    conn.exec_driver_sql(statement)
                assert _existing_triggers(conn) == _TRIGGERS
                assert _function_exists(conn)
            finally:
                tx.rollback()
