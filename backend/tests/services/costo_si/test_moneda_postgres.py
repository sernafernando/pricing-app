"""Costo SI in the product's cost currency (owner L18, sell-in-costo-si T3 PR 1): an ARS-cost product averages in
pesos, its USD invoices converted with the S4 FX order at the invoice (PM correction, Compras TC, the invoice date's
rate), never at today's rate; a USD-cost product stays in USD. Every step stores the currency it is in.
Spec: handoffs/sell-in-costo-si-feature.md S1, S2, S4, S10; plan handoffs/sell-in-costo-si-t3-paralelo.md Q2.
Invented data."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Iterator

import pytest
from sqlalchemy import Engine
from sqlalchemy.orm import sessionmaker

from app.services.costo_si import recompute
from tests.services.costo_si import _world as w

pytestmark = pytest.mark.postgres

D = Decimal
ARS_P, USD_P = 5301, 5302
ARS, USD = 1, 2


@pytest.fixture(scope="module")
def engine() -> Iterator[Engine]:
    with w.world("costo_si_moneda") as engine:
        yield engine


@pytest.fixture(autouse=True)
def _clean(engine: Engine) -> Iterator[None]:
    yield
    w.clean(engine)


def _recalcular(engine: Engine, item_id: int) -> recompute.Resultado:
    with sessionmaker(bind=engine, autoflush=False)() as db:
        resultado = recompute.recalcular(db, item_id, motivo="test")
        db.commit()
    return resultado


def _compras(engine: Engine, item_id: int) -> list:
    return w.rows(
        engine,
        "SELECT moneda, costo_neto_usd, tipo_cambio, fuente_tc, costo_neto_neto_usd, promedio_usd FROM costo_si_pasos "
        "WHERE item_id = :i ORDER BY orden",
        i=item_id,
    )


def _ars_product(engine: Engine) -> dict:
    """An ARS-cost product: list cost ARS 15000 before the 10 % loyalty starts (10-01, stock 0); then a USD invoice
    linked to Compras at TC 1600, a USD invoice with no link (the 10-05 rate, 1500), a USD invoice the PM corrected to
    1550, and an ARS invoice. Today's rate (3000) must never be used."""
    w.producto(engine, ARS_P, moneda="ARS")
    w.costo_lista(engine, ARS_P, datetime(2026, 9, 1), "15000", curr_id=ARS)
    w.bono_marca(engine, "10", date(2026, 10, 1), date(2026, 12, 31))
    w.tipo_cambio(engine, date(2026, 10, 5), 1500)
    w.tipo_cambio(engine, date(2026, 11, 20), 3000)
    pedido = w.factura(
        engine, ARS_P, date(2026, 10, 4), datetime(2026, 10, 4), 1, "10", previo=0, pedido=8, tc_pedido="1600"
    )
    sin = w.factura(engine, ARS_P, date(2026, 10, 6), datetime(2026, 10, 6), 1, "10", previo=1)
    manual = w.factura(engine, ARS_P, date(2026, 10, 7), datetime(2026, 10, 7), 1, "10", previo=2)
    w.run(engine, "INSERT INTO costo_si_factura_tc (ct_transaction, tipo_cambio) VALUES (:c, 1550)", c=manual)
    pesos = w.factura(engine, ARS_P, date(2026, 10, 8), datetime(2026, 10, 8), 1, "14000", previo=3, curr_id=ARS)
    w.run(engine, "DELETE FROM costo_si_dirty")
    return {"pedido": pedido, "sin": sin, "manual": manual, "pesos": pesos}


def test_an_ars_cost_product_averages_in_pesos_with_each_invoices_own_rate(engine: Engine) -> None:
    """L18: USD nets x the invoice's rate (S4 order), the ARS invoice as is, the start in ARS list cost; 10 % loyalty
    on every net (S6); stock 0 at the start, so the average restarts at the first purchase (S9)."""
    _ars_product(engine)

    _recalcular(engine, ARS_P)

    assert _compras(engine, ARS_P) == [
        ("ARS", D("15000.00000"), None, None, D("13500.00000"), D("13500.00000")),  # less the loyalty (L39/L40)
        ("ARS", D("16000.00000"), D("1600"), "pedido", D("14400.00000"), D("14400.00000")),
        ("ARS", D("15000.00000"), D("1500"), "fecha_factura", D("13500.00000"), D("13950.00000")),
        ("ARS", D("15500.00000"), D("1550"), "manual", D("13950.00000"), D("13950.00000")),
        ("ARS", D("14000.00000"), None, "ars", D("12600.00000"), D("13612.50000")),
    ]


