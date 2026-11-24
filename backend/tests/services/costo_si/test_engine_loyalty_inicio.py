"""Costo SI engine: a brand loyalty also lowers the starting stock (handoffs/sell-in-costo-promedio-tarea.md L39, L40).

Owner L39: "sí, aplicaselo a todo el stock viejo"; L40: "aplicá a todos los anteriores". The stock in place when the
loyalty's period starts enters the average at the start cost x (1 - loyalty %), for every product, no exception.

The three products are the real prod rows of `costo_si_pasos` on 2026-11-24 (TP-Link, bono 98, 3.6 %): the start and
every purchase step with its stored inputs. The expected averages are moneda's replay in
handoffs/incidente-sell-in-costo-2026-11-24.md ("start with loyalty" column).
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from app.services.costo_si.engine import Compra, Inicio, SellIn, calcular

D = Decimal
LOYALTY = SellIn("bono", 98, D("3.6000"))


def _compra(fecha: date, ct: int, cantidad: int, neto: str, stock_antes: int, *compras: tuple) -> Compra:
    sell_ins = tuple(SellIn("compra", ref, D(pct)) for ref, pct in compras) + (LOYALTY,)
    return Compra(fecha, ct, cantidad, D(neto), sell_ins, stock_antes)


RE200 = (
    Inicio(date(2026, 10, 1), 1666, D("17.04000"), (LOYALTY,)),
    [
        _compra(date(2026, 10, 27), 935025, 200, "16.96401", 1184),
        _compra(date(2026, 11, 18), 950137, 200, "16.99804", 727, (28, "1.0000")),
    ],
)
DECO_E4 = (
    Inicio(date(2026, 10, 1), 173, D("25.12000"), (LOYALTY,)),
    [
        _compra(date(2026, 11, 6), 944606, 20, "25.63330", 140, (25, "2.5000")),
        _compra(date(2026, 11, 10), 944440, 75, "25.62936", 156),
    ],
)
TAPO_C500 = (
    Inicio(date(2026, 10, 1), 393, D("26.07360"), (LOYALTY,)),
    [
        _compra(date(2026, 10, 15), 919426, 150, "26.96784", 313),
        _compra(date(2026, 10, 29), 937717, 50, "26.91500", 300),
        _compra(date(2026, 11, 6), 944606, 200, "26.91500", 162, (25, "2.5000")),
        _compra(date(2026, 11, 10), 943885, 250, "26.88000", 286),
        _compra(date(2026, 11, 19), 950141, 55, "26.08514", 427, (29, "1.0000")),
        _compra(date(2026, 11, 19), 950142, 100, "26.08514", 482, (30, "1.0000")),
        _compra(date(2026, 11, 20), 952991, 250, "26.88000", 561),
    ],
)


@pytest.mark.parametrize(
    ("producto", "inicio_neto_neto", "final"),
    [
        pytest.param(RE200, D("16.42656"), D("16.37285"), id="RE200-item-22"),
        pytest.param(DECO_E4, D("24.21568"), D("24.36278"), id="DecoE4-item-454"),
        pytest.param(TAPO_C500, D("25.13495"), D("25.57632"), id="TapoC500-item-1249"),
    ],
)
def test_the_loyalty_lowers_the_starting_stock_of_the_real_tp_link_rows(
    producto: tuple, inicio_neto_neto: Decimal, final: Decimal
) -> None:
    """L39/L40: the start enters at its list cost x (1 - 3.6 %); every purchase averages from there."""
    inicio, compras = producto

    pasos = calcular(inicio, compras)

    (primero, *_), ultimo = pasos, pasos[-1]
    assert (primero.tipo, primero.costo_neto_usd, primero.sell_ins, primero.sell_in_pct) == (
        "inicio",
        inicio.costo_usd,
        (LOYALTY,),
        D("3.6000"),
    )
    assert (primero.costo_neto_neto_usd, primero.promedio_usd) == (inicio_neto_neto, inicio_neto_neto)
    assert ultimo.promedio_usd == final


def test_a_start_without_a_loyalty_keeps_its_list_cost() -> None:
    """Previous behavior: a start no loyalty covers enters at its list cost, with no sell in."""
    (inicio,) = calcular(Inicio(date(2026, 11, 1), 10, D("17.04")), [])

    assert (inicio.sell_ins, inicio.sell_in_pct, inicio.costo_neto_neto_usd, inicio.promedio_usd) == (
        (),
        D(0),
        D("17.04000"),
        D("17.04000"),
    )


def test_a_start_with_a_loyalty_but_no_list_cost_stays_unknown_never_a_zero() -> None:
    """§7: an unknown start cost is never taken as 0, with or without the loyalty: the average stays unknown until a
    purchase brings one."""
    inicio, compra = calcular(
        Inicio(date(2026, 10, 1), 5, None, (LOYALTY,)),
        [_compra(date(2026, 10, 2), 1, 10, "100", 5)],
    )

    assert (inicio.costo_neto_usd, inicio.costo_neto_neto_usd, inicio.promedio_usd) == (None, None, None)
    assert inicio.sell_ins == (LOYALTY,)
    assert compra.promedio_usd == D("96.40000")
