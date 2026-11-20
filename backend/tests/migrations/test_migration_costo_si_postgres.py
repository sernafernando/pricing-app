"""Migration `20261125_costo_si` (sell-in-costo-si T2): new tables only, plus the queue triggers on the sell-in /
Compras tables; the downgrade removes all of it. On a real Postgres, in a throwaway schema holding the tables the
triggers sit on (`tests.services.costo_si._world`) but not the costo SI ones."""

from __future__ import annotations

import importlib.util
import os
from datetime import date
from typing import Iterator

import pytest
from alembic.config import Config
from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import Engine, text

from app.services.costo_si import queue
from tests.services.costo_si import _world as w
from tests.services.sell._schema import throwaway_schema

_BACKEND_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_REVISION = "20261125_costo_si"
_NUEVAS = {
    "costo_si_pasos",
    "costo_si_backups",
    "costo_si_dirty",
    "costo_si_stock_diario",
    "costo_si_full_operaciones",
    "costo_si_full_cobertura",
    "costo_si_factura_tc",
}


def _module():
    path = os.path.join(_BACKEND_ROOT, "alembic", "versions", f"{_REVISION}.py")
    spec = importlib.util.spec_from_file_location(f"{_REVISION}_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _step(engine: Engine, step: str) -> None:
    with engine.connect() as conn:
        ctx = MigrationContext.configure(conn)
        with ctx.begin_transaction(), Operations.context(ctx):
            getattr(_module(), step)()


@pytest.fixture
def antes() -> Iterator[Engine]:
    tablas = [t for t in w.TABLES if t.name not in _NUEVAS]
    with throwaway_schema("costo_si_mig", tablas, w.STUBS) as engine:
        yield engine


def _tablas(engine: Engine) -> set:
    with engine.connect() as conn:
        return {
            r[0]
            for r in conn.execute(
                text("SELECT table_name FROM information_schema.tables WHERE table_schema = current_schema()")
            )
        }


def _triggers(engine: Engine) -> set:
    with engine.connect() as conn:
        return {
            r[0]
            for r in conn.execute(
                text(
                    "SELECT tgname FROM pg_trigger t JOIN pg_class c ON c.oid = t.tgrelid "
                    "JOIN pg_namespace n ON n.oid = c.relnamespace "
                    "WHERE n.nspname = current_schema() AND tgname LIKE 'costo_si%'"
                )
            )
        }


def test_it_chains_on_the_head_of_main() -> None:
    config = Config(os.path.join(_BACKEND_ROOT, "alembic.ini"))
    config.set_main_option("script_location", os.path.join(_BACKEND_ROOT, "alembic"))
    script = ScriptDirectory.from_config(config)
    assert script.get_revision(_REVISION).down_revision == "20261124_mcp_write_actions"


def test_the_frozen_trigger_sql_is_the_live_definition() -> None:
    module = _module()
    assert (module.UPGRADE_SQL, module.DOWNGRADE_SQL) == (queue.UPGRADE_SQL, queue.DOWNGRADE_SQL)


@pytest.mark.postgres
def test_upgrade_creates_the_tables_and_triggers_and_downgrade_removes_them(antes: Engine) -> None:
    existentes = _tablas(antes)

    _step(antes, "upgrade")

    assert _tablas(antes) - existentes == _NUEVAS
    assert _triggers(antes) == {t[1] for t in queue._TRIGGERS}
    w.producto(antes, 5101)
    w.bono_marca(antes, "3.6", date(2026, 10, 1), date(2026, 12, 31))
    assert w.encolados(antes) == [(5101, date(2026, 10, 1))]

    _step(antes, "downgrade")

    assert _tablas(antes) == existentes
    assert _triggers(antes) == set()
