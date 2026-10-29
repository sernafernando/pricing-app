"""Overlapping sell-in bonuses and their `acumulable` flag (sell-in-sell-out T27b, S36).

Owner, on how the system tells which overlapping bonuses must count twice: "agregaselo". Same meaning as sell
out's `acumulable` (`sell_out.asignacion`): bonuses on the same product and dates stack unless one of them is not
acumulable; then the one with the lower id takes precedence and the other takes only the units no bonus with
precedence over it took. For invoice bonuses the units are the operation's invoiced units of each product (what
the generated purchase holds); for % of cost bonuses, each sale's units. The rules already in place hold: a cost
bonus never takes a unit invoice-based sell in took, and a unit's cost bonuses never pass its cost.

Postgres only, in a throwaway schema (`_bono_world`)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Iterator

import pytest
from sqlalchemy import Engine
from sqlalchemy.orm import sessionmaker

from app.services.sell_in import bonos, bonos_costo
from app.services.sell_in.costing import get_costing
from tests.services.sell_in import _bono_world as b
from tests.services.sell_in import _world as w

D = date


@pytest.fixture(scope="module")
def engine() -> Iterator[Engine]:
    with b.world("sell_in_bonos_acum") as engine:
        yield engine


@pytest.fixture(autouse=True)
def _clean(engine: Engine) -> Iterator[None]:
    yield
    b.clean(engine)


def _reconciliar(engine: Engine, **kwargs) -> bonos.ReconcileResult:
    with sessionmaker(bind=engine)() as db:
        result = bonos.reconciliar(db, **kwargs)
        db.commit()
    return result


def _exclusivo(engine: Engine, bono_id: int, **values) -> int:
    b.update_bono(engine, bono_id, acumulable=False, **values)
    return bono_id


def _unidades(engine: Engine, bono_id: int, pedido_id: int):
    """`(item_id, cantidad, monto_asignado)` of the ACTIVE purchase generated for (bonus, operation)."""
    activas = {(g[0], g[1]) for g in b.generadas(engine) if g[2] == "activa"}
    return b.items_de(engine, bono_id, pedido_id) if (bono_id, pedido_id) in activas else []


@pytest.mark.postgres
class TestFactura:
    def test_two_acumulable_bonuses_still_stack_on_every_invoiced_unit(self, engine: Engine) -> None:
        uno, otro = b.bono(engine, monto="1.00"), b.bono(engine, monto="3.00")
        pedido = b.pedido(engine, {2964: 4})

        _reconciliar(engine, pedido_ids=[pedido])

        assert _unidades(engine, uno, pedido) == [(2964, 4, Decimal("4.00"))]
        assert _unidades(engine, otro, pedido) == [(2964, 4, Decimal("12.00"))]

    @pytest.mark.parametrize("cual", ["el_primero", "el_segundo"])
    def test_with_one_not_acumulable_the_lower_id_takes_the_units_and_the_other_gets_none(
        self, engine: Engine, cual: str
    ) -> None:
        uno, otro = b.bono(engine, monto="1.00"), b.bono(engine, monto="3.00")
        _exclusivo(engine, uno if cual == "el_primero" else otro)
        pedido = b.pedido(engine, {2964: 4})

        _reconciliar(engine, pedido_ids=[pedido])

        assert _unidades(engine, uno, pedido) == [(2964, 4, Decimal("4.00"))]
        assert _unidades(engine, otro, pedido) == []

    def test_a_not_acumulable_bonus_takes_the_units_a_capped_earlier_one_left(self, engine: Engine) -> None:
        uno = _exclusivo(engine, b.bono(engine, monto="1.00"), tope_unidades=3)
        otro = _exclusivo(engine, b.bono(engine, monto="3.00"))
        pedido = b.pedido(engine, {2964: 4})

        _reconciliar(engine, pedido_ids=[pedido])

        assert _unidades(engine, uno, pedido) == [(2964, 3, Decimal("3.00"))]
        assert _unidades(engine, otro, pedido) == [(2964, 1, Decimal("3.00"))]

    def test_three_bonuses_two_acumulable_share_units_and_no_unit_gets_the_exclusive_one_twice(
        self, engine: Engine
    ) -> None:
        # The first takes unit 0 (its cap); the exclusive second the units the first left (1-3); the third, acumulable,
        # only what the exclusive one left (0), which it shares with the first.
        uno = b.bono(engine, monto="1.00")
        b.update_bono(engine, uno, tope_unidades=1)
        dos = _exclusivo(engine, b.bono(engine, monto="2.00"))
        tres = b.bono(engine, monto="5.00")
        pedido = b.pedido(engine, {2964: 4})

        _reconciliar(engine, pedido_ids=[pedido])

        assert _unidades(engine, uno, pedido) == [(2964, 1, Decimal("1.00"))]
        assert _unidades(engine, dos, pedido) == [(2964, 3, Decimal("6.00"))]
        assert _unidades(engine, tres, pedido) == [(2964, 1, Decimal("5.00"))]

    def test_a_not_acumulable_bonus_cuts_only_the_products_and_operations_it_shares(self, engine: Engine) -> None:
        uno = _exclusivo(engine, b.bono(engine, monto="1.00"))
        otro = b.bono_alcance(engine, "modelos", modelos=(2270,), monto="3.00")
        compartido = b.pedido(engine, {2964: 2, 2270: 2})
        aparte = b.pedido(engine, {2270: 5}, fecha_factura=D(2026, 11, 2))
        b.update_bono(engine, otro, fecha_hasta=D(2026, 11, 30))

        _reconciliar(engine, pedido_ids=[compartido, aparte])

        assert _unidades(engine, uno, compartido) == [(2270, 2, Decimal("2.00")), (2964, 2, Decimal("2.00"))]
        assert _unidades(engine, otro, compartido) == []
        assert _unidades(engine, otro, aparte) == [(2270, 5, Decimal("15.00"))]

    def test_a_percentage_bonus_left_with_part_of_the_units_gets_that_share_of_the_line(self, engine: Engine) -> None:
        uno = _exclusivo(engine, b.bono(engine, monto="1.00"), tope_unidades=1)
        otro = b.bono_alcance(engine, "modelos", modelos=(2964,), tipo="porcentaje", porcentaje="10.0000")
        pedido = b.pedido(engine, {2964: 4})
        b.set_importe(engine, pedido, 2964, "401.00", "USD")

        _reconciliar(engine, pedido_ids=[pedido])

        assert _unidades(engine, uno, pedido) == [(2964, 1, Decimal("1.00"))]
        # 10 % of 401.00 is 40.10 for 4 units; 3 are left: 30.075, half up.
        assert _unidades(engine, otro, pedido) == [(2964, 3, Decimal("30.08"))]

    def test_voiding_the_exclusive_bonus_gives_the_other_its_units_back_when_only_it_is_asked(
        self, engine: Engine
    ) -> None:
        uno = _exclusivo(engine, b.bono(engine, monto="1.00"))
        otro = b.bono(engine, monto="3.00")
        pedido = b.pedido(engine, {2964: 4})
        _reconciliar(engine, pedido_ids=[pedido])
        assert _unidades(engine, otro, pedido) == []

        b.update_bono(engine, uno, estado="anulada")
        _reconciliar(engine, bono_ids=[uno])

        assert _unidades(engine, uno, pedido) == []
        assert _unidades(engine, otro, pedido) == [(2964, 4, Decimal("12.00"))]

    def test_making_the_exclusive_bonus_acumulable_restores_the_other_when_only_it_is_asked(
        self, engine: Engine
    ) -> None:
        uno = _exclusivo(engine, b.bono(engine, monto="1.00"))
        otro = b.bono(engine, monto="3.00")
        pedido = b.pedido(engine, {2964: 4})
        _reconciliar(engine, pedido_ids=[pedido])

        b.update_bono(engine, uno, acumulable=True)
        _reconciliar(engine, bono_ids=[uno])

        assert _unidades(engine, uno, pedido) == [(2964, 4, Decimal("4.00"))]
        assert _unidades(engine, otro, pedido) == [(2964, 4, Decimal("12.00"))]

    def test_when_the_exclusive_bonus_fails_on_an_operation_the_later_one_is_left_as_it_was_there(
        self, engine: Engine
    ) -> None:
        uno = _exclusivo(engine, b.bono(engine, monto="1.00"))  # USD: an ARS operation with no rate fails it
        otro = b.bono(engine, monto="3.00", moneda="ARS")
        sin_tc = b.pedido(engine, {2964: 4}, moneda="ARS", tipo_cambio=None)
        con_tc = b.pedido(engine, {2964: 2})

        result = _reconciliar(engine, pedido_ids=[sin_tc, con_tc])

        assert sorted(result.fallidas) == [(uno, sin_tc), (otro, sin_tc)]
        assert "no se acumula" in result.fallidas[(otro, sin_tc)]
        assert _unidades(engine, otro, sin_tc) == []
        assert _unidades(engine, uno, con_tc) == [(2964, 2, Decimal("2.00"))]
        assert _unidades(engine, otro, con_tc) == []

    def test_a_flag_change_queues_the_bonus(self, engine: Engine) -> None:
        bono = b.bono(engine)
        b.clear_queue(engine)

        b.update_bono(engine, bono, acumulable=False)

        assert b.queued(engine) == [("bono", bono)]


def _items(engine: Engine, *item_ids: int) -> None:
    with sessionmaker(bind=engine)() as db:
        bonos_costo.recalcular(db, item_ids)
        db.commit()


def _fifo(engine: Engine, *item_ids: int) -> None:
    with sessionmaker(bind=engine)() as db:
        get_costing().recompute(db, item_ids, isolate_failures=False)
        db.commit()


def _fuera(engine: Engine, item_id: int, unidades: int, dia: date, costo_unit: str = "1000.00") -> int:
    ref = w.venta(engine, "fuera", item_id, unidades, dia)
    w.update_venta(engine, "fuera", ref, costo_total=Decimal(costo_unit) * unidades)
    return ref


def _filas(engine: Engine):
    """`(bono_id, venta_ref, unidades, descuento_ars)`."""
    return [(r[0], r[2], r[5], r[6]) for r in b.bono_consumos(engine)]


@pytest.mark.postgres
class TestCosto:
    def test_with_one_not_acumulable_the_lower_id_takes_the_units_and_the_other_gets_none(self, engine: Engine) -> None:
        uno = b.bono_costo(engine, "3.00")
        _exclusivo(engine, b.bono_costo(engine, "2.00"))
        ref = _fuera(engine, 2964, 4, D(2026, 10, 5))

        _items(engine, 2964)

        assert _filas(engine) == [(uno, ref, 4, Decimal("120.00"))]

    def test_a_not_acumulable_bonus_takes_the_units_a_capped_earlier_one_left(self, engine: Engine) -> None:
        uno = _exclusivo(engine, b.bono_costo(engine, "3.00", tope_unidades=1))
        otro = _exclusivo(engine, b.bono_costo(engine, "2.00"))
        ref = _fuera(engine, 2964, 4, D(2026, 10, 5))

        _items(engine, 2964)

        assert _filas(engine) == [(uno, ref, 1, Decimal("30.00")), (otro, ref, 3, Decimal("60.00"))]

    def test_three_bonuses_two_acumulable_share_units_and_a_unit_never_passes_its_cost(self, engine: Engine) -> None:
        # 10 % capped to unit 0; the exclusive 20 % on units 1-3; the acumulable 95 % only on unit 0, which already
        # carries the first's 100.00 of its 1000.00 cost: 900.00 left, not the 950.00 asked.
        uno = b.bono_costo(engine, "10.00", tope_unidades=1)
        dos = _exclusivo(engine, b.bono_costo(engine, "20.00"))
        tres = b.bono_costo(engine, "95.00")
        ref = _fuera(engine, 2964, 4, D(2026, 10, 5))

        _items(engine, 2964)

        assert _filas(engine) == [
            (uno, ref, 1, Decimal("100.00")),
            (dos, ref, 3, Decimal("600.00")),
            (tres, ref, 1, Decimal("900.00")),
        ]

    def test_three_acumulable_bonuses_on_a_unit_still_stop_at_its_cost(self, engine: Engine) -> None:
        uno, dos, tres = b.bono_costo(engine, "60.00"), b.bono_costo(engine, "30.00"), b.bono_costo(engine, "20.00")
        ref = _fuera(engine, 2964, 2, D(2026, 10, 5))

        _items(engine, 2964)

        assert _filas(engine) == [
            (uno, ref, 2, Decimal("1200.00")),
            (dos, ref, 2, Decimal("600.00")),
            (tres, ref, 2, Decimal("200.00")),
        ]

    def test_units_invoice_sell_in_took_stay_out_for_an_exclusive_cost_bonus_too(self, engine: Engine) -> None:
        w.compra(engine, [(2964, 2, "300.00")], D(2026, 10, 1))  # a purchase covering 2 units
        uno = b.bono_costo(engine, "3.00", tope_unidades=1)
        otro = _exclusivo(engine, b.bono_costo(engine, "2.00"))
        ref = _fuera(engine, 2964, 5, D(2026, 10, 5))
        _fifo(engine, 2964)

        _items(engine, 2964)

        # Units 0-1 are the purchase's; the first takes unit 2 (its cap), the exclusive one units 3-4.
        assert _filas(engine) == [(uno, ref, 1, Decimal("30.00")), (otro, ref, 2, Decimal("40.00"))]
