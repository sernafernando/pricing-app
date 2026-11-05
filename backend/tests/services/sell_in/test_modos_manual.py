"""The `manual` cost mode in the allocation (`fifo.asignar`), as a pure function (D6, handoffs
`sell-in-costos-propuesta.md`).

Owner: "otro permiso aparte para poder setear cantidad y costo a mano, por si un sell in quedó defazado al stock actual
y se quiere usar un costo a mano que sea el de reposición por ejemplo". From its `desde` the typed quantity REPLACES the
units left of the lots that count by then; each of its units carries the product's cost frozen at save time minus the
typed cost, signed (a higher typed cost raises the sale's cost, owner 2026-11-02). Purchases that count later queue
behind it, FIFO.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from app.services.sell_in.fifo import Consumo, Lote, Periodo, Venta, asignar, lote_manual

OCT1, OCT20, OCT25, OCT30 = (date(2026, 10, d) for d in (1, 20, 25, 30))
NOV1, NOV2, NOV5 = (date(2026, 11, d) for d in (1, 2, 5))
M = 7001  # the manual row's id
BLOQUE = -M  # its consumptions' source in the allocation


def _lote(item: int, cantidad: int, descuento: str, fecha: date = OCT1) -> Lote:
    return Lote(compra_item_id=item, compra_id=item, fecha=fecha, cantidad=cantidad, descuento_ars=Decimal(descuento))


def _venta(ref: int, unidades: int, fecha: date, objetivo: int | None = None) -> Venta:
    return Venta("fuera", ref, fecha, unidades, ("fuera", objetivo) if objetivo else None)


def _por_venta(consumos: list[Consumo]) -> dict[int, list[tuple[int, int, Decimal]]]:
    salida: dict[int, list[tuple[int, int, Decimal]]] = {}
    for c in consumos:
        salida.setdefault(c.venta_ref, []).append((c.compra_item_id, c.unidades, c.descuento_ars))
    return salida


DOS_LOTES = [_lote(1, 100, "1000"), _lote(2, 100, "800")]  # 100 at 10 and 100 at 8
# 30 units typed at 49 990 against a frozen cost of 50 000: 10 per unit.
MANUAL = lote_manual(M, OCT25, 30, Decimal("300"))
PERIODO = Periodo(OCT25, "manual", M)


def test_the_typed_quantity_replaces_the_units_left_at_its_value() -> None:
    ventas = [_venta(5, 50, OCT20), _venta(7, 40, OCT30)]

    consumos = _por_venta(asignar(DOS_LOTES + [MANUAL], ventas, [PERIODO]))

    assert consumos[5] == [(1, 50, Decimal("500.00"))]  # before `desde`: FIFO, untouched
    # 30 manual units; the other 10 find nothing: the 150 units the lots had left were replaced.
    assert consumos[7] == [(BLOQUE, 30, Decimal("300.00"))]


def test_a_typed_cost_above_the_frozen_one_is_a_surcharge() -> None:
    caro = lote_manual(M, OCT25, 30, Decimal("-60000"))  # typed 52 000 against 50 000 frozen

    consumos = _por_venta(asignar(DOS_LOTES + [caro], [_venta(7, 3, OCT30)], [PERIODO]))

    assert consumos[7] == [(BLOQUE, 3, Decimal("-6000.00"))]


def test_a_purchase_counting_later_queues_behind_the_manual_units() -> None:
    nueva = _lote(3, 20, "200", fecha=NOV1)

    consumos = _por_venta(asignar(DOS_LOTES + [MANUAL, nueva], [_venta(7, 40, NOV2)], [PERIODO]))

    assert consumos[7] == [(BLOQUE, 30, Decimal("300.00")), (3, 10, Decimal("100.00"))]


def test_a_lot_counting_on_the_manual_date_is_replaced_too() -> None:
    mismo_dia = _lote(3, 20, "200", fecha=OCT25)

    consumos = _por_venta(asignar(DOS_LOTES + [mismo_dia, MANUAL], [_venta(7, 40, OCT30)], [PERIODO]))

    assert consumos[7] == [(BLOQUE, 30, Decimal("300.00"))]


def test_a_returned_manual_unit_goes_back_to_the_block() -> None:
    ventas = [_venta(7, 30, OCT30), _venta(8, -5, NOV1, objetivo=7), _venta(9, 5, NOV2)]

    consumos = _por_venta(asignar(DOS_LOTES + [MANUAL], ventas, [PERIODO]))

    assert consumos[7] == [(BLOQUE, 25, Decimal("250.00"))]
    assert consumos[9] == [(BLOQUE, 5, Decimal("50.00"))]


def test_a_return_after_the_manual_date_never_brings_replaced_units_back() -> None:
    ventas = [_venta(5, 50, OCT20), _venta(6, -10, OCT30, objetivo=5), _venta(9, 40, NOV2)]

    consumos = _por_venta(asignar(DOS_LOTES + [MANUAL], ventas, [PERIODO]))

    assert consumos[5] == [(1, 40, Decimal("400.00"))]
    assert consumos[9] == [(BLOQUE, 30, Decimal("300.00"))]


def test_a_later_weighted_row_weighs_the_manual_units_with_the_later_lots() -> None:
    nueva = _lote(3, 30, "600", fecha=NOV1)  # 30 at 20
    periodos = [PERIODO, Periodo(NOV2, "ponderado")]

    consumos = _por_venta(asignar(DOS_LOTES + [MANUAL, nueva], [_venta(7, 60, NOV5)], periodos))

    # 30 at 10 plus 30 at 20: 60 at 15.
    assert sum(x[2] for x in consumos[7]) == Decimal("900.00")
    assert [(x[0], x[1]) for x in consumos[7]] == [(BLOQUE, 30), (3, 30)]


def test_a_second_manual_row_replaces_what_the_first_block_left() -> None:
    otro = lote_manual(M + 1, NOV1, 10, Decimal("50"))
    periodos = [PERIODO, Periodo(NOV1, "manual", M + 1)]
    ventas = [_venta(7, 20, OCT30), _venta(9, 15, NOV2)]

    consumos = _por_venta(asignar(DOS_LOTES + [MANUAL, otro], ventas, periodos))

    assert consumos[7] == [(BLOQUE, 20, Decimal("200.00"))]
    assert consumos[9] == [(-(M + 1), 10, Decimal("50.00"))]


def test_a_manual_row_superseded_on_its_own_day_replaces_nothing() -> None:
    periodos = [PERIODO, Periodo(OCT25, "fifo")]

    consumos = _por_venta(asignar(DOS_LOTES, [_venta(7, 40, OCT30)], periodos))

    assert consumos[7] == [(1, 40, Decimal("400.00"))]


@pytest.mark.parametrize(
    "lotes, periodos",
    [
        (DOS_LOTES, [PERIODO]),  # the period without its block
        (DOS_LOTES + [MANUAL], []),  # the block without its period
        (DOS_LOTES + [lote_manual(M, OCT30, 30, Decimal("300"))], [PERIODO]),  # on another day
    ],
)
def test_a_block_and_its_period_go_together(lotes, periodos) -> None:
    with pytest.raises(ValueError):
        asignar(lotes, [_venta(7, 40, NOV2)], periodos)
