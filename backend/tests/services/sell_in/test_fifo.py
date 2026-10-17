"""FIFO sell-in allocation (sell-in-sell-out T5, option A), as a pure function.

A purchase line's units are consumed by the product's sales in date order,
oldest purchase first; a sale only consumes purchases that count from on or
before its date. When every unit is used up, later sales get nothing (their
cost goes back to normal).
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from app.services.sell_in.fifo import Consumo, Lote, Venta, asignar


def _lote(item: int, cantidad: int, descuento: str, fecha: date = date(2026, 10, 1), compra: int = 1) -> Lote:
    return Lote(compra_item_id=item, compra_id=compra, fecha=fecha, cantidad=cantidad, descuento_ars=Decimal(descuento))


def _venta(ref: int, unidades: int, fecha: date = date(2026, 10, 16), canal: str = "fuera") -> Venta:
    return Venta(canal=canal, venta_ref=ref, fecha=fecha, unidades=unidades)


class TestAsignar:
    def test_a_sale_consumes_part_of_a_purchase_line(self) -> None:
        consumos = asignar([_lote(10, 10, "250000.00")], [_venta(590274, 3)])

        assert consumos == [
            Consumo(
                compra_item_id=10,
                canal="fuera",
                venta_ref=590274,
                fecha_venta=date(2026, 10, 16),
                unidades=3,
                descuento_ars=Decimal("75000.00"),
            )
        ]

    def test_once_the_units_are_used_up_later_sales_get_nothing(self) -> None:
        ventas = [_venta(1, 2, date(2026, 10, 2)), _venta(2, 2, date(2026, 10, 3)), _venta(3, 1, date(2026, 10, 4))]

        consumos = asignar([_lote(10, 3, "300.00")], ventas)

        assert [(c.venta_ref, c.unidades, c.descuento_ars) for c in consumos] == [
            (1, 2, Decimal("200.00")),
            (2, 1, Decimal("100.00")),
        ]

    def test_a_sale_crossing_two_purchases_takes_the_oldest_first(self) -> None:
        nueva = _lote(20, 5, "50.00", fecha=date(2026, 10, 5), compra=2)
        vieja = _lote(10, 2, "40.00", fecha=date(2026, 10, 1), compra=1)

        consumos = asignar([nueva, vieja], [_venta(7, 4, date(2026, 10, 6))])

        assert [(c.compra_item_id, c.unidades, c.descuento_ars) for c in consumos] == [
            (10, 2, Decimal("40.00")),
            (20, 2, Decimal("20.00")),
        ]

    def test_a_sale_never_consumes_a_purchase_that_counts_from_a_later_date(self) -> None:
        lote = _lote(10, 5, "50.00", fecha=date(2026, 10, 10))

        consumos = asignar([lote], [_venta(1, 2, date(2026, 10, 9)), _venta(2, 2, date(2026, 10, 10))])

        assert [(c.venta_ref, c.unidades) for c in consumos] == [(2, 2)]

    def test_sales_are_taken_in_date_order_whatever_order_they_come_in(self) -> None:
        ventas = [_venta(1, 1, date(2026, 10, 9)), _venta(2, 1, date(2026, 10, 3))]

        consumos = asignar([_lote(10, 1, "10.00")], ventas)

        assert [c.venta_ref for c in consumos] == [2]

    def test_same_day_ties_break_by_channel_then_reference(self) -> None:
        dia = date(2026, 10, 3)
        ventas = [
            _venta(5, 1, dia, "tn"),
            _venta(9, 1, dia, "fuera"),
            _venta(4, 1, dia, "ml"),
            _venta(3, 1, dia, "fuera"),
        ]

        consumos = asignar([_lote(10, 3, "30.00")], ventas)

        assert [(c.canal, c.venta_ref) for c in consumos] == [("fuera", 3), ("fuera", 9), ("ml", 4)]

    def test_returns_and_negative_lines_consume_nothing(self) -> None:
        consumos = asignar([_lote(10, 5, "50.00")], [_venta(1, -1), _venta(2, 0), _venta(3, 1)])

        assert [c.venta_ref for c in consumos] == [3]

    def test_the_consumed_discount_adds_up_to_the_line_exactly(self) -> None:
        ventas = [_venta(n, 1, date(2026, 10, n)) for n in range(1, 4)]

        consumos = asignar([_lote(10, 3, "100.00")], ventas)

        assert [c.descuento_ars for c in consumos] == [Decimal("33.33"), Decimal("33.34"), Decimal("33.33")]
        assert sum(c.descuento_ars for c in consumos) == Decimal("100.00")

    def test_it_is_deterministic(self) -> None:
        lotes = [_lote(10, 4, "40.00"), _lote(20, 4, "80.00", date(2026, 10, 2), compra=2)]
        ventas = [_venta(n, 3, date(2026, 10, 1 + n)) for n in range(4)]

        assert asignar(lotes, ventas) == asignar(list(reversed(lotes)), list(reversed(ventas)))

    def test_no_purchases_or_no_sales_is_no_consumption(self) -> None:
        assert asignar([], [_venta(1, 1)]) == []
        assert asignar([_lote(10, 1, "1.00")], []) == []


def _devolucion(ref: int, unidades: int, fecha: date, objetivo=None) -> Venta:
    return Venta(canal="fuera", venta_ref=ref, fecha=fecha, unidades=-unidades, objetivo=objetivo)


def _por_venta(consumos) -> dict:
    out: dict = {}
    for c in consumos:
        out[c.venta_ref] = out.get(c.venta_ref, 0) + c.unidades
    return out


class TestDevoluciones:
    """A return gives its units back to the pool: its target sale (resolved by
    the caller: ERP link, then unique customer candidate) loses them first, any
    excess comes from the most recent earlier sale still holding units, and the
    freed units go to LATER sales FIFO."""

    def test_the_target_sale_loses_the_returned_units_and_a_later_sale_takes_them(self) -> None:
        ventas = [
            _venta(1, 2, date(2026, 10, 2)),
            _venta(2, 2, date(2026, 10, 3)),  # before the return: stays without units
            _devolucion(3, 1, date(2026, 10, 4), objetivo=("fuera", 1)),
            _venta(4, 1, date(2026, 10, 5)),
        ]

        consumos = asignar([_lote(10, 2, "20.00")], ventas)

        assert _por_venta(consumos) == {1: 1, 4: 1}

    def test_the_excess_over_what_the_target_holds_comes_from_the_most_recent_holder(self) -> None:
        ventas = [
            _venta(1, 1, date(2026, 10, 2)),
            _venta(2, 2, date(2026, 10, 3)),
            _devolucion(3, 2, date(2026, 10, 4), objetivo=("fuera", 1)),
            _venta(4, 3, date(2026, 10, 5)),
        ]

        consumos = asignar([_lote(10, 3, "30.00")], ventas)

        assert _por_venta(consumos) == {2: 1, 4: 2}

    def test_without_a_target_the_most_recent_sale_still_holding_units_loses_them(self) -> None:
        ventas = [
            _venta(1, 1, date(2026, 10, 2)),
            _venta(2, 1, date(2026, 10, 3)),
            _venta(3, 1, date(2026, 10, 4)),  # holds nothing: the line is used up
            _devolucion(4, 1, date(2026, 10, 5)),
        ]

        consumos = asignar([_lote(10, 2, "20.00")], ventas)

        assert _por_venta(consumos) == {1: 1}

    def test_a_target_that_holds_nothing_sends_everything_to_the_fallback(self) -> None:
        ventas = [
            _venta(1, 1, date(2026, 9, 30)),  # before the purchase counts: holds nothing
            _venta(2, 1, date(2026, 10, 2)),
            _devolucion(3, 1, date(2026, 10, 4), objetivo=("fuera", 1)),
        ]

        consumos = asignar([_lote(10, 2, "20.00")], ventas)

        assert consumos == []

    def test_freed_units_go_back_to_their_own_purchase_line(self) -> None:
        vieja = _lote(10, 1, "100.00", date(2026, 10, 1), compra=1)
        nueva = _lote(20, 5, "50.00", date(2026, 10, 1), compra=2)
        ventas = [
            _venta(1, 2, date(2026, 10, 2)),  # 1 from vieja, 1 from nueva
            _devolucion(2, 1, date(2026, 10, 3), objetivo=("fuera", 1)),  # the last unit taken goes back first
            _venta(3, 5, date(2026, 10, 4)),
        ]

        consumos = asignar([vieja, nueva], ventas)

        assert sorted((c.venta_ref, c.compra_item_id, c.unidades) for c in consumos) == [(1, 10, 1), (3, 20, 5)]

    def test_a_return_before_any_consumption_frees_nothing(self) -> None:
        ventas = [_devolucion(1, 3, date(2026, 10, 2)), _venta(2, 1, date(2026, 10, 3))]

        assert _por_venta(asignar([_lote(10, 1, "10.00")], ventas)) == {2: 1}

    def test_money_stays_exact_after_returns(self) -> None:
        ventas = [
            _venta(1, 2, date(2026, 10, 2)),
            _devolucion(2, 1, date(2026, 10, 3), objetivo=("fuera", 1)),
            _venta(3, 1, date(2026, 10, 4)),
            _venta(4, 1, date(2026, 10, 5)),
        ]

        consumos = asignar([_lote(10, 3, "100.00")], ventas)

        assert sum(c.unidades for c in consumos) == 3
        assert sum(c.descuento_ars for c in consumos) == Decimal("100.00")

    def test_it_is_deterministic_with_returns(self) -> None:
        ventas = [
            _venta(1, 2, date(2026, 10, 2)),
            _venta(2, 2, date(2026, 10, 2)),
            _devolucion(3, 3, date(2026, 10, 3)),
            _venta(4, 2, date(2026, 10, 4)),
        ]
        lotes = [_lote(10, 3, "30.00"), _lote(20, 2, "40.00", compra=2)]

        assert asignar(lotes, ventas) == asignar(list(reversed(lotes)), list(reversed(ventas)))
