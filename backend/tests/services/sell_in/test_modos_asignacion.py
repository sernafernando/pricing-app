"""Sell-in cost modes in the allocation (`fifo.asignar` with dated `Periodo`s), as a pure function.

Owner: "si compro 100 unidades a 10 y 100 a 8, ponderar eso en 200 a 9" (`ponderado`) and "que el costo sea el del
último también combinando las cantidades" (`ultimo`). A sale's units still come out of the lots in FIFO order (each lot
keeps its consumed and left units); only the money a unit carries follows the mode governing the sale's date. Sales
before a mode's `desde` keep exactly what FIFO gave them.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from app.services.sell_in.fifo import Consumo, Lote, Periodo, Venta, asignar

OCT1, OCT15, OCT20, OCT25, OCT30 = (date(2026, 10, d) for d in (1, 15, 20, 25, 30))
NOV2 = date(2026, 11, 2)


def _lote(item: int, cantidad: int, descuento: str, fecha: date = OCT1) -> Lote:
    return Lote(compra_item_id=item, compra_id=item, fecha=fecha, cantidad=cantidad, descuento_ars=Decimal(descuento))


def _venta(ref: int, unidades: int, fecha: date) -> Venta:
    return Venta(canal="fuera", venta_ref=ref, fecha=fecha, unidades=unidades)


def _por_venta(consumos: list[Consumo]) -> dict[int, list[tuple[int, int, Decimal]]]:
    salida: dict[int, list[tuple[int, int, Decimal]]] = {}
    for c in consumos:
        salida.setdefault(c.venta_ref, []).append((c.compra_item_id, c.unidades, c.descuento_ars))
    return salida


DOS_LOTES = [_lote(1, 100, "1000"), _lote(2, 100, "800")]  # 100 at 10 and 100 at 8


def test_the_owners_example_100_at_10_and_100_at_8_weigh_200_at_9() -> None:
    consumos = asignar(DOS_LOTES, [_venta(7, 200, NOV2)], [Periodo(NOV2, "ponderado")])

    assert _por_venta(consumos) == {7: [(1, 100, Decimal("900.00")), (2, 100, Decimal("900.00"))]}


def test_without_modes_the_allocation_is_fifo() -> None:
    ventas = [_venta(7, 150, NOV2)]

    assert asignar(DOS_LOTES, ventas, []) == asignar(DOS_LOTES, ventas)
    assert _por_venta(asignar(DOS_LOTES, ventas)) == {7: [(1, 100, Decimal("1000.00")), (2, 50, Decimal("400.00"))]}


def test_sales_before_the_mode_keep_what_fifo_gave_them() -> None:
    ventas = [_venta(5, 50, OCT20), _venta(7, 50, NOV2)]

    fifo = _por_venta(asignar(DOS_LOTES, ventas))
    ponderado = _por_venta(asignar(DOS_LOTES, ventas, [Periodo(NOV2, "ponderado")]))

    assert ponderado[5] == fifo[5] == [(1, 50, Decimal("500.00"))]
    # Left at the mode's date: 50 of lot 1 (at 10) and 100 of lot 2 (at 8): 1300 over 150 units.
    assert ponderado[7] == [(1, 50, Decimal("433.33"))]


def test_a_lot_bought_later_joins_the_weighted_pool_and_reweighs_it() -> None:
    lotes = [_lote(1, 100, "1000"), _lote(2, 50, "200", fecha=OCT25)]
    ventas = [_venta(5, 50, OCT20), _venta(7, 100, OCT30)]

    consumos = _por_venta(asignar(lotes, ventas, [Periodo(OCT15, "ponderado")]))

    assert consumos[5] == [(1, 50, Decimal("500.00"))]
    # 500 still in the pool for 50 units, plus 200 for 50: 700 over 100 units.
    assert sum(x[2] for x in consumos[7]) == Decimal("700.00")
    assert [(x[0], x[1]) for x in consumos[7]] == [(1, 50), (2, 50)]


def test_last_price_values_every_unit_left_at_the_newest_lot() -> None:
    # 90 left at 10 plus a new lot of 10 at 8: 100 at 8 (800 handed out against the 980 the lots still hold).
    lotes = [_lote(1, 100, "1000"), _lote(2, 10, "80", fecha=OCT25)]
    ventas = [_venta(5, 10, OCT20), _venta(7, 100, OCT30)]

    consumos = _por_venta(asignar(lotes, ventas, [Periodo(OCT15, "ultimo")]))

    assert consumos[5] == [(1, 10, Decimal("100.00"))]  # before the new lot, the newest is lot 1 at 10
    assert sum(x[2] for x in consumos[7]) == Decimal("800.00")


def test_back_to_fifo_each_lot_left_carries_its_own_value_again() -> None:
    ventas = [_venta(5, 100, OCT20), _venta(7, 100, OCT30)]

    consumos = _por_venta(asignar(DOS_LOTES, ventas, [Periodo(OCT15, "ponderado"), Periodo(OCT25, "fifo")]))

    assert consumos == {5: [(1, 100, Decimal("900.00"))], 7: [(2, 100, Decimal("800.00"))]}


def test_two_modes_on_the_same_day_the_one_saved_last_governs() -> None:
    ventas = [_venta(7, 150, NOV2)]

    consumos = asignar(DOS_LOTES, ventas, [Periodo(NOV2, "ultimo"), Periodo(NOV2, "fifo")])

    assert consumos == asignar(DOS_LOTES, ventas)


def test_a_re_based_lot_hands_out_exactly_its_total_with_odd_cents() -> None:
    # 100.01 over 2 units: the first unit took 50.01 (cumulative rounding); the re-base must start from the 50.00 left,
    # not from the unrounded 50.005, or the lot hands out 100.02.
    lotes = [_lote(1, 2, "100.01")]
    ventas = [_venta(5, 1, OCT20), _venta(7, 1, OCT30)]

    consumos = _por_venta(asignar(lotes, ventas, [Periodo(OCT25, "fifo")]))

    assert consumos == {5: [(1, 1, Decimal("50.01"))], 7: [(1, 1, Decimal("50.00"))]}
