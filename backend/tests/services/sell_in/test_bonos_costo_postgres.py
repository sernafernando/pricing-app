"""A sell-in bonus on a % of the sale's cost, with no invoice (sell-in-sell-out T25b, S30, S33).

Owner: "agregá el de sell in, es para operaciones viejas que no tienen la factura cargada". A `base = 'costo_venta'`
bonus discounts, on every sale of its scope dated in its range, its % of the cost recorded on the sale without VAT
(ML `mcosto / qty`, fuera/TN `costo_total / units`); with `incluye_iva` the % is first divided by (1 + the product's
VAT rate) ("el tilde tendría que restar el iva, a la cuenta siempre debería llegar 2,71"). It takes only the units
invoice-based sell in left (rule 5, owner "ok"), stacks with other cost bonuses up to the unit cost, and its optional
cap goes in sale order. Rows live in `sell_in_bono_consumos`, written as a difference.

Postgres only, in a throwaway schema (`_bono_world`)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Iterator

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.orm import sessionmaker

from app.services.sell_in import bonos, bonos_costo
from app.services.sell_in.costing import get_costing
from tests.services.sell_in import _bono_world as b
from tests.services.sell_in import _world as w

D = date


@pytest.fixture(scope="module")
def engine() -> Iterator[Engine]:
    with b.world("sell_in_bonos_costo") as engine:
        yield engine


@pytest.fixture(autouse=True)
def _clean(engine: Engine) -> Iterator[None]:
    yield
    b.clean(engine)


def _items(engine: Engine, *item_ids: int) -> bonos_costo.CostoResult:
    with sessionmaker(bind=engine)() as db:
        result = bonos_costo.recalcular(db, item_ids)
        db.commit()
    return result


def _bonos(engine: Engine, *bono_ids: int) -> bonos_costo.CostoResult:
    with sessionmaker(bind=engine)() as db:
        result = bonos_costo.recalcular(db, bono_ids=bono_ids)
        db.commit()
    return result


def _fifo(engine: Engine, *item_ids: int) -> None:
    with sessionmaker(bind=engine)() as db:
        get_costing().recompute(db, item_ids, isolate_failures=False)
        db.commit()


def _fuera(engine: Engine, item_id: int, unidades: int, dia: date, costo_unit: str = "1000.00", **kw) -> int:
    """A fuera sale with its recorded cost (`costo_total` = units x `costo_unit`, without VAT)."""
    ref = w.venta(engine, "fuera", item_id, unidades, dia, **kw)
    if costo_unit is not None:
        w.update_venta(engine, "fuera", ref, costo_total=Decimal(costo_unit) * unidades)
    return ref


def _filas(engine: Engine):
    """`(bono_id, venta_ref, item_id, unidades, descuento_ars)`."""
    return [(r[0], r[2], r[3], r[5], r[6]) for r in b.bono_consumos(engine)]


@pytest.mark.postgres
class TestBase:
    def test_only_sales_dated_inside_the_range_get_the_discount(self, engine: Engine) -> None:
        bono = b.bono_costo(engine, "3.00")
        _fuera(engine, 2964, 2, D(2026, 9, 30))
        dentro = _fuera(engine, 2964, 2, D(2026, 10, 5))
        _fuera(engine, 2964, 2, D(2026, 11, 1))

        _items(engine, 2964)

        # 3 % of 1000.00 per unit, two units.
        assert _filas(engine) == [(bono, dentro, 2964, 2, Decimal("60.00"))]

    def test_the_base_is_the_ml_cost_per_unit_and_a_sale_with_unknown_cost_is_pending(self, engine: Engine) -> None:
        bono = b.bono_costo(engine, "10.00")
        ml = w.venta(engine, "ml", 2964, 2, D(2026, 10, 5))  # mcosto 30 for 2 units: 15.00 each, without VAT
        _fuera(engine, 2964, 1, D(2026, 10, 6), costo_unit=None)  # no costo_total: unknown, skipped

        result = _items(engine, 2964)

        assert _filas(engine) == [(bono, ml, 2964, 2, Decimal("3.00"))]
        assert result.pendientes == {bono: 1}
        assert result.failed == {}

    def test_a_product_outside_the_scope_gets_nothing(self, engine: Engine) -> None:
        b.bono_costo(engine, "3.00")
        _fuera(engine, 950, 1, D(2026, 10, 5))  # MERCUSYS

        _items(engine, 950)

        assert _filas(engine) == []


@pytest.mark.postgres
class TestIva:
    def test_with_vat_the_percentage_is_divided_by_each_products_own_rate(self, engine: Engine) -> None:
        b.set_iva(engine, 2964, 10.5)
        b.set_iva(engine, 2270, 21.0)
        bono = b.bono_costo(engine, "3.00", incluye_iva=True)
        tp = _fuera(engine, 2964, 1, D(2026, 10, 5))
        forza = _fuera(engine, 2270, 1, D(2026, 10, 5))

        _items(engine, 2964, 2270)

        # 3 / 1.105 = 2.7149 % and 3 / 1.21 = 2.4793 % of 1000.00.
        assert sorted(_filas(engine)) == sorted(
            [(bono, tp, 2964, 1, Decimal("27.15")), (bono, forza, 2270, 1, Decimal("24.79"))]
        )

    def test_without_vat_the_percentage_is_used_as_loaded(self, engine: Engine) -> None:
        b.set_iva(engine, 2964, 10.5)
        bono = b.bono_costo(engine, "2.71")
        ref = _fuera(engine, 2964, 1, D(2026, 10, 5))

        _items(engine, 2964)

        assert _filas(engine) == [(bono, ref, 2964, 1, Decimal("27.10"))]

    def test_with_vat_a_product_without_a_vat_rate_fails_alone(self, engine: Engine) -> None:
        b.set_iva(engine, 2270, 21.0)
        bono = b.bono_costo(engine, "3.00", incluye_iva=True)
        _fuera(engine, 2964, 1, D(2026, 10, 5))  # no iva
        forza = _fuera(engine, 2270, 1, D(2026, 10, 5))

        result = _items(engine, 2964, 2270)

        assert set(result.failed) == {2964}
        assert _filas(engine) == [(bono, forza, 2270, 1, Decimal("24.79"))]


@pytest.mark.postgres
class TestModelos:
    def test_a_model_with_its_own_percentage_uses_it_and_the_others_take_the_bonus(self, engine: Engine) -> None:
        bono = b.bono_costo(engine, "2.00", alcance="modelos", marca=None, modelos=(2964, 950))
        b.valor_de_modelo(engine, bono, 2964, porcentaje="5.00")
        propio = _fuera(engine, 2964, 1, D(2026, 10, 5))
        del_bono = _fuera(engine, 950, 1, D(2026, 10, 5))
        _fuera(engine, 2270, 1, D(2026, 10, 5))  # not a model of the bonus

        _items(engine, 2964, 950, 2270)

        assert sorted(_filas(engine)) == sorted(
            [(bono, propio, 2964, 1, Decimal("50.00")), (bono, del_bono, 950, 1, Decimal("20.00"))]
        )

    def test_a_category_bonus_reaches_the_products_of_its_category(self, engine: Engine) -> None:
        b.set_categoria(engine, 950, "Routers")
        bono = b.bono_costo(engine, "1.00", alcance="categoria", marca=None, categoria="Routers")
        ref = _fuera(engine, 950, 1, D(2026, 10, 5))
        _fuera(engine, 2964, 1, D(2026, 10, 5))

        _items(engine, 950, 2964)

        assert _filas(engine) == [(bono, ref, 950, 1, Decimal("10.00"))]


@pytest.mark.postgres
class TestExclusividad:
    def test_units_taken_by_invoice_sell_in_are_left_out(self, engine: Engine) -> None:
        w.compra(engine, [(2964, 3, "300.00")], D(2026, 10, 1))  # a purchase covering 3 units
        bono = b.bono_costo(engine, "3.00")
        ref = _fuera(engine, 2964, 5, D(2026, 10, 5))
        _fifo(engine, 2964)

        _items(engine, 2964)

        assert [(c[2], c[4]) for c in w.consumos(engine)] == [(ref, 3)]
        assert _filas(engine) == [(bono, ref, 2964, 2, Decimal("60.00"))]

    def test_a_sale_fully_covered_by_invoice_sell_in_gets_no_row(self, engine: Engine) -> None:
        w.compra(engine, [(2964, 10, "300.00")], D(2026, 10, 1))
        b.bono_costo(engine, "3.00")
        _fuera(engine, 2964, 5, D(2026, 10, 5))
        _fifo(engine, 2964)

        _items(engine, 2964)

        assert _filas(engine) == []

    def test_cost_bonuses_stack_on_a_unit_up_to_its_cost(self, engine: Engine) -> None:
        primero = b.bono_costo(engine, "60.00")
        segundo = b.bono_costo(engine, "70.00")
        ref = _fuera(engine, 2964, 2, D(2026, 10, 5))

        _items(engine, 2964)

        # 600.00 per unit for the first; the second only the 400.00 left of the 1000.00 cost.
        assert _filas(engine) == [
            (primero, ref, 2964, 2, Decimal("1200.00")),
            (segundo, ref, 2964, 2, Decimal("800.00")),
        ]


@pytest.mark.postgres
class TestTope:
    def test_the_unit_cap_goes_in_sale_order_a_late_sale_dated_earlier_displaces_a_later_one(
        self, engine: Engine
    ) -> None:
        bono = b.bono_costo(engine, "3.00", tope_unidades=3)
        posterior = _fuera(engine, 2964, 2, D(2026, 10, 10))
        _items(engine, 2964)
        assert _filas(engine) == [(bono, posterior, 2964, 2, Decimal("60.00"))]

        anterior = _fuera(engine, 2270, 2, D(2026, 10, 5))  # loaded later, sold earlier, another product
        _items(engine, 2270)

        assert _filas(engine) == [
            (bono, anterior, 2270, 2, Decimal("60.00")),
            (bono, posterior, 2964, 1, Decimal("30.00")),
        ]

    def test_the_money_cap_is_shared_by_the_whole_bonus(self, engine: Engine) -> None:
        bono = b.bono_costo(engine, "3.00", tope_monto="75.00")
        primera = _fuera(engine, 2964, 2, D(2026, 10, 5))
        segunda = _fuera(engine, 2964, 2, D(2026, 10, 6))

        _bonos(engine, bono)

        assert _filas(engine) == [
            (bono, primera, 2964, 2, Decimal("60.00")),
            (bono, segunda, 2964, 1, Decimal("15.00")),
        ]


@pytest.mark.postgres
class TestDevoluciones:
    def test_a_fuera_return_frees_the_units_of_its_sale(self, engine: Engine) -> None:
        bono = b.bono_costo(engine, "3.00")
        venta = _fuera(engine, 2964, 3, D(2026, 10, 5))
        w.venta(engine, "fuera", 2964, 1, D(2026, 10, 6), signo=-1)

        _items(engine, 2964)

        assert _filas(engine) == [(bono, venta, 2964, 2, Decimal("60.00"))]

    def test_a_return_of_units_invoice_sell_in_held_frees_only_what_the_bonus_held(self, engine: Engine) -> None:
        w.compra(engine, [(2964, 5, "300.00")], D(2026, 10, 1))  # covers the first sale whole
        bono = b.bono_costo(engine, "3.00")
        primera = _fuera(engine, 2964, 5, D(2026, 10, 5))
        otra = _fuera(engine, 2964, 2, D(2026, 10, 6), cliente=999)  # another customer: no units left in the lot
        w.venta(engine, "fuera", 2964, 2, D(2026, 10, 7), signo=-1)  # returns 2 of the first sale
        _fifo(engine, 2964)

        _items(engine, 2964)

        # FIFO keeps 3 units of the first sale; its 2 returned units were never the bonus's, so the other
        # customer's sale keeps its 2: 3 + 2 = 7 sold - 2 returned, no unit counted twice.
        assert [(c[2], c[4]) for c in w.consumos(engine)] == [(primera, 3)]
        assert _filas(engine) == [(bono, otra, 2964, 2, Decimal("60.00"))]


@pytest.mark.postgres
class TestEscritura:
    def test_a_rerun_writes_nothing_and_a_cost_change_rewrites_only_its_row(self, engine: Engine) -> None:
        bono = b.bono_costo(engine, "3.00")
        primera = _fuera(engine, 2964, 1, D(2026, 10, 5))
        segunda = _fuera(engine, 2964, 1, D(2026, 10, 6))
        _items(engine, 2964)
        with engine.connect() as conn:
            ids = dict(conn.execute(text("SELECT venta_ref, id FROM sell_in_bono_consumos")).all())

        again = _items(engine, 2964)
        assert (again.inserted, again.deleted) == (0, 0)

        w.update_venta(engine, "fuera", segunda, costo_total=Decimal("2000.00"))
        changed = _items(engine, 2964)

        assert (changed.inserted, changed.deleted) == (1, 1)
        assert _filas(engine) == [
            (bono, primera, 2964, 1, Decimal("30.00")),
            (bono, segunda, 2964, 1, Decimal("60.00")),
        ]
        with engine.connect() as conn:
            assert (
                conn.execute(text("SELECT id FROM sell_in_bono_consumos WHERE venta_ref = :r"), {"r": primera}).scalar()
                == ids[primera]
            )

    def test_a_voided_bonus_deletes_its_rows(self, engine: Engine) -> None:
        bono = b.bono_costo(engine, "3.00")
        _fuera(engine, 2964, 1, D(2026, 10, 5))
        _bonos(engine, bono)
        assert len(_filas(engine)) == 1

        b.update_bono(engine, bono, estado="anulada")
        result = _bonos(engine, bono)

        assert _filas(engine) == []
        assert result.deleted == 1

    def test_a_sale_moved_out_of_the_range_loses_its_row(self, engine: Engine) -> None:
        b.bono_costo(engine, "3.00")
        ref = _fuera(engine, 2964, 1, D(2026, 10, 5))
        _items(engine, 2964)

        w.update_venta(engine, "fuera", ref, fecha_venta=D(2026, 11, 5))
        _items(engine, 2964)

        assert _filas(engine) == []

    def test_a_row_of_a_bonus_that_is_not_a_cost_bonus_survives_the_recompute(self, engine: Engine) -> None:
        b.bono_costo(engine, "3.00")
        factura = b.bono(engine, monto="1.50")
        otra = _fuera(engine, 2964, 1, D(2026, 10, 5))
        with engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO sell_in_bono_consumos (bono_id, canal, venta_ref, item_id, fecha_venta, unidades, "
                    "descuento_ars) VALUES (:b, 'fuera', :r, 2964, '2026-10-05', 1, 9.99)"
                ),
                {"b": factura, "r": otra},
            )

        _items(engine, 2964)

        assert (factura, otra, 2964, 1, Decimal("9.99")) in _filas(engine)

    def test_no_active_cost_bonus_is_a_no_op(self, engine: Engine) -> None:
        _fuera(engine, 2964, 1, D(2026, 10, 5))

        result = _items(engine, 2964)

        assert (result.inserted, result.deleted, result.failed) == (0, 0, {})


@pytest.mark.postgres
class TestFacturaIgnoraCosto:
    def test_the_invoice_reconcile_never_creates_purchases_for_a_cost_bonus(self, engine: Engine) -> None:
        bono = b.bono_costo(engine, "3.00", tope_unidades=5)
        pedido = b.pedido(engine, {2964: 4})

        with sessionmaker(bind=engine)() as db:
            result = bonos.reconciliar(db, bono_ids=[bono], pedido_ids=[pedido])
            db.commit()

        assert (result.creadas, result.fallidas) == (0, {})
        assert b.generadas(engine) == []

    def test_an_invoice_bonus_still_generates_its_purchase(self, engine: Engine) -> None:
        b.bono_costo(engine, "3.00")
        factura = b.bono(engine, monto="1.50")
        pedido = b.pedido(engine, {2964: 4})

        with sessionmaker(bind=engine)() as db:
            bonos.reconciliar(db, pedido_ids=[pedido])
            db.commit()

        assert [(g[0], g[1], g[4]) for g in b.generadas(engine)] == [(factura, pedido, Decimal("6.00"))]
