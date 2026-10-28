"""A sell-in bonus's shared cap (sell-in-sell-out T24b). Owner, 2026-10-28: "muchos rebates aplican a un tope
conjunto por ejemplo, tablets y notebooks lenovo que aplica hasta 3000 USD entre los dos, o distintos modelos de
productos que aplican entre sí a tanto monto". The cap is allocated like sell out's (`sell_out.tope`): the bonus's
invoiced lines in invoice order, the line that crosses the cap keeps only the rest, later lines get nothing, and
every reconcile of the bonus recomputes it from scratch.

Postgres only, in a throwaway schema (`_bono_world`)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Iterator

import pytest
from sqlalchemy import Engine
from sqlalchemy.orm import sessionmaker

from app.services.sell_in import bonos
from tests.services.sell_in import _bono_world as b

D = date


@pytest.fixture(scope="module")
def engine() -> Iterator[Engine]:
    with b.world("sell_in_bonos_tope") as engine:
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


def _bono_con_tope(engine: Engine, *, monto: str = "10.00", **tope) -> int:
    bono = b.bono(engine, monto=monto)
    b.update_bono(engine, bono, **tope)
    return bono


def _estados(engine: Engine) -> dict:
    return {(g[0], g[1]): (g[2], g[4]) for g in b.generadas(engine)}


@pytest.mark.postgres
class TestMoneyCap:
    def test_the_operation_that_crosses_the_cap_gets_the_rest_and_later_ones_get_nothing(self, engine) -> None:
        bono = _bono_con_tope(engine, tope_monto="25.00")
        primero = b.pedido(engine, {2964: 2}, D(2026, 10, 5))
        segundo = b.pedido(engine, {2964: 2}, D(2026, 10, 10))
        tercero = b.pedido(engine, {2964: 2}, D(2026, 10, 12))

        result = _reconciliar(engine, bono_ids=[bono])

        assert (result.creadas, result.fallidas) == (2, {})
        assert b.items_de(engine, bono, primero) == [(2964, 2, Decimal("20.00"))]
        # 5.00 left: the units needed to cover it (one), its amount capped at what was left.
        assert b.items_de(engine, bono, segundo) == [(2964, 1, Decimal("5.00"))]
        assert b.items_de(engine, bono, tercero) == []
        assert _estados(engine)[(bono, segundo)] == ("activa", Decimal("5.00"))

    def test_the_cap_is_shared_by_every_product_of_the_bonus(self, engine) -> None:
        # Two products of the brand (like tablets and notebooks): 30.00 between both, whatever product.
        bono = _bono_con_tope(engine, tope_monto="30.00")
        pedido = b.pedido(engine, {2270: 2, 2964: 5}, D(2026, 10, 5))

        _reconciliar(engine, bono_ids=[bono])

        # Inside an operation the lines go by item: 2270 takes 20.00, 2964 the 10.00 left.
        assert b.items_de(engine, bono, pedido) == [(2270, 2, Decimal("20.00")), (2964, 1, Decimal("10.00"))]

    def test_per_model_amounts_stay_under_the_shared_cap(self, engine) -> None:
        bono = b.bono_alcance(engine, "modelos", modelos=(2964, 2270), monto="2.00")
        b.valor_de_modelo(engine, bono, 2964, monto="7.00")
        b.update_bono(engine, bono, tope_monto="20.00")
        primero = b.pedido(engine, {2270: 3, 2964: 1}, D(2026, 10, 5))  # 6.00 + 7.00
        segundo = b.pedido(engine, {2964: 3}, D(2026, 10, 6))  # 7.00 left: one unit

        _reconciliar(engine, bono_ids=[bono])

        assert b.items_de(engine, bono, primero) == [(2270, 3, Decimal("6.00")), (2964, 1, Decimal("7.00"))]
        assert b.items_de(engine, bono, segundo) == [(2964, 1, Decimal("7.00"))]

    def test_a_percentage_bonus_keeps_each_whole_lines_exact_amount(self, engine) -> None:
        bono = b.bono(engine)
        b.update_bono(engine, bono, tipo="porcentaje", monto_unit=None, porcentaje="5", tope_monto="6.00")
        primero = b.pedido(engine, {2964: 3}, D(2026, 10, 5))
        b.set_importe(engine, primero, 2964, "100.10", "USD")  # 5% = 5.005 -> 5.01
        segundo = b.pedido(engine, {2964: 3}, D(2026, 10, 6))
        b.set_importe(engine, segundo, 2964, "60.00", "USD")  # 1.00 per unit; 0.99 left

        _reconciliar(engine, bono_ids=[bono])

        assert b.items_de(engine, bono, primero) == [(2964, 3, Decimal("5.01"))]
        assert b.items_de(engine, bono, segundo) == [(2964, 1, Decimal("0.99"))]


@pytest.mark.postgres
class TestUnitCap:
    def test_the_line_that_reaches_the_unit_cap_keeps_the_units_left(self, engine) -> None:
        bono = _bono_con_tope(engine, monto="2.00", tope_unidades=5)
        primero = b.pedido(engine, {2964: 3}, D(2026, 10, 5))
        segundo = b.pedido(engine, {2964: 4}, D(2026, 10, 6))

        _reconciliar(engine, bono_ids=[bono])

        assert b.items_de(engine, bono, primero) == [(2964, 3, Decimal("6.00"))]
        assert b.items_de(engine, bono, segundo) == [(2964, 2, Decimal("4.00"))]

    def test_with_both_caps_the_first_one_reached_wins(self, engine) -> None:
        bono = _bono_con_tope(engine, monto="10.00", tope_unidades=10, tope_monto="15.00")
        pedido = b.pedido(engine, {2964: 4}, D(2026, 10, 5))

        _reconciliar(engine, bono_ids=[bono])

        assert b.items_de(engine, bono, pedido) == [(2964, 2, Decimal("15.00"))]


@pytest.mark.postgres
class TestRecompute:
    def test_invoice_order_decides_not_load_order_and_a_call_for_one_operation_recomputes_the_bonus(
        self, engine
    ) -> None:
        bono = _bono_con_tope(engine, tope_unidades=2)
        tarde = b.pedido(engine, {2964: 2}, D(2026, 10, 20))
        _reconciliar(engine, bono_ids=[bono])
        assert b.items_de(engine, bono, tarde) == [(2964, 2, Decimal("20.00"))]

        # Loaded later, invoiced earlier: it takes the cap, and the later invoice loses its purchase.
        temprano = b.pedido(engine, {2964: 2}, D(2026, 10, 3))
        result = _reconciliar(engine, pedido_ids=[temprano])

        assert (result.creadas, result.anuladas) == (1, 1)
        assert b.items_de(engine, bono, temprano) == [(2964, 2, Decimal("20.00"))]
        assert _estados(engine)[(bono, tarde)][0] == "anulada"

    def test_a_cancelled_operation_frees_the_cap_for_the_next_one(self, engine) -> None:
        bono = _bono_con_tope(engine, tope_unidades=2)
        primero = b.pedido(engine, {2964: 2}, D(2026, 10, 5))
        segundo = b.pedido(engine, {2964: 2}, D(2026, 10, 6))
        _reconciliar(engine, bono_ids=[bono])
        assert b.items_de(engine, bono, segundo) == []

        b.update_pedido(engine, primero, estado="cancelado")
        _reconciliar(engine, pedido_ids=[primero])

        assert _estados(engine)[(bono, primero)][0] == "anulada"
        assert b.items_de(engine, bono, segundo) == [(2964, 2, Decimal("20.00"))]

    def test_a_credit_note_frees_units_for_later_operations(self, engine) -> None:
        bono = _bono_con_tope(engine, tope_unidades=3)
        primero = b.pedido(engine, {2964: 3}, D(2026, 10, 5))
        segundo = b.pedido(engine, {2964: 3}, D(2026, 10, 6))
        _reconciliar(engine, bono_ids=[bono])

        b.set_lineas(engine, primero, {2964: 1})  # invoiced 3, credit note of 2
        _reconciliar(engine, pedido_ids=[primero])

        assert b.items_de(engine, bono, primero) == [(2964, 1, Decimal("10.00"))]
        assert b.items_de(engine, bono, segundo) == [(2964, 2, Decimal("20.00"))]

    def test_raising_or_removing_the_cap_pays_the_rest(self, engine) -> None:
        bono = _bono_con_tope(engine, tope_unidades=1)
        pedido = b.pedido(engine, {2964: 3}, D(2026, 10, 5))
        _reconciliar(engine, bono_ids=[bono])
        assert b.items_de(engine, bono, pedido) == [(2964, 1, Decimal("10.00"))]

        b.update_bono(engine, bono, tope_unidades=None)
        result = _reconciliar(engine, bono_ids=[bono])

        assert result.actualizadas == 1
        assert b.items_de(engine, bono, pedido) == [(2964, 3, Decimal("30.00"))]

    def test_a_rerun_writes_nothing(self, engine) -> None:
        bono = _bono_con_tope(engine, tope_monto="25.00")
        b.pedido(engine, {2964: 2}, D(2026, 10, 5))
        b.pedido(engine, {2964: 2}, D(2026, 10, 10))
        _reconciliar(engine, bono_ids=[bono])

        result = _reconciliar(engine, bono_ids=[bono])

        assert (result.creadas, result.actualizadas, result.anuladas) == (0, 0, 0)

    def test_a_bonus_without_a_cap_is_unchanged(self, engine) -> None:
        bono = b.bono(engine, monto="10.00")
        primero = b.pedido(engine, {2964: 2}, D(2026, 10, 5))
        segundo = b.pedido(engine, {2964: 2}, D(2026, 10, 10))

        _reconciliar(engine, pedido_ids=[segundo])

        assert b.items_de(engine, bono, segundo) == [(2964, 2, Decimal("20.00"))]
        assert b.items_de(engine, bono, primero) == []  # not asked for, not widened


@pytest.mark.postgres
class TestFailure:
    def test_a_failing_earlier_operation_leaves_the_later_ones_as_they_were(self, engine) -> None:
        bono = _bono_con_tope(engine, tope_unidades=4)
        # An ARS operation with no rate of its own and no BNA rate: a USD bonus cannot price it.
        sin_tasa = b.pedido(engine, {2964: 2}, D(2026, 10, 5), moneda="ARS", tipo_cambio=None)
        despues = b.pedido(engine, {2964: 2}, D(2026, 10, 6))
        antes = b.pedido(engine, {2964: 1}, D(2026, 10, 4))

        result = _reconciliar(engine, bono_ids=[bono])

        assert set(result.fallidas) == {(bono, sin_tasa), (bono, despues)}
        assert "tope" in result.fallidas[(bono, despues)]
        assert b.items_de(engine, bono, antes) == [(2964, 1, Decimal("10.00"))]
        assert b.items_de(engine, bono, despues) == []
