"""A generated purchase's "Costo antes / Costo después" come from the INVOICE (sell in incident 2026-11-24, S2).

Owner rule L38: "te entran 200 unidades con un descuento del 1% son 200 unidades con un costo más barato que el de la
factura". So a line's unit cost before the sell in is the invoice unit price (the invoiced net over the invoiced
units, `pedido_compra_lineas_facturadas`) and the unit cost after is that price less the line's unit sell in, in the
invoice's currency; never the product's list cost times the purchase's rate. The line amount was already right and
does not change. A line with no invoiced price yet keeps the product's cost, as before.

The cases are the real production rows of 2026-11-24 (Distecna compra 28 / item 22 and compra 31 / item 4202), read
back through `compras.serializar`, the serializer of `GET /api/sell-in/compras/{id}`.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Iterator

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.orm import sessionmaker

from app.models.sell_in import SellInCompra
from app.services.sell_in import bonos, compras
from tests.services.sell_in import _bono_world as b

D = date


@pytest.fixture(scope="module")
def engine() -> Iterator[Engine]:
    with b.world("sell_in_precio_factura") as engine:
        yield engine


@pytest.fixture(autouse=True)
def _clean(engine: Engine) -> Iterator[None]:
    yield
    b.clean(engine)


def _producto(engine: Engine, item_id: int, costo: str, moneda: str = "USD") -> None:
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO productos_erp (item_id, codigo, descripcion, marca, costo, moneda_costo) "
                "VALUES (:i, :c, 'Producto', :m, :costo, :mon)"
            ),
            {"i": item_id, "c": f"C{item_id}", "m": b.TPLINK, "costo": costo, "mon": moneda},
        )


def _reconciliar(engine: Engine, **kwargs) -> bonos.ReconcileResult:
    with sessionmaker(bind=engine)() as db:
        result = bonos.reconciliar(db, **kwargs)
        db.commit()
    return result


def _detalle(engine: Engine, bono_id: int, pedido_id: int) -> dict:
    """The purchase as the detail endpoint returns it."""
    with sessionmaker(bind=engine)() as db:
        [fila] = compras.serializar(db, [db.get(SellInCompra, b.compra_id(engine, bono_id, pedido_id))])
    return fila


def _linea(fila: dict) -> tuple:
    [item] = fila["items"]
    return (
        item["item_id"],
        item["cantidad"],
        item["costo_base_unit"],
        item["monto_asignado"],
        item["descuento_unit"],
        item["costo_con_sell_in_unit"],
        item["porcentaje"],
    )


def _bono_factura(engine: Engine, pedido_id: int, porcentaje: str, moneda: str, fecha: date) -> int:
    return b.bono_alcance(
        engine,
        "factura",
        tipo="porcentaje",
        porcentaje=porcentaje,
        moneda=moneda,
        pedido_id=pedido_id,
        desde=fecha,
        hasta=fecha,
    )


@pytest.mark.postgres
class TestCostoDeLaFactura:
    def test_costo_antes_is_the_invoice_unit_price_and_despues_is_that_price_less_the_percentage(
        self, engine: Engine
    ) -> None:
        # Distecna compra 28 / item 22: 200 u invoiced at 26,856.90 ARS (curr_id 1), bonus 91 at 1 %, ARS, BNA 1580.
        # The product's list cost (17.04 USD x 1580 = 26,923.20) is what was stored and shown.
        _producto(engine, 22, "17.04")
        fecha = D(2026, 11, 18)
        b.tipo_cambio(engine, fecha, 1580)
        pedido = b.pedido(engine, {22: 200}, fecha, moneda="ARS", tipo_cambio=None)
        b.set_importe(engine, pedido, 22, "5371380.00", "ARS")  # 200 x 26,856.90
        bono = _bono_factura(engine, pedido, "1", "ARS", fecha)

        _reconciliar(engine, bono_ids=[bono])

        fila = _detalle(engine, bono, pedido)
        assert (fila["moneda"], fila["monto_total"]) == ("ARS", Decimal("53713.80"))
        assert _linea(fila) == (
            22,
            200,
            Decimal("26856.900000"),  # antes: the invoice unit price
            Decimal("53713.80"),  # the line amount, unchanged: 200 x 26,856.90 x 1 %
            Decimal("268.569000"),  # the unit sell in
            Decimal("26588.331000"),  # después: 26,856.90 x (1 - 1 %)
            Decimal("1.00"),
        )

    def test_a_cost_far_below_the_invoice_takes_the_invoice_price(self, engine: Engine) -> None:
        # Compra 31 / item 4202: 12 u invoiced at 351,376.20 ARS, bonus 89 at 5.76 %, ARS, the operation's rate 1580.
        # Stored and shown: 294,559.40 (186.43 USD x 1580), 0.838 of the invoice price.
        _producto(engine, 4202, "186.43")
        fecha = D(2026, 11, 19)
        pedido = b.pedido(engine, {4202: 12}, fecha, moneda="ARS", tipo_cambio="1580.000000")
        b.set_importe(engine, pedido, 4202, "4216514.40", "ARS")  # 12 x 351,376.20
        bono = _bono_factura(engine, pedido, "5.76", "ARS", fecha)

        _reconciliar(engine, bono_ids=[bono])

        fila = _detalle(engine, bono, pedido)
        assert fila["moneda"] == "ARS"
        assert _linea(fila) == (
            4202,
            12,
            Decimal("351376.200000"),
            Decimal("242871.23"),
            Decimal("20239.269167"),
            Decimal("331136.930833"),
            Decimal("5.76"),
        )

    def test_a_changed_line_takes_the_new_invoice_price_and_a_line_that_stays_is_not_rewritten(
        self, engine: Engine
    ) -> None:
        # A reconcile never fixes stored rows by itself (parent decision 3): only a changed line is rewritten.
        bono = b.bono_alcance(engine, "modelos", modelos=(2964, 2270), tipo="porcentaje", porcentaje="1", moneda="USD")
        pedido = b.pedido(engine, {2964: 4, 2270: 2})
        b.set_importe(engine, pedido, 2964, "200.00", "USD")  # 50.00 a unit
        b.set_importe(engine, pedido, 2270, "20.00", "USD")  # 10.00 a unit
        _reconciliar(engine, bono_ids=[bono])
        with engine.begin() as conn:  # a stored cost from before the fix, on both lines
            conn.execute(text("UPDATE sell_in_compra_items SET costo_base_unit = 41.5"))
        b.set_importe(engine, pedido, 2964, "160.00", "USD")  # a credit note: 40.00 a unit

        result = _reconciliar(engine, bono_ids=[bono])

        assert (result.creadas, result.actualizadas, result.anuladas) == (0, 1, 0)
        costos = {
            i["item_id"]: (i["costo_base_unit"], i["monto_asignado"]) for i in _detalle(engine, bono, pedido)["items"]
        }
        assert costos == {
            2270: (Decimal("41.500000"), Decimal("0.20")),  # stays: not rewritten
            2964: (Decimal("40.000000"), Decimal("1.60")),  # changed: the new invoice price
        }

    def test_a_line_with_no_invoiced_price_yet_keeps_the_products_cost(self, engine: Engine) -> None:
        # Today's behaviour, kept: no invoiced net on the snapshot line (NULL) -> the product's cost at the rate.
        bono = b.bono(engine, monto="1000.00", moneda="ARS")
        pedido = b.pedido(engine, {2964: 3}, moneda="ARS", tipo_cambio="1450.000000")

        _reconciliar(engine, bono_ids=[bono])

        fila = _detalle(engine, bono, pedido)
        assert (fila["moneda"], fila["monto_total"]) == ("ARS", Decimal("3000.00"))
        assert _linea(fila) == (
            2964,
            3,
            Decimal("60175.000000"),  # 41.50 USD x 1450
            Decimal("3000.00"),
            Decimal("1000.000000"),
            Decimal("59175.000000"),
            Decimal("1.66"),
        )
