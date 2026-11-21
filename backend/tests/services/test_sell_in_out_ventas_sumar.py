"""`sell_in_out_ventas.sumar`: several sales' sell out as one (Métricas audit A7; no sell in since Costo SI T3 D1)."""

from __future__ import annotations

import dataclasses
from decimal import Decimal

from app.services.sell_in_out_ventas import MontosVenta, sumar


def test_an_estimated_known_sell_out_sums_and_stays_estimated():
    total = sumar(
        [
            MontosVenta(sell_out_ars=Decimal("10"), sell_out_estimado=True),
            MontosVenta(sell_out_ars=Decimal("5"), sell_out_estimado=False),
        ]
    )

    assert total == MontosVenta(sell_out_ars=Decimal("15"), sell_out_estimado=True)


def test_an_unknown_sell_out_makes_the_total_unknown():
    total = sumar(
        [MontosVenta(sell_out_ars=Decimal("5"), sell_out_estimado=False), MontosVenta(sell_out_estimado=True)]
    )

    assert total == MontosVenta(sell_out_ars=None, sell_out_estimado=True)


def test_parts_without_rows_add_nothing_and_none_at_all_is_none():
    assert sumar([None, MontosVenta(), MontosVenta(sell_out_ars=Decimal("2"), sell_out_estimado=False)]) == MontosVenta(
        sell_out_ars=Decimal("2"), sell_out_estimado=False
    )
    assert sumar([MontosVenta(), None]) == MontosVenta()
    assert sumar([None]) is None
    assert sumar([]) is None


def test_a_sale_amount_has_no_sell_in():
    # D1: the frozen cost is costo SI; the sale carries its sell out only.
    assert {f.name for f in dataclasses.fields(MontosVenta)} == {"sell_out_ars", "sell_out_estimado"}
