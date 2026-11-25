"""Costo SI: a brand bonus also lowers the stock on hand (handoffs/sell-in-costo-promedio-tarea.md L39-L41).

Owner L39: "sí, aplicaselo a todo el stock viejo"; L40: "aplicá a todos los anteriores"; L41: "toda aplicación que
sea por marca tiene que aplicar no solo los que se llaman loyalty, todo aplica igual". The stock on hand when a bonus
starts gets it at the cost in force, for every product and every shape (%, per unit, capped).

The three products are the real prod rows of `costo_si_pasos` on 2026-11-24 (TP-Link, bono 98, 3.6 %): the start and
every purchase step with its stored inputs. The expected averages are moneda's replay in
handoffs/incidente-sell-in-costo-2026-11-24.md ("start with loyalty" column).
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from app.services.costo_si.engine import Aplicacion, Compra, Inicio, SellIn, calcular
from app.services.costo_si.fuentes import CURRS, EN_MANO, Bono, Linea, aplicar_topes

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


# --- Owner L41 ("toda aplicación que sea por marca tiene que aplicar [...] todo aplica igual"): every brand bonus,
# any shape, lands on the stock on hand. Real prod rows of 2026-11-25 (incident sweep N1, T5 regressions R1/R2).


def _sobre_stock(bono: Bono, item_id: int, stock: int, costo: str, **valor: Decimal) -> SellIn:
    """What `bono`'s walk gives `item_id`'s stock on hand (USD product, no invoice in the walk)."""
    mano = Linea(EN_MANO, item_id, stock, D(costo), CURRS["USD"], valor.get("pct"), valor.get("unit"), D(21), None)
    _, en_mano = aplicar_topes(bono, [mano])
    return en_mano[item_id]


def test_tactical_41_reaches_the_corcisa_units_on_hand_up_to_its_cap() -> None:
    """Tactical 41 / bono 65 (Logitech item 1451): 6.88 % capped at 400 units, from 2026-11-12. Corcisa invoice
    00091704 (400 u) is dated 11-11, so today it gets nothing and the product sits at list 15.55. On 11-12 there are
    438 on hand: 400 get the 6.88 %, i.e. 6.2831 % of the stock, and the costo SI falls to 14.57298."""
    bono = Bono(65, D("6.8800"), date(2026, 11, 12), date(2027, 7, 30), tope_unidades=400)
    sell_in = _sobre_stock(bono, 1451, 438, "15.55", pct=D("6.8800"))

    (inicio,) = calcular(Inicio(date(2026, 11, 12), 438, D("15.55"), (sell_in,)), [])

    assert sell_in == SellIn("bono", 65, D("6.2831"))
    assert (inicio.sell_in_pct, inicio.promedio_usd) == (D("6.2831"), D("14.57298"))


def test_bono_99_xerox_remanente_takes_its_amount_off_the_units_on_hand() -> None:
    """Tactical 63 / bono 99 (XEROX 3020 remanente, item 1004): USD 6.50 per unit from 2026-11-01, no invoice since
    September, so today it applies to nothing. The 145 units on hand at 83.00 get 6.50 / 83 = 7.8313 %."""
    bono = Bono(99, None, date(2026, 11, 1), date(2026, 12, 31), D("6.50"), "USD")
    sell_in = _sobre_stock(bono, 1004, 145, "83.00", unit=D("6.50"))

    (inicio,) = calcular(Inicio(date(2026, 11, 1), 145, D("83.00"), (sell_in,)), [])

    assert sell_in == SellIn("bono", 99, D(0), D("6.50"))
    assert (inicio.sell_ins, inicio.promedio_usd) == ((SellIn("bono", 99, D("7.8313")),), D("76.50002"))


def test_a_bonus_starting_after_the_start_is_a_sell_in_step_on_the_average_in_force() -> None:
    """Tactical 54 / bono 87 shape (HP BPS, USD 170 per unit from 11-17, its invoice dated 11-03): the 5 units on hand
    on 11-17 get it off the average in force then (1000 -> 830), and the next purchase averages from there."""
    compra = Compra(date(2026, 11, 3), 1, 5, D("1000"), (), 0)
    despues = Compra(date(2026, 11, 20), 2, 5, D("1000"), (), 5)
    aplicacion = Aplicacion(date(2026, 11, 17), 5, (SellIn("bono", 87, D(0), D("170")),))

    pasos = calcular(Inicio(date(2026, 11, 1), 0, D("1000")), [compra, despues], aplicaciones=[aplicacion])

    assert [(p.tipo, p.fecha, p.costo_neto_usd, p.sell_in_pct, p.promedio_usd) for p in pasos] == [
        ("inicio", date(2026, 11, 1), D("1000.00000"), D(0), D("1000.00000")),
        ("compra", date(2026, 11, 3), D("1000.00000"), D(0), D("1000.00000")),
        ("sell_in", date(2026, 11, 17), D("1000.00000"), D("17.0000"), D("830.00000")),
        ("compra", date(2026, 11, 20), D("1000.00000"), D(0), D("915.00000")),
    ]