def test_an_ars_product_with_only_usd_invoices_reads_their_dates_rates(engine: Engine) -> None:
    """S4: the rates are read for the invoices NOT in the product's currency."""
    w.producto(engine, ARS_P, moneda="ARS")
    w.costo_lista(engine, ARS_P, datetime(2026, 9, 1), "15000", curr_id=ARS)
    w.bono_marca(engine, "10", date(2026, 10, 1), date(2026, 12, 31))
    w.tipo_cambio(engine, date(2026, 10, 5), 1500)
    w.factura(engine, ARS_P, date(2026, 10, 6), datetime(2026, 10, 6), 1, "10", previo=0)

    _recalcular(engine, ARS_P)

    assert _compras(engine, ARS_P)[1] == (
        "ARS",
        D("15000.00000"),
        D("1500"),
        "fecha_factura",
        D("13500.00000"),
        D("13500.00000"),
    )


def test_a_usd_cost_product_stays_in_usd_and_converts_only_its_ars_invoices(engine: Engine) -> None:
    """S4 as before for a USD-cost product: the ARS invoice at the invoice date's rate, the USD one as is."""
    w.producto(engine, USD_P)
    w.costo_lista(engine, USD_P, datetime(2026, 9, 1), "10")
    w.bono_marca(engine, "10", date(2026, 10, 1), date(2026, 12, 31))
    w.tipo_cambio(engine, date(2026, 10, 5), 1500)
    w.tipo_cambio(engine, date(2026, 11, 20), 3000)
    w.factura(engine, USD_P, date(2026, 10, 6), datetime(2026, 10, 6), 1, "15000", previo=0, curr_id=ARS)
    w.factura(engine, USD_P, date(2026, 10, 7), datetime(2026, 10, 7), 1, "12", previo=1)

    _recalcular(engine, USD_P)

    assert _compras(engine, USD_P) == [
        ("USD", D("10.00000"), None, None, D("9.00000"), D("9.00000")),  # the start less the loyalty (L39/L40)
        ("USD", D("10.00000"), D("1500"), "fecha_factura", D("9.00000"), D("9.00000")),
        ("USD", D("12.00000"), None, "usd", D("10.80000"), D("9.90000")),
    ]


def test_an_ars_product_ignores_usd_list_history_for_its_start(engine: Engine) -> None:
    """S2 in the product's currency: a USD list row is not an ARS start cost (never converted at any rate)."""
    w.producto(engine, ARS_P, moneda="ARS")
    w.costo_lista(engine, ARS_P, datetime(2026, 9, 1), "15000", curr_id=ARS)
    w.costo_lista(engine, ARS_P, datetime(2026, 9, 2), "12", curr_id=USD)
    w.bono_marca(engine, "10", date(2026, 10, 1), date(2026, 12, 31))

    _recalcular(engine, ARS_P)

    # 15000 ARS less the 10 % loyalty in force on the start day (L39/L40)
    assert _compras(engine, ARS_P) == [("ARS", D("15000.00000"), None, None, D("13500.00000"), D("13500.00000"))]


def test_changing_the_products_currency_rewrites_its_history_with_a_backup(engine: Engine) -> None:
    """S8: the currency is part of every step, so a product moved from USD to ARS is recomputed in pesos, the USD
    rows backed up first."""
    _ars_product(engine)
    w.run(engine, "UPDATE productos_erp SET moneda_costo = 'USD' WHERE item_id = :i", i=ARS_P)
    w.costo_lista(engine, ARS_P, datetime(2026, 9, 3), "10", curr_id=USD)
    _recalcular(engine, ARS_P)
    assert {r[0] for r in _compras(engine, ARS_P)} == {"USD"}

    w.run(engine, "UPDATE productos_erp SET moneda_costo = 'ARS' WHERE item_id = :i", i=ARS_P)
    resultado = _recalcular(engine, ARS_P)

    assert resultado.desde == date(2026, 10, 1)
    assert {r[0] for r in _compras(engine, ARS_P)} == {"ARS"}
    assert w.rows(engine, "SELECT count(*) FROM costo_si_backups WHERE item_id = :i", i=ARS_P) == [(1,)]
