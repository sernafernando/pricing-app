"""A percentage bonus's purchase is stored in the INVOICE's currency (sell in incident 2026-11-24, S3).

Owner rule L38: the line amount is units x invoice unit price x %, in the invoice's currency. A % has no currency of
its own, so a % bonus loaded as USD on an ARS invoice (bonuses 84/85, tactical 47 "DESC AIR TP", 2.5 %) generates an
ARS purchase: compra 25 = 393,467.14 ARS, not 250.62 USD (÷ 1570). A per-unit bonus's amount does have the bonus's
currency and keeps it; a USD % bonus on a USD invoice is unchanged.

The case is the real production rows of 2026-11-24 (compra 25, operation 326, invoice ct 944606), read back through
`compras.serializar`, the serializer of `GET /api/sell-in/compras/{id}`.
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

# Compra 25's lines: item -> (invoiced units, invoice unit price ARS, product cost USD).
COMPRA_25 = {
    70: (250, "25929.96", "16.5159"),
    454: (20, "40244.28", "25.6333"),
    1249: (200, "42256.55", "26.915"),
}
# Compra 26's lines (bonus 85, operation 325, invoice ct 944607), same shape.
COMPRA_26 = {
    70: (200, "25929.96", "16.5159"),
    455: (800, "7317.14", "4.6606"),
    627: (30, "15146.58", "9.6475"),
    2064: (30, "113415.86", "72.2394"),
    2103: (113, "27850.70", "17.7393"),
    2320: (30, "20195.38", "12.8633"),
    3077: (82, "25929.96", "16.5159"),
}


@pytest.fixture(scope="module")
def engine() -> Iterator[Engine]:
    with b.world("sell_in_moneda_factura") as engine:
        yield engine


@pytest.fixture(autouse=True)
def _clean(engine: Engine) -> Iterator[None]:
    yield
    b.clean(engine)


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


def _operacion(engine: Engine, lineas: dict) -> int:
    """An operation like 325/326: ARS, its own rate 1570, invoiced 2026-11-06 in ARS (curr_id 1)."""
    with engine.begin() as conn:
        for item_id, (_, _, costo) in lineas.items():
            conn.execute(
                text(
                    "INSERT INTO productos_erp (item_id, codigo, descripcion, marca, costo, moneda_costo) "
                    "VALUES (:i, :c, 'Producto', :m, :costo, 'USD')"
                ),
                {"i": item_id, "c": f"C{item_id}", "m": b.TPLINK, "costo": costo},
            )
    pedido = b.pedido(
        engine, {i: u for i, (u, _, _) in lineas.items()}, D(2026, 11, 6), moneda="ARS", tipo_cambio="1570.000000"
    )
    for item_id, (unidades, precio, _) in lineas.items():
        b.set_importe(engine, pedido, item_id, str(Decimal(precio) * unidades), "ARS")
    return pedido


def _bono_factura(engine: Engine, pedido: int, **valores) -> int:
    """Like bonuses 84/85: an invoice bonus of 2.5 %, loaded as USD."""
    fecha = D(2026, 11, 6)
    bono = b.bono_alcance(
        engine, "factura", tipo="porcentaje", porcentaje="2.5", moneda="USD", pedido_id=pedido, desde=fecha, hasta=fecha
    )
    if valores:
        b.update_bono(engine, bono, **valores)
    return bono


@pytest.mark.postgres
class TestMonedaDeLaFactura:
    def test_a_usd_percentage_bonus_on_an_ars_invoice_is_stored_in_ars(self, engine: Engine) -> None:
        pedido = _operacion(engine, COMPRA_25)
        fecha = D(2026, 11, 6)
        bono = _bono_factura(engine, pedido)

        _reconciliar(engine, bono_ids=[bono])

        # (bono, pedido, estado, moneda, monto_total, tipo_cambio, fecha, proveedor): the rate stays the operation's.
        assert b.generadas(engine) == [
            (bono, pedido, "activa", "ARS", Decimal("393467.14"), Decimal("1570.000000"), fecha, 31)
        ]
        assert b.items_de(engine, bono, pedido) == [
            (70, 250, Decimal("162062.25")),
            (454, 20, Decimal("20122.14")),
            (1249, 200, Decimal("211282.75")),
        ]
        fila = _detalle(engine, bono, pedido)
        assert (fila["moneda"], fila["monto_total"], fila["tipo_cambio"]) == (
            "ARS",
            Decimal("393467.14"),
            Decimal("1570.000000"),
        )
        # Every line in ARS, its cost before the invoice price (S2) and its amount 2.5 % of it.
        assert [(i["item_id"], i["costo_base_unit"], i["monto_asignado"], i["porcentaje"]) for i in fila["items"]] == [
            (70, Decimal("25929.960000"), Decimal("162062.25"), Decimal("2.50")),
            (454, Decimal("40244.280000"), Decimal("20122.14"), Decimal("2.50")),
            (1249, Decimal("42256.550000"), Decimal("211282.75"), Decimal("2.50")),
        ]

    def test_compra_26_is_the_sum_of_its_lines_rounded_each(self, engine: Engine) -> None:
        # The header is the sum of the per-line amounts, each half up to cents (the existing rule): 519,395.63 ARS.
        # The incident handoff's 519,395.61 rounds the total once.
        pedido = _operacion(engine, COMPRA_26)
        bono = _bono_factura(engine, pedido)

        _reconciliar(engine, bono_ids=[bono])

        assert b.generadas(engine)[0][3:6] == ("ARS", Decimal("519395.63"), Decimal("1570.000000"))
        assert b.items_de(engine, bono, pedido) == [
            (70, 200, Decimal("129649.80")),
            (455, 800, Decimal("146342.80")),
            (627, 30, Decimal("11359.94")),
            (2064, 30, Decimal("85061.90")),
            (2103, 113, Decimal("78678.23")),
            (2320, 30, Decimal("15146.54")),
            (3077, 82, Decimal("53156.42")),
        ]

    def test_lines_invoiced_in_more_than_one_currency_keep_the_bonus_currency(self, engine: Engine) -> None:
        # Parent decision 4: no single invoice currency -> the bonus's, each line converted at the pair's rate.
        pedido = _operacion(engine, {70: (250, "25929.96", "16.5159"), 454: (20, "40244.28", "25.6333")})
        b.set_importe(engine, pedido, 454, "500.00", "USD")
        bono = _bono_factura(engine, pedido)

        _reconciliar(engine, bono_ids=[bono])

        assert b.generadas(engine)[0][3:6] == ("USD", Decimal("115.72"), Decimal("1570.000000"))
        assert b.items_de(engine, bono, pedido) == [
            (70, 250, Decimal("103.22")),  # 162,062.25 ARS / 1570
            (454, 20, Decimal("12.50")),  # 2.5 % of 500.00 USD
        ]

    def test_a_percentage_bonus_with_a_money_cap_keeps_the_bonus_currency(self, engine: Engine) -> None:
        # Parent decision 5: the cap is in the bonus's currency, so its purchase is too (no change for money caps).
        pedido = _operacion(engine, COMPRA_25)
        bono = _bono_factura(engine, pedido, tope_monto="1000.00")

        _reconciliar(engine, bono_ids=[bono])

        assert b.generadas(engine)[0][3:6] == ("USD", Decimal("250.62"), Decimal("1570.000000"))
        assert b.items_de(engine, bono, pedido) == [
            (70, 250, Decimal("103.22")),
            (454, 20, Decimal("12.82")),
            (1249, 200, Decimal("134.58")),
        ]

    def test_a_usd_percentage_bonus_on_a_usd_invoice_stays_in_usd(self, engine: Engine) -> None:
        # Today's behaviour, kept: the invoice is already in the bonus's currency.
        bono = b.bono_alcance(engine, "modelos", modelos=(2964,), tipo="porcentaje", porcentaje="2.5", moneda="USD")
        pedido = b.pedido(engine, {2964: 4}, moneda="USD", tipo_cambio="1450.000000")
        b.set_importe(engine, pedido, 2964, "1000.00", "USD")

        _reconciliar(engine, bono_ids=[bono])

        assert b.generadas(engine)[0][3:6] == ("USD", Decimal("25.00"), Decimal("1450.000000"))
        assert b.items_de(engine, bono, pedido) == [(2964, 4, Decimal("25.00"))]

    def test_a_per_unit_usd_bonus_on_an_ars_invoice_keeps_the_bonus_currency(self, engine: Engine) -> None:
        # Today's behaviour, kept: an amount per unit has a currency, the bonus's.
        bono = b.bono(engine, monto="2.50", moneda="USD")
        pedido = b.pedido(engine, {2964: 4}, moneda="ARS", tipo_cambio="1450.000000")
        b.set_importe(engine, pedido, 2964, "290000.00", "ARS")

        _reconciliar(engine, bono_ids=[bono])

        assert b.generadas(engine)[0][3:6] == ("USD", Decimal("10.00"), Decimal("1450.000000"))
        assert b.items_de(engine, bono, pedido) == [(2964, 4, Decimal("10.00"))]
