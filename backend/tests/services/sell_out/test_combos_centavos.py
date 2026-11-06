"""The combo split never loses or adds a cent (orchestrator, 2026-11-05: "3 equal components on a price of 100 give
33.33 each = 99.99. Make component amounts sum EXACTLY to the combo line"): each component's share of a combo line's
price and cost, units times unit value, adds up to the line's own amount, by largest remainder."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from app.services.combos.ventas import Parte, repartir
from app.services.sell_out.alcance import Venta, _de_componentes

TERCIO = Decimal(1) / 3
TRES_IGUALES = [Parte(1, Decimal(1), TERCIO), Parte(2, Decimal(1), TERCIO), Parte(3, Decimal(1), TERCIO)]


def test_three_equal_components_of_100_split_to_exactly_100() -> None:
    assert repartir(Decimal("100"), TRES_IGUALES) == [Decimal("33.34"), Decimal("33.33"), Decimal("33.33")]


def test_the_largest_remainder_takes_the_cent_not_the_first() -> None:
    partes = [Parte(1, Decimal(1), Decimal("0.3333")), Parte(2, Decimal(1), Decimal("0.6667"))]
    # 0.10 x 0.3333 = 0.033 and 0.10 x 0.6667 = 0.067: the second has the larger remainder.
    assert repartir(Decimal("0.10"), partes) == [Decimal("0.03"), Decimal("0.07")]


def test_a_combo_lines_price_and_cost_reach_the_components_without_losing_a_cent() -> None:
    combo = Venta("fuera", 7, 99, date(2026, 11, 5), 2, costo_unit=Decimal("50"), precio_unit=Decimal("50"))
    partes = [Parte(1, Decimal(1), TERCIO), Parte(2, Decimal(2), TERCIO), Parte(3, Decimal(1), TERCIO)]

    suyas = _de_componentes(combo, {99: partes}, {1, 2, 3})

    assert [v.unidades for v in suyas] == [2, 4, 2]
    for campo in ("precio_unit", "costo_unit"):
        montos = [(getattr(v, campo) * v.unidades).quantize(Decimal("0.01")) for v in suyas]
        assert montos == [Decimal("33.34"), Decimal("33.33"), Decimal("33.33")]
        assert sum(montos) == Decimal("100.00")
