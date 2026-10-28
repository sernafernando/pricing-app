"""`sell_in_out_ventas.sumar`: several sales' sell in / sell out as one (Métricas audit A7)."""

from __future__ import annotations

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
    assert sumar([None, MontosVenta(), MontosVenta(sell_in_ars=Decimal("2"))]) == MontosVenta(sell_in_ars=Decimal("2"))
    assert sumar([MontosVenta(), None]) == MontosVenta()
    assert sumar([None]) is None
    assert sumar([]) is None
