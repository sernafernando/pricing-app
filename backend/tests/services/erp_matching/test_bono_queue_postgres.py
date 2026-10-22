"""PostgreSQL: an amount-only reconcile does not queue the pedido for the sell-in bonus.

The reconcile upsert keeps `cantidad` in its SET list even when only
importe_neto/moneda changed. What keeps the bonus queue quiet is the trigger's
WHEN clause (`(OLD.pedido_id, OLD.item_id, OLD.cantidad) IS DISTINCT FROM
(NEW...)`, 20261107_sell_in_bonos_marca), not the SET list: a bonus is per unit,
so an amount change must not re-run it, while a quantity change must.
"""

from __future__ import annotations

import importlib.util
import os
from typing import Iterator

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session

from app.services.erp_matching_service import reconciliar_lineas_facturadas
from tests.services.erp_matching._schema import BONO_FUNCIONES, USD, filas, lf_schema, linea, pedido_con_factura

pytestmark = pytest.mark.postgres

_BACKEND_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
_MIGRATION_20261107 = os.path.join(_BACKEND_ROOT, "alembic", "versions", "20261107_sell_in_bonos_marca.py")


@pytest.fixture
def eng() -> Iterator[Engine]:
    with lf_schema(con_bono=True) as engine:
        with engine.begin() as conn:
            # An active bonus covering the pedido's invoice date: the trigger's gate is open.
            conn.execute(
                text(
                    "INSERT INTO sell_in_bonos_marca (id, marca, fecha_desde, fecha_hasta) "
                    "VALUES (1, 'TP-LINK', '2026-10-01', '2026-10-31')"
                )
            )
            pedido_con_factura(conn)
            conn.execute(text("UPDATE pedidos_compra SET fecha_factura = '2026-10-15' WHERE id = 1"))
            linea(conn, 1, 100, 501, "2", "10", USD)
        _reconciliar(engine)
        assert _cola(engine) == [("pedido", 1)]  # the first snapshot row did queue it (INSERT trigger)
        with engine.begin() as conn:
            conn.execute(text("DELETE FROM sell_in_bono_dirty"))
        yield engine


def _reconciliar(eng: Engine) -> int:
    with Session(eng) as session:
        cambios = reconciliar_lineas_facturadas(session, 1)
        session.commit()
    return cambios


def _cola(eng: Engine) -> list[tuple]:
    with eng.connect() as conn:
        return [tuple(r) for r in conn.execute(text("SELECT tipo, ref FROM sell_in_bono_dirty ORDER BY tipo, ref"))]


@pytest.mark.parametrize(
    ("cambio", "esperado"),
    [
        ("UPDATE tb_item_transactions SET it_price = 12 WHERE it_transaction = 1", (1, 501, 2, "24.00", "USD")),
        ("UPDATE tb_item_transactions SET curr_id = 1 WHERE it_transaction = 1", (1, 501, 2, "20.00", "ARS")),
    ],
    ids=["amount", "currency"],
)
def test_an_amount_or_currency_only_change_updates_the_row_and_queues_nothing(eng, cambio, esperado):
    with eng.begin() as conn:
        conn.execute(text(cambio))

    assert _reconciliar(eng) == 1
    assert filas(eng) == [esperado]
    assert _cola(eng) == []


def test_a_quantity_change_queues_the_pedido(eng):
    with eng.begin() as conn:
        conn.execute(text("UPDATE tb_item_transactions SET it_qty = 3 WHERE it_transaction = 1"))

    assert _reconciliar(eng) == 1
    assert filas(eng) == [(1, 501, 3, "30.00", "USD")]
    assert _cola(eng) == [("pedido", 1)]


def test_the_fake_schema_triggers_are_a_verbatim_copy_of_the_migration():
    spec = importlib.util.spec_from_file_location("sell_in_bonos_marca_migration", _MIGRATION_20261107)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    assert [s for s in BONO_FUNCIONES if s not in module._TRIGGERS_UP] == []
