"""Migration `20261112_tactical_facturas_pendientes` (sell in factura pendiente, monto total): creates the waiting
invoice totals table and widens the operation gate to it; the downgrade restores the previous gate and drops the
table. On a real Postgres, over stub tables with the previous gate."""

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
from sqlalchemy.exc import IntegrityError

from tests.services.sell._schema import throwaway_schema

_BACKEND_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_VERSIONS = os.path.join(_BACKEND_ROOT, "alembic", "versions")
_REVISION = "20261112_tactical_facturas_pendientes"


def _module(revision: str = _REVISION):
    spec = importlib.util.spec_from_file_location(f"{revision}_m", os.path.join(_VERSIONS, f"{revision}.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _sql(nombre: str) -> str:
    from app.services.sell_in import bono_queue

    [sentencia] = [s for s in bono_queue.UPGRADE_SQL if nombre in s]
    return sentencia


_STUBS = [
    "CREATE TABLE usuarios (id INTEGER PRIMARY KEY)",
    "CREATE TABLE tacticals (id BIGINT PRIMARY KEY)",
    "CREATE TABLE pedidos_compra (id BIGINT PRIMARY KEY)",
    "CREATE TABLE sell_in_compras (id BIGINT PRIMARY KEY)",
    """CREATE TABLE sell_in_bonos_marca (
        id BIGSERIAL PRIMARY KEY, alcance TEXT NOT NULL, marca TEXT, pedido_id BIGINT,
        estado TEXT NOT NULL DEFAULT 'activa', fecha_desde DATE NOT NULL, fecha_hasta DATE NOT NULL
    )""",
    _sql("FUNCTION sell_in_bono_cubre(p_fecha"),
    *_module().FUNCIONES_DOWN,  # what production runs before this revision
    "INSERT INTO usuarios VALUES (7)",
    "INSERT INTO tacticals VALUES (1)",
    "INSERT INTO pedidos_compra VALUES (10), (11)",
]


def _step(engine: Engine, step: str) -> None:
    module = _module()
    with engine.connect() as conn:
        ctx = MigrationContext.configure(conn)
        with ctx.begin_transaction(), Operations.context(ctx):
            getattr(module, step)()


@pytest.fixture
def before() -> Iterator[Engine]:
    with throwaway_schema("tactical_fact_pend", [], _STUBS) as engine:
        yield engine


def _cubre(engine: Engine, pedido: int) -> bool:
    with engine.connect() as conn:
        return conn.execute(text("SELECT sell_in_bono_cubre_pedido('2026-10-10', :p)"), {"p": pedido}).scalar()


def _pendiente(engine: Engine, pedido: int, **campos) -> None:
    valores = {"tactical_id": 1, "tactical_linea": 1, "pedido_id": pedido, "valor": 100, "moneda": "ARS",
               "usuario_id": 7, **campos}  # fmt: skip
    columnas = ", ".join(valores)
    with engine.begin() as conn:
        conn.execute(
            text(
                f"INSERT INTO tactical_facturas_pendientes ({columnas}) VALUES ({', '.join(':' + c for c in valores)})"
            ),
            valores,
        )


def test_this_revision_chains_on_the_arribo_progreso_revision() -> None:
    config = Config(os.path.join(_BACKEND_ROOT, "alembic.ini"))
    config.set_main_option("script_location", os.path.join(_BACKEND_ROOT, "alembic"))
    script = ScriptDirectory.from_config(config)
    revision = script.get_revision(_REVISION)
    assert revision is not None
    assert revision.down_revision == "20261112_pedido_compra_arribo_progreso"
    assert len(script.get_heads()) == 1


@pytest.mark.postgres
def test_upgrade_creates_the_table_and_gates_in_an_operation_with_a_waiting_total(before) -> None:
    _step(before, "upgrade")

    assert _cubre(before, 10) is False
    _pendiente(before, 10)
    assert _cubre(before, 10) is True
    assert _cubre(before, 11) is False  # no waiting total, no bonus: the date gate, as before
    with before.begin() as conn:
        conn.execute(text("UPDATE tactical_facturas_pendientes SET estado = 'anulada'"))
    assert _cubre(before, 10) is False  # only a waiting one gates in
    with pytest.raises(IntegrityError):
        _pendiente(before, 11, estado="aplicada")  # an applied one names its purchase
    with pytest.raises(IntegrityError):
        _pendiente(before, 11, valor=0)


@pytest.mark.postgres
def test_downgrade_restores_the_previous_gate_and_drops_the_table(before) -> None:
    _step(before, "upgrade")
    _pendiente(before, 10)
    _step(before, "downgrade")

    assert _cubre(before, 10) is False
    with before.connect() as conn:
        assert conn.execute(text("SELECT to_regclass('tactical_facturas_pendientes')")).scalar() is None


def test_the_next_gate_restores_this_revisions_and_the_downgrade_restores_the_previous_one() -> None:
    # The gate was widened later (20261114_sell_in_cubre_totales_aplicados), whose downgrade restores this one.
    siguiente = _module("20261114_sell_in_cubre_totales_aplicados").FUNCIONES_DOWN
    assert {_norm(s) for s in _module().FUNCIONES_UP} <= {_norm(s) for s in siguiente}
    previa = _module("20261112_sell_in_bono_cubre_pedido").FUNCIONES_UP
    assert {_norm(s) for s in _module().FUNCIONES_DOWN} <= {_norm(s) for s in previa}


def _norm(sql: str) -> str:
    return " ".join(sql.split())
