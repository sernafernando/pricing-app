"""Migration `20261213_sell_in_bono_costo_triggers` (sell-in-sell-out T25b2, S30): a fuera/TN sale whose `costo_total`
changes queues its line in `sell_dirty`, and a product whose brand, category or VAT rate changes queues the % of the
sale's cost bonuses reaching it; the downgrade puts the previous triggers back. On a real Postgres, in a throwaway
schema with the live triggers (`_bono_world`), downgraded first to stand for the database before this revision."""

from __future__ import annotations

import importlib.util
import os
from datetime import date
from decimal import Decimal
from typing import Iterator

import pytest
from alembic.config import Config
from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import Engine, text

from app.services.sell import queue as sell_queue
from app.services.sell_in import bono_queue
from tests.services.sell_in import _bono_world as b
from tests.services.sell_in import _world as w

_BACKEND_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_VERSIONS = os.path.join(_BACKEND_ROOT, "alembic", "versions")
_REVISION = "20261213_sell_in_bono_costo_triggers"


def _module(revision: str = _REVISION):
    spec = importlib.util.spec_from_file_location(f"{revision}_migration", os.path.join(_VERSIONS, f"{revision}.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _step(engine: Engine, step: str) -> None:
    with engine.connect() as conn:
        ctx = MigrationContext.configure(conn)
        with ctx.begin_transaction(), Operations.context(ctx):
            getattr(_module(), step)()


@pytest.fixture
def before() -> Iterator[Engine]:
    """The database as 20261212 left it: the live triggers, downgraded by this revision."""
    with b.world("si_bono_costo_trg") as engine:
        _step(engine, "downgrade")
        yield engine


def _cambios(engine: Engine) -> tuple:
    """A TP-LINK cost bonus and a fuera sale of 2964 with a recorded cost; then the product changes brand and the
    sale's cost changes. Returns (cost bonuses queued, sale lines queued)."""
    bono = b.bono_costo(engine)
    ref = w.venta(engine, "fuera", 2964, 2, date(2026, 10, 5))
    w.update_venta(engine, "fuera", ref, costo_total=Decimal("2000.00"))
    b.clear_queue(engine)
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM sell_dirty"))
        conn.execute(text("UPDATE productos_erp SET marca = 'OTRA' WHERE item_id = 2964"))
    w.update_venta(engine, "fuera", ref, costo_total=Decimal("1800.00"))
    return [k for k in b.queued(engine) if k == ("bono", bono)], [r for r in w.queued(engine) if r == ("fuera", ref)]


def test_this_revision_chains_on_the_cost_bonus_revision_and_is_the_single_head() -> None:
    config = Config(os.path.join(_BACKEND_ROOT, "alembic.ini"))
    config.set_main_option("script_location", os.path.join(_BACKEND_ROOT, "alembic"))
    script = ScriptDirectory.from_config(config)
    revision = script.get_revision(_REVISION)
    assert revision is not None
    assert revision.down_revision == "20261212_sell_in_bono_costo"
    assert len(script.get_heads()) == 1


@pytest.mark.postgres
def test_before_it_neither_change_queues_and_after_the_upgrade_both_do(before) -> None:
    bonos, lineas = _cambios(before)
    assert (len(bonos), len(lineas)) == (0, 0)
    b.clean(before)

    _step(before, "upgrade")

    bonos, lineas = _cambios(before)
    assert (len(bonos), len(lineas)) == (1, 1)


@pytest.mark.postgres
def test_after_the_upgrade_an_unrelated_change_queues_nothing(before) -> None:
    _step(before, "upgrade")
    b.bono_costo(before)
    ref = w.venta(before, "fuera", 2964, 2, date(2026, 10, 5))
    b.clear_queue(before)
    with before.begin() as conn:
        conn.execute(text("DELETE FROM sell_dirty"))
        conn.execute(text("UPDATE productos_erp SET costo = 1, descripcion = 'Otra' WHERE item_id = 2964"))
    w.update_venta(before, "fuera", ref, cliente="Otro")

    assert (b.queued(before), w.queued(before)) == ([], [])


@pytest.mark.postgres
def test_what_was_queued_before_still_is(before) -> None:
    """The invoice operations on a brand change (20261115) and a `costo_unitario` change (20261031)."""
    _step(before, "upgrade")
    b.bono(before)
    pedido = b.pedido(before, {2964: 1})
    ref = w.venta(before, "fuera", 2964, 1, date(2026, 10, 5))
    b.clear_queue(before)
    with before.begin() as conn:
        conn.execute(text("DELETE FROM sell_dirty"))
        conn.execute(text("UPDATE productos_erp SET marca = 'OTRA' WHERE item_id = 2964"))
    w.update_venta(before, "fuera", ref, costo_unitario=Decimal("1"))

    assert (b.queued(before), w.queued(before)) == ([("pedido", pedido)], [("fuera", ref)])


@pytest.mark.postgres
def test_both_steps_are_idempotent_and_the_downgrade_restores_the_previous_triggers(before) -> None:
    _step(before, "upgrade")
    _step(before, "upgrade")
    _step(before, "downgrade")
    _step(before, "downgrade")

    bonos, lineas = _cambios(before)
    assert (len(bonos), len(lineas)) == (0, 0)
    with before.connect() as conn:
        funcion = conn.execute(text("SELECT prosrc FROM pg_proc WHERE proname = 'sell_in_bono_enqueue_producto'"))
        assert "costo_venta" not in funcion.scalar()


@pytest.mark.postgres
@pytest.mark.parametrize("step", ["upgrade", "downgrade"])
def test_it_restores_the_lock_timeout_the_transaction_had(before, step) -> None:
    if step == "downgrade":
        _step(before, "upgrade")
    with before.connect() as conn:
        ctx = MigrationContext.configure(conn)
        with ctx.begin_transaction(), Operations.context(ctx):
            conn.exec_driver_sql("SET LOCAL lock_timeout = '17s'")
            getattr(_module(), step)()
            assert conn.exec_driver_sql("SHOW lock_timeout").scalar() == "17s"


def _norm(sql: str) -> str:
    return " ".join(sql.split())


def test_the_live_module_statements_are_this_revisions() -> None:
    """What the test worlds install (the modules) is what this revision installs; what its downgrade restores is what
    20261115 and 20261031 installed."""
    module = _module()
    vivos = {_norm(s) for s in bono_queue.UPGRADE_SQL + sell_queue.UPGRADE_SQL}
    assert {_norm(s) for s in module.PRODUCTO_UP + module.SELL_DIRTY_UP} <= vivos
    previos = {_norm(s) for s in _module("20261115_sell_in_bono_queue_alcance")._TRIGGERS_UP}
    previos |= {_norm(s) for s in _module("20261031_sell_dirty_queue")._TRIGGERS_UP}
    assert {_norm(s) for s in module.PRODUCTO_DOWN + module.SELL_DIRTY_DOWN} <= previos
