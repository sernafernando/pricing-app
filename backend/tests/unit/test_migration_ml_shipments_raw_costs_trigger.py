"""Migration `20261008_ml_shipments_raw_costs_trigger` (ventas-ml-bonificacion-envio-flex).

Graph assertions run everywhere; the DDL assertions need Postgres (a
plpgsql trigger does not exist in SQLite) and are marked accordingly.
"""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import text

_BACKEND_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_REVISION = "20261008_ml_shipments_raw_costs_trigger"


def _script_directory() -> ScriptDirectory:
    config = Config(os.path.join(_BACKEND_ROOT, "alembic.ini"))
    config.set_main_option("script_location", os.path.join(_BACKEND_ROOT, "alembic"))
    return ScriptDirectory.from_config(config)


def _load_migration():
    path = Path(_BACKEND_ROOT) / "alembic" / "versions" / f"{_REVISION}.py"
    spec = importlib.util.spec_from_file_location("ml_shipments_raw_costs_trigger_migration", path)
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
        revision = _script_directory().get_revision(_REVISION)
        assert isinstance(revision.down_revision, str)


def _trigger_definition(conn) -> str:
    return conn.execute(
        text(
            "SELECT pg_get_triggerdef(t.oid) FROM pg_trigger t JOIN pg_class c ON c.oid = t.tgrelid "
            "WHERE c.relname = 'ml_shipments_ops' AND t.tgname = 'trg_order_metrics_shipments_ops_update'"
        )
    ).scalar()


@pytest.mark.postgres
class TestMigrationDdl:
    def test_upgrade_watches_raw_costs_and_downgrade_restores_pr4(self, pg_order_metrics_triggers_engine) -> None:
        migration = _load_migration()
        with pg_order_metrics_triggers_engine.begin() as conn:
            try:
                for statement in migration._DOWNGRADE_STATEMENTS:
                    conn.exec_driver_sql(statement)
                assert "raw_costs" not in _trigger_definition(conn)

                for statement in migration._UPGRADE_STATEMENTS:
                    conn.exec_driver_sql(statement)
                definition = _trigger_definition(conn)
                assert "raw_costs" in definition
                assert "IS DISTINCT FROM" in definition

                # Idempotent: applying it twice never collides on CREATE TRIGGER.
                for statement in migration._UPGRADE_STATEMENTS:
                    conn.exec_driver_sql(statement)
            finally:
                for statement in migration._UPGRADE_STATEMENTS:
                    conn.exec_driver_sql(statement)
