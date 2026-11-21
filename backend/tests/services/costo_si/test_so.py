"""Sell out on top of costo SI (D1, plan sell-in-costo-si-t3-paralelo.md Q6/Q7; interface §2): the cost is costo SI
only; sell out adds to the profit, never comes off the cost; a sell out of base 'costo' is a % of costo SI.
Owner L12: "si de ganancia tenés 1000 y le agregás 10% tenés 1100 de ganancia"."""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.services.costo_si import so
from app.services.pricing_calculator import calcular_markup

D = Decimal


def test_ganancia_con_so_adds_the_sell_out_to_the_profit() -> None:
    """L12: 1000 of profit plus a 100 sell out is 1100 of profit."""
    assert so.ganancia_con_so(D("3000"), D("100"), D("2000")) == D("1100")
    assert so.ganancia_con_so(3000.0, 100.0, 2000.0) == 1100.0


def test_markup_con_so_is_limpio_plus_so_minus_costo_si_over_costo_si() -> None:
    """Q6: (limpio + SO - costo SI) / costo SI, a ratio like `calcular_markup`; with no sell out it is the markup."""
    assert so.markup_con_so(D("3000"), D("100"), D("2000")) == D("0.55")
    assert so.markup_con_so(3000.0, 0.0, 2000.0) == calcular_markup(3000.0, 2000.0)


@pytest.mark.parametrize("limpio, sell_out, costo", [(None, 1, 2), (3, None, 2), (3, 1, None), (3, 1, 0)])
def test_an_unknown_input_or_a_zero_cost_is_an_unknown_markup(limpio, sell_out, costo) -> None:
    assert so.markup_con_so(limpio, sell_out, costo) is None


@pytest.mark.parametrize("limpio, sell_out, costo", [(None, 1, 2), (3, None, 2), (3, 1, None)])
def test_an_unknown_input_is_an_unknown_profit(limpio, sell_out, costo) -> None:
    assert so.ganancia_con_so(limpio, sell_out, costo) is None


def test_a_cost_based_sell_out_is_a_percentage_of_costo_si() -> None:
    """Q7: base 'costo' = costo SI (one cost everywhere, L4.7); base 'precio_neto' unchanged."""
    assert so.base_sell_out(D("20000"), D("35000")) == {"costo": D("20000"), "precio_neto": D("35000")}
    assert so.base_sell_out(None, None) == {"costo": None, "precio_neto": None}
