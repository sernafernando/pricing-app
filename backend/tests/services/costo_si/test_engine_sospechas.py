"""Costo SI engine: suspicious purchase prices are held out of the average (owner L29).

Spec: odd/tasks/costo-si-compras-sospechosas.md S1, S3. A purchase whose unit net price (in the product's currency,
before sell ins) is below 1/10 or above 10x the average in force right before it (or the list cost when there is no
average) does not enter the average until a reviewer accepts it. Invented numbers.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from app.services.costo_si.engine import Compra, Inicio, Lista, SellIn, calcular

D = Decimal


def _compra(dia: int, cantidad: int, neto: str, stock_antes: int, *pcts: str, mes: int = 11) -> Compra:
    return Compra(
        fecha=date(2026, mes, dia),
        ct_transaction=1000 + dia,
        cantidad=cantidad,
        costo_neto_usd=D(neto),
        sell_ins=tuple(SellIn("compra", i, D(p)) for i, p in enumerate(pcts, 1)),
        stock_antes=stock_antes,
    )


def _resumen(pasos):
    return [(p.tipo, p.costo_neto_usd, p.promedio_usd, p.referencia, p.fuente_ref) for p in pasos]


def test_a_purchase_below_a_tenth_of_the_average_is_excluded_and_the_average_carries_forward() -> None:
    """The case to pin, item 23 / invoice 00128199: ARS 15.14 at the invoice rate = USD 0.00971 vs 13.5355."""
    pasos = calcular(
        Inicio(date(2026, 10, 1), 100, D("13.5355")),
        [_compra(27, 312, "0.00971", 100, mes=10), _compra(28, 10, "14", 400, mes=10)],
    )

    assert _resumen(pasos) == [
        ("inicio", D("13.53550"), D("13.53550"), None, None),
        ("excluido", D("0.00971"), D("13.53550"), D("13.53550"), "costo_si"),
        ("compra", D("14.00000"), D("13.54683"), None, None),
    ]
    excluido = pasos[1]
    assert (excluido.ct_transaction, excluido.cantidad, excluido.stock_antes) == (1027, 312, 100)
    assert (excluido.stock_base, excluido.stock_despues) == (100, 412)


def test_a_purchase_above_ten_times_the_average_is_excluded() -> None:
    pasos = calcular(Inicio(date(2026, 11, 1), 50, D("2")), [_compra(2, 5, "20.01", 50)])

    assert _resumen(pasos)[1] == ("excluido", D("20.01000"), D("2.00000"), D("2.00000"), "costo_si")


def test_exactly_a_tenth_and_exactly_ten_times_still_enter_the_average() -> None:
    pasos = calcular(
        Inicio(date(2026, 11, 1), 10, D("10")),
        [_compra(2, 10, "1", 10), _compra(3, 10, "55", 0)],
    )

    assert [(p.tipo, p.promedio_usd, p.referencia) for p in pasos[1:]] == [
        ("compra", D("5.50000"), None),
        ("compra", D("55.00000"), None),  # 55 = 10 x 5.5; stock 0: the average restarts at it
    ]


def test_an_accepted_purchase_enters_the_average_and_keeps_its_reference() -> None:
    pasos = calcular(
        Inicio(date(2026, 10, 1), 100, D("13.5355")),
        [_compra(27, 312, "0.00971", 100, mes=10)],
        aceptadas=frozenset({1027}),
    )

    assert _resumen(pasos)[1] == ("compra", D("0.00971"), D("3.29267"), D("13.53550"), "costo_si")


def test_without_any_reference_the_purchase_is_not_checked() -> None:
    pasos = calcular(Inicio(date(2026, 11, 1), 0, None), [_compra(2, 10, "0.01", 0)])

    assert _resumen(pasos)[1] == ("compra", D("0.01000"), D("0.01000"), None, None)


def test_without_an_average_the_list_cost_on_the_invoice_date_is_the_reference() -> None:
    """No average yet (no list cost at the start): the list cost in force on the invoice date is the reference, and an
    excluded purchase is valued at it (the product must not stay without a cost)."""
    compra = Compra(
        fecha=date(2026, 11, 5),
        ct_transaction=77,
        cantidad=10,
        costo_neto_usd=D("0.5"),
        sell_ins=(),
        stock_antes=0,
        referencia_lista=D("12"),
    )

    pasos = calcular(Inicio(date(2026, 11, 1), 0, None), [compra])

    assert _resumen(pasos)[1] == ("excluido", D("0.50000"), D("12.00000"), D("12.00000"), "lista")


def test_the_list_cost_reference_is_ignored_once_there_is_an_average() -> None:
    compra = Compra(date(2026, 11, 5), 77, 10, D("0.5"), (), 10, referencia_lista=D("0.6"))

    pasos = calcular(Inicio(date(2026, 11, 1), 10, D("8")), [compra])

    assert _resumen(pasos)[1] == ("excluido", D("0.50000"), D("8.00000"), D("8.00000"), "costo_si")


def test_after_a_stock_restart_the_previous_average_is_still_the_reference() -> None:
    """Stock 0 or less restarts the average at the purchase (S9), but "right before" it the average was 10."""
    pasos = calcular(Inicio(date(2026, 11, 1), 10, D("10")), [_compra(2, 10, "0.5", -3)])

    assert _resumen(pasos)[1] == ("excluido", D("0.50000"), D("10.00000"), D("10.00000"), "costo_si")


def test_the_check_uses_the_net_before_sell_ins_and_a_list_reanchor_of_the_same_day() -> None:
    """The price checked is the net (sell ins are discounts on a real price); a re-anchor in force from 00:00 of the
    invoice day (L23) is the average right before the purchase."""
    pasos = calcular(
        Inicio(date(2026, 11, 1), 10, D("100")),
        [_compra(5, 10, "9", 10, "50")],
        [Lista(date(2026, 11, 5), D("8"), 10)],
    )

    assert [(p.tipo, p.promedio_usd, p.referencia) for p in pasos] == [
        ("inicio", D("100.00000"), None),
        ("lista", D("8.00000"), None),
        ("compra", D("6.25000"), None),  # 9 vs 8 is not suspicious; net-net 4.5 averages in
    ]
