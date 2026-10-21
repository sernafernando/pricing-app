"""Migration `20261109_sell_out_triggers` (sell-in-sell-out T7 S4): the chain,
the frozen copy of the live trigger SQL and upgrade/downgrade on a real Postgres.

What each trigger queues is proven by `tests/services/sell_out/test_triggers_postgres.py`,
which runs the module's SQL; the frozen-copy test ties it to this migration.
"""

from __future__ import annotations

import importlib.util
import os
from typing import Iterator

import pytest
from alembic.config import Config
from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import Engine, text

from app.services.sell_out import triggers
from tests.services.sell_out import _world as w

_BACKEND_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_REVISION = "20261109_sell_out_triggers"
_PATH = os.path.join(_BACKEND_ROOT, "alembic", "versions", f"{_REVISION}.py")
_TRIGGERS = (
    "SELECT tgname FROM pg_trigger t JOIN pg_class c ON c.oid = t.tgrelid "
    "WHERE c.relnamespace = current_schema()::regnamespace AND NOT t.tgisinternal AND tgname LIKE 'trg_sell_out_%'"
)
_FUNCTIONS = (
    "SELECT proname FROM pg_proc WHERE pronamespace = current_schema()::regnamespace AND proname LIKE 'sell_out_%'"
)
_DRIFT = (
    "app/services/sell_out/triggers.py {} differs from the frozen copy in {}: changing the module's trigger SQL "
    "requires a NEW migration that installs it (then point this test at that migration)"
)


def _scripts() -> ScriptDirectory:
    config = Config(os.path.join(_BACKEND_ROOT, "alembic.ini"))
    config.set_main_option("script_location", os.path.join(_BACKEND_ROOT, "alembic"))
    return ScriptDirectory.from_config(config)


def _module():
    spec = importlib.util.spec_from_file_location("sell_out_triggers_migration", _PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _step(engine: Engine, step: str) -> None:
    with engine.connect() as conn:
        ctx = MigrationContext.configure(conn)
        with ctx.begin_transaction(), Operations.context(ctx):
            getattr(_module(), step)()


def _names(engine: Engine, sql: str) -> set[str]:
    with engine.connect() as conn:
        return {r[0] for r in conn.execute(text(sql))}


class TestMigrationGraph:
    def test_this_revision_chains_on_the_sell_out_consumos_revision(self) -> None:
        # Not `get_heads() == [this]`: a later revision must not break this test.
        revision = _scripts().get_revision(_REVISION)
        assert revision is not None
        assert revision.down_revision == "20261108_sell_out_consumos"


class TestFrozenTriggerCopy:
    def test_the_upgrade_installs_exactly_the_module_trigger_sql(self) -> None:
        assert _module().UPGRADE_SQL == triggers.UPGRADE_SQL, _DRIFT.format("UPGRADE_SQL", _REVISION)

    def test_the_downgrade_drops_exactly_the_module_trigger_sql(self) -> None:
        assert _module().DOWNGRADE_SQL == triggers.DOWNGRADE_SQL, _DRIFT.format("DOWNGRADE_SQL", _REVISION)


@pytest.fixture()
def engine() -> Iterator[Engine]:
    with w.world("so_trg_mig") as engine:
        yield engine


@pytest.mark.postgres
class TestUpgradeDowngrade:
    def test_upgrade_installs_the_triggers_and_downgrade_removes_everything(self, engine: Engine) -> None:
        cid = w.campana(engine, [w.grupo(engine, [{"marca": "TP-LINK"}])])

        _step(engine, "upgrade")
        assert _names(engine, _TRIGGERS) == {
            "trg_sell_out_filtros_insert_delete",
            "trg_sell_out_filtros_update",
            "trg_sell_out_productos_insert_delete",
            "trg_sell_out_productos_update",
            "trg_sell_out_fuera_update",
            "trg_sell_out_tn_update",
        }
        w.execute(engine, "UPDATE productos_erp SET marca = 'MERCUSYS' WHERE item_id = 2270")
        assert w.queued(engine) == [(cid, 0, None)]

        _step(engine, "downgrade")
        assert _names(engine, _TRIGGERS) == set()
        assert _names(engine, _FUNCTIONS) == set()
        w.clear_queue(engine)
        w.execute(engine, "UPDATE productos_erp SET marca = 'TP-LINK' WHERE item_id = 2270")
        assert w.queued(engine) == []
