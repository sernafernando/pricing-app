"""Costo SI engine (sell-in-costo-si T2): the moving weighted average per product, pure (no database).

Spec: handoffs/sell-in-costo-si-feature.md S1, S5, S9, S10. Invented numbers except Alejandro's L1 table, which is the
owner's own example and must be reproduced exactly.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from app.services.costo_si.engine import Compra, Inicio, SellIn, calcular

D = Decimal


def _compra(dia: int, cantidad: int, neto: str, stock_antes: int, *pcts: str) -> Compra:
    return Compra(
        fecha=date(2026, 11, dia),
        ct_transaction=1000 + dia,
        cantidad=cantidad,
        costo_neto_usd=D(neto),
        sell_ins=tuple(SellIn("compra", i, D(p)) for i, p in enumerate(pcts, 1)),
        stock_antes=stock_antes,
    )


def test_alejandros_l1_table_is_reproduced_exactly() -> None:
    """S1: 200 at 25; A +100 at 22 -2.5 %; a sale of 20 (stock 280); B +50 at 20 -5 %; C +50 at 21 -2 %."""
    pasos = calcular(
        Inicio(fecha=date(2026, 11, 1), stock=200, costo_usd=D("25")),
        [
            _compra(2, 100, "22", 200, "2.5"),
            _compra(3, 50, "20", 280, "5"),
            _compra(4, 50, "21", 330, "2"),
        ],
    )

    assert [(p.tipo, p.stock_despues, p.costo_neto_neto_usd, p.promedio_usd) for p in pasos] == [
        ("inicio", 200, D("25.00000"), D("25.00000")),
        ("compra", 300, D("21.45000"), D("23.81667")),
        ("compra", 330, D("19.00000"), D("23.08687")),
        ("compra", 380, D("20.58000"), D("22.75702")),
    ]
    # S10: stored with 5 decimals (shown with 2 by the readers).
    assert all(p.promedio_usd.as_tuple().exponent == -5 for p in pasos)


def test_a_sale_changes_only_the_stock_never_the_average() -> None:
    """S1/S12: between purchases the average stays; only the stock read before the next purchase moved."""
    pasos = calcular(Inicio(date(2026, 11, 1), 200, D("25")), [_compra(2, 100, "22", 200, "2.5")])

    assert pasos[-1].promedio_usd == D("23.81667")
    assert pasos[-1].stock_antes == 200


def test_every_sell_in_is_a_percent_of_the_same_net_and_they_add_up() -> None:
    """S5 (L5): 100 x (1 - 0.05 - 0.036) = 91.40, not 100 x 0.95 x 0.964."""
    (_, paso) = calcular(Inicio(date(2026, 11, 1), 0, D("80")), [_compra(2, 10, "100", 0, "5", "3.6")])

    assert paso.sell_in_pct == D("8.6")
    assert paso.costo_neto_neto_usd == D("91.40000")
    assert [s.porcentaje for s in paso.sell_ins] == [D("5"), D("3.6")]


def test_a_purchase_without_sell_in_still_enters_the_average() -> None:
    """S4 (L2.3): "sí entran, porque si mañana entra una factura tiene que tener el promedio"."""
    (_, paso) = calcular(Inicio(date(2026, 11, 1), 100, D("10")), [_compra(2, 100, "20", 100)])

    assert paso.costo_neto_neto_usd == D("20.00000")
    assert paso.promedio_usd == D("15.00000")


def test_negative_stock_at_a_purchase_counts_as_zero_and_restarts_the_average() -> None:
    """S9 (L4.6): "Si está negativo, calculalo como 0, arrancaría con el stock nuevo directamente"."""
    (_, negativo) = calcular(Inicio(date(2026, 11, 1), 50, D("30")), [_compra(2, 40, "20", -7, "10")])

    assert negativo.stock_antes == -7  # what the source said, kept for the breakdown
    assert negativo.stock_base == 0
    assert negativo.stock_despues == 40
    assert negativo.promedio_usd == D("18.00000")


def test_zero_stock_at_a_purchase_restarts_too() -> None:
    (_, cero) = calcular(Inicio(date(2026, 11, 1), 50, D("30")), [_compra(2, 10, "12", 0)])

    assert cero.promedio_usd == D("12.00000")


def test_a_start_without_a_historical_cost_starts_at_the_first_purchase() -> None:
    """No list cost before the start: there is nothing to weigh the old stock with, so the first purchase sets it."""
    pasos = calcular(Inicio(date(2026, 11, 1), 30, None), [_compra(2, 10, "12", 30)])

    assert pasos[0].promedio_usd is None
    assert pasos[1].promedio_usd == D("12.00000")
