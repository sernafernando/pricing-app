"""Migration `20261112_sell_in_bono_cubre_pedido` (sell in factura pendiente): linking the invoice of an operation
with an active invoice bonus queues it whatever the bonus's range; the date gate stays for everything else; the
downgrade restores the previous functions. On a real Postgres, over stub tables with the previous functions."""

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

from tests.services.sell._schema import throwaway_schema

_BACKEND_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_VERSIONS = os.path.join(_BACKEND_ROOT, "alembic", "versions")
_REVISION = "20261112_sell_in_bono_cubre_pedido"


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
    """CREATE TABLE sell_in_bonos_marca (
        id BIGSERIAL PRIMARY KEY, alcance TEXT NOT NULL, marca TEXT, pedido_id BIGINT,
        estado TEXT NOT NULL DEFAULT 'activa', fecha_desde DATE NOT NULL, fecha_hasta DATE NOT NULL
    )""",
    "CREATE TABLE pedidos_compra (id BIGINT PRIMARY KEY, fecha_factura DATE, estado TEXT)",
    "CREATE TABLE pedido_compra_lineas_facturadas (id BIGSERIAL PRIMARY KEY, pedido_id BIGINT, item_id INTEGER)",
    """CREATE TABLE sell_in_bono_dirty (
        tipo TEXT NOT NULL, ref BIGINT NOT NULL, enqueued_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        attempts INTEGER NOT NULL DEFAULT 0, last_error TEXT, PRIMARY KEY (tipo, ref)
    )""",
    _sql("FUNCTION sell_in_bono_cubre(p_fecha"),
    *_module().FUNCIONES_DOWN,  # what production runs before this revision
    "CREATE TRIGGER t_pedidos AFTER UPDATE ON pedidos_compra FOR EACH ROW EXECUTE FUNCTION sell_in_bono_enqueue_pedido()",
    "CREATE TRIGGER t_lineas AFTER INSERT ON pedido_compra_lineas_facturadas FOR EACH ROW "
    "EXECUTE FUNCTION sell_in_bono_enqueue_linea()",
    # An invoice bonus waiting for operation 1 (placeholder day), a brand bonus over October.
    "INSERT INTO sell_in_bonos_marca (alcance, pedido_id, fecha_desde, fecha_hasta) "
    "VALUES ('factura', 1, '2026-11-12', '2026-11-12')",
    "INSERT INTO sell_in_bonos_marca (alcance, marca, fecha_desde, fecha_hasta) "
    "VALUES ('marca', 'TP-LINK', '2026-10-01', '2026-10-31')",
    "INSERT INTO pedidos_compra (id) VALUES (1), (2)",
]


def _step(engine: Engine, step: str) -> None:
    module = _module()
    with engine.connect() as conn:
        ctx = MigrationContext.configure(conn)
        with ctx.begin_transaction(), Operations.context(ctx):
            getattr(module, step)()


@pytest.fixture
def before() -> Iterator[Engine]:
    with throwaway_schema("si_bono_cubre_pedido", [], _STUBS) as engine:
        yield engine


def _facturar(engine: Engine, pedido: int, fecha: str) -> list:
    """Links an invoice dated `fecha` to `pedido` and returns what got queued."""
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM sell_in_bono_dirty"))
        conn.execute(text("UPDATE pedidos_compra SET fecha_factura = :f WHERE id = :p"), {"f": fecha, "p": pedido})
        return [tuple(r) for r in conn.execute(text("SELECT tipo, ref FROM sell_in_bono_dirty ORDER BY 1, 2"))]


def test_this_revision_chains_on_the_producto_envio_eleccion_revision() -> None:
    config = Config(os.path.join(_BACKEND_ROOT, "alembic.ini"))
    config.set_main_option("script_location", os.path.join(_BACKEND_ROOT, "alembic"))
    script = ScriptDirectory.from_config(config)
    revision = script.get_revision(_REVISION)
    assert revision is not None
    assert revision.down_revision == "20261112_producto_envio_eleccion"
    assert len(script.get_heads()) == 1


@pytest.mark.postgres
def test_upgrade_queues_the_operation_of_a_waiting_invoice_bonus_and_keeps_the_date_gate(before) -> None:
    assert _facturar(before, 1, "2026-12-05") == []  # before: the invoice bonus's placeholder day misses it
    with before.begin() as conn:
        conn.execute(text("UPDATE pedidos_compra SET fecha_factura = NULL"))

    _step(before, "upgrade")

    assert _facturar(before, 1, "2026-12-06") == [("pedido", 1)]
    assert _facturar(before, 2, "2026-12-05") == []  # no bonus of its own: the date gate, as before
    assert _facturar(before, 2, "2026-10-10") == [("pedido", 2)]
    with before.begin() as conn:
        conn.execute(text("DELETE FROM sell_in_bono_dirty"))
        conn.execute(text("INSERT INTO pedido_compra_lineas_facturadas (pedido_id, item_id) VALUES (1, 2964)"))
        assert conn.execute(text("SELECT tipo, ref FROM sell_in_bono_dirty")).all() == [("pedido", 1)]


@pytest.mark.postgres
def test_downgrade_restores_the_date_gate_and_drops_the_new_function(before) -> None:
    _step(before, "upgrade")
    _step(before, "downgrade")

    assert _facturar(before, 1, "2026-12-05") == []
    with before.connect() as conn:
        assert conn.execute(text("SELECT to_regproc('sell_in_bono_cubre_pedido')")).scalar() is None


def test_the_live_module_functions_are_this_revisions_and_the_downgrade_restores_the_previous_ones() -> None:
    from app.services.sell_in import bono_queue

    vivos = {_norm(s) for s in bono_queue.UPGRADE_SQL}
    gate, *funciones = _module().FUNCIONES_UP
    assert {_norm(s) for s in funciones} <= vivos
    # The gate was widened later (20261112_tactical_facturas_pendientes), whose downgrade restores this one.
    assert _norm(gate) in {_norm(s) for s in _module("20261112_tactical_facturas_pendientes").FUNCIONES_DOWN}
    previos = {_norm(s) for s in _module("20261115_sell_in_bono_queue_alcance")._TRIGGERS_UP}
    assert {_norm(s) for s in _module().FUNCIONES_DOWN} <= previos


def _norm(sql: str) -> str:
    return " ".join(sql.split())
