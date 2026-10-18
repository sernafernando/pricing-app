"""`FifoPurchaseCosting` (sell-in-sell-out T5, option A) against real tables:
it recomputes a product's `sell_in_consumos` from its active purchase lines and
its sales in the three channels, writing only what changed.

Postgres only: the recompute takes a per-product advisory lock. Runs in a
throwaway schema (`_world`).
"""

from __future__ import annotations

import threading
import time
from dataclasses import replace
from datetime import date
from decimal import Decimal
from typing import Iterator

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session, sessionmaker

from app.models.sell_in import SellInCompra, SellInCompraItem
from app.schemas.sell_in import SellInCompraCreate, SellInLineaIn
from app.services.sell_in import compras
from app.services.sell_in import costing as costing_module
from app.services.sell_in.costing import FifoPurchaseCosting, SellInCosting, get_costing
from tests.services.sell_in import _world as w

D = date


@pytest.fixture(scope="module")
def engine() -> Iterator[Engine]:
    with w.world("sell_in_costing") as engine:
        yield engine


@pytest.fixture(autouse=True)
def _clean(engine: Engine) -> Iterator[None]:
    yield
    w.clean(engine)


def _recompute(engine: Engine, *items: int):
    with sessionmaker(bind=engine)() as db:
        result = get_costing().recompute(db, items)
        db.commit()
    return result


@pytest.mark.postgres
class TestStrategy:
    def test_the_active_strategy_is_fifo_by_purchase(self) -> None:
        costing = get_costing()

        assert isinstance(costing, FifoPurchaseCosting)
        assert isinstance(costing, SellInCosting)


@pytest.mark.postgres
class TestFifoPurchaseCosting:
    def test_sales_in_every_channel_consume_the_purchase_partially(self, engine: Engine) -> None:
        [linea] = w.compra(engine, [(2964, 10, "250000.00")])
        ml = w.venta(engine, "ml", 2964, 2, D(2026, 10, 2))
        fuera = w.venta(engine, "fuera", 2964, 1, D(2026, 10, 3))
        tn = w.venta(engine, "tn", 2964, 3, D(2026, 10, 4))

        result = _recompute(engine, 2964)

        assert w.consumos(engine) == [
            (linea, "fuera", fuera, 2964, 1, Decimal("25000.00")),
            (linea, "ml", ml, 2964, 2, Decimal("50000.00")),
            (linea, "tn", tn, 2964, 3, Decimal("75000.00")),
        ]
        assert (result.products, result.inserted, result.deleted, result.failed) == (1, 3, 0, {})

    def test_used_up_units_send_later_sales_back_to_normal_cost(self, engine: Engine) -> None:
        [linea] = w.compra(engine, [(2964, 3, "300.00")])
        a = w.venta(engine, "fuera", 2964, 2, D(2026, 10, 2))
        b = w.venta(engine, "fuera", 2964, 2, D(2026, 10, 3))
        w.venta(engine, "fuera", 2964, 1, D(2026, 10, 4))

        _recompute(engine, 2964)

        assert w.consumos(engine) == [
            (linea, "fuera", a, 2964, 2, Decimal("200.00")),
            (linea, "fuera", b, 2964, 1, Decimal("100.00")),
        ]

    def test_a_sale_crossing_two_purchases_takes_the_oldest_first(self, engine: Engine) -> None:
        [nueva] = w.compra(engine, [(2964, 5, "50.00")], D(2026, 10, 5))
        [vieja] = w.compra(engine, [(2964, 2, "40.00")], D(2026, 10, 1))
        ref = w.venta(engine, "fuera", 2964, 4, D(2026, 10, 6))

        _recompute(engine, 2964)

        assert w.consumos(engine) == sorted(
            [(vieja, "fuera", ref, 2964, 2, Decimal("40.00")), (nueva, "fuera", ref, 2964, 2, Decimal("20.00"))]
        )

    def test_a_purchase_counting_from_its_goods_receipt_waits_for_it(self, engine: Engine) -> None:
        [por_ingreso] = w.compra(
            engine, [(2964, 5, "50.00")], D(2026, 10, 1), cuenta_desde="ingreso", fecha_ingreso=D(2026, 10, 8)
        )
        [por_compra] = w.compra(engine, [(2964, 5, "500.00")], D(2026, 10, 5))
        antes = w.venta(engine, "fuera", 2964, 1, D(2026, 10, 6))
        despues = w.venta(engine, "fuera", 2964, 6, D(2026, 10, 9))

        _recompute(engine, 2964)

        assert w.consumos(engine) == sorted(
            [
                (por_compra, "fuera", antes, 2964, 1, Decimal("100.00")),
                (por_compra, "fuera", despues, 2964, 4, Decimal("400.00")),
                (por_ingreso, "fuera", despues, 2964, 2, Decimal("20.00")),
            ]
        )

    def test_usd_is_consumed_at_the_purchase_own_tipo_cambio(self, engine: Engine) -> None:
        """Owner's decision (2026-10-17): a USD sell in turns into pesos at the
        `tipo_cambio` frozen on ITS purchase, never at the sale-date rate."""
        [vieja] = w.compra(engine, [(2964, 1, "100.00")], D(2026, 10, 1), moneda="USD", tipo_cambio="1000.000000")
        [nueva] = w.compra(engine, [(2964, 4, "100.00")], D(2026, 10, 2), moneda="USD", tipo_cambio="1450.500000")
        ref = w.venta(engine, "tn", 2964, 2, D(2026, 10, 9))

        _recompute(engine, 2964)

        assert w.consumos(engine) == [
            (vieja, "tn", ref, 2964, 1, Decimal("100000.00")),
            (nueva, "tn", ref, 2964, 1, Decimal("36262.50")),
        ]

    def test_a_return_before_any_consumption_and_negative_adjustment_lines_free_nothing(self, engine: Engine) -> None:
        [linea] = w.compra(engine, [(2964, 5, "50.00")])
        w.venta(engine, "fuera", 2964, 1, D(2026, 10, 2), signo=-1)
        w.venta(engine, "tn", 2964, -1, D(2026, 10, 2))
        venta = w.venta(engine, "fuera", 2964, 1, D(2026, 10, 3))

        _recompute(engine, 2964)

        assert w.consumos(engine) == [(linea, "fuera", venta, 2964, 1, Decimal("10.00"))]

    def test_a_deleted_sale_frees_its_units_for_the_next_sale_in_line(self, engine: Engine) -> None:
        [linea] = w.compra(engine, [(2964, 2, "20.00")])
        primera = w.venta(engine, "ml", 2964, 2, D(2026, 10, 2))
        segunda = w.venta(engine, "fuera", 2964, 2, D(2026, 10, 3))
        _recompute(engine, 2964)

        w.delete_venta(engine, "ml", primera)
        _recompute(engine, 2964)

        assert w.consumos(engine) == [(linea, "fuera", segunda, 2964, 2, Decimal("20.00"))]

    def test_a_quantity_change_reallocates(self, engine: Engine) -> None:
        [linea] = w.compra(engine, [(2964, 3, "30.00")])
        primera = w.venta(engine, "fuera", 2964, 3, D(2026, 10, 2))
        segunda = w.venta(engine, "tn", 2964, 2, D(2026, 10, 3))
        _recompute(engine, 2964)
        assert [c[2] for c in w.consumos(engine)] == [primera]

        w.update_venta(engine, "fuera", primera, cantidad=Decimal("1.0000"))
        _recompute(engine, 2964)

        assert w.consumos(engine) == [
            (linea, "fuera", primera, 2964, 1, Decimal("10.00")),
            (linea, "tn", segunda, 2964, 2, Decimal("20.00")),
        ]

    def test_a_product_change_releases_the_old_product(self, engine: Engine) -> None:
        [vieja] = w.compra(engine, [(2964, 2, "20.00")])
        [nueva] = w.compra(engine, [(2270, 2, "80.00")])
        ref = w.venta(engine, "fuera", 2964, 1, D(2026, 10, 2))
        _recompute(engine, 2964)

        w.update_venta(engine, "fuera", ref, item_id=2270)
        _recompute(engine, 2964, 2270)

        assert w.consumos(engine) == [(nueva, "fuera", ref, 2270, 1, Decimal("40.00"))]
        assert vieja != nueva

    def test_a_rerun_writes_nothing(self, engine: Engine) -> None:
        w.compra(engine, [(2964, 5, "50.00")])
        w.compra(engine, [(2964, 5, "70.00")], D(2026, 10, 2))
        for dia in range(2, 6):
            w.venta(engine, "fuera", 2964, 2, D(2026, 10, dia))
        _recompute(engine, 2964)
        before = (w.consumos(engine), w.consumo_ids(engine))

        again = _recompute(engine, 2964)

        assert (w.consumos(engine), w.consumo_ids(engine)) == before
        assert (again.products, again.inserted, again.deleted) == (1, 0, 0)

    def test_a_product_without_sell_in_is_untouched(self, engine: Engine) -> None:
        w.venta(engine, "fuera", 950, 2, D(2026, 10, 3))

        result = _recompute(engine, 950)

        assert w.consumos(engine) == []
        assert (result.inserted, result.deleted) == (0, 0)

    def test_a_voided_purchase_releases_everything_to_the_next_purchase(self, engine: Engine) -> None:
        [anulada] = w.compra(engine, [(2964, 2, "20.00")], D(2026, 10, 1))
        [siguiente] = w.compra(engine, [(2964, 5, "500.00")], D(2026, 10, 2))
        ref = w.venta(engine, "fuera", 2964, 2, D(2026, 10, 3))
        _recompute(engine, 2964)
        assert [c[0] for c in w.consumos(engine)] == [anulada]

        with sessionmaker(bind=engine)() as db:
            compra_id = db.query(SellInCompra.id).order_by(SellInCompra.id).first()[0]
            compras.anular_compra(db, compra_id, usuario_id=7, motivo="error de carga")

        assert w.consumos(engine) == [(siguiente, "fuera", ref, 2964, 2, Decimal("200.00"))]

    def test_loading_a_purchase_allocates_the_sales_already_made(self, engine: Engine) -> None:
        ref = w.venta(engine, "fuera", 2964, 2, D(2026, 10, 3))
        data = SellInCompraCreate(
            moneda="ARS",
            monto_total=Decimal("100.00"),
            formula="por_unidad",
            fecha_compra=D(2026, 10, 1),
            lineas=[SellInLineaIn(item_id=2964, cantidad=4, costo_base_unit=Decimal("1000"))],
        )

        with sessionmaker(bind=engine)() as db:
            compra = compras.crear_compra(db, data, usuario_id=7)
            lineas = [i.id for i in compra_items(db, compra.id)]

        assert w.consumos(engine) == [(lineas[0], "fuera", ref, 2964, 2, Decimal("50.00"))]


X, Y, Z = 31748, 202741, 394748  # real fuera customers


@pytest.mark.postgres
class TestDevoluciones:
    """Owner's decision: every fuera return gives its units back. The sale that
    loses them is the customer's ONLY earlier sale of the product (same
    `cust_id` and `item_id`, earlier by `(fecha_venta, it_transaction)`); with
    zero or several candidates, the most recent earlier sale still holding
    units. Freed units go to later sales FIFO. Only our own sale columns."""

    def test_the_customer_unique_earlier_sale_gives_the_units_back(self, engine: Engine) -> None:
        [linea] = w.compra(engine, [(2964, 2, "20.00")])
        suya = w.venta(engine, "fuera", 2964, 1, D(2026, 10, 2), cliente=X)
        otra = w.venta(engine, "fuera", 2964, 1, D(2026, 10, 3), cliente=Y)  # the most recent: NOT picked
        w.venta(engine, "fuera", 2964, 1, D(2026, 10, 4), signo=-1, cliente=X)
        despues = w.venta(engine, "tn", 2964, 1, D(2026, 10, 5))

        _recompute(engine, 2964)

        assert w.consumos(engine) == [
            (linea, "fuera", otra, 2964, 1, Decimal("10.00")),
            (linea, "tn", despues, 2964, 1, Decimal("10.00")),
        ]
        assert suya not in [c[2] for c in w.consumos(engine)]

    def test_a_same_day_return_matches_the_sale_it_follows(self, engine: Engine) -> None:
        [linea] = w.compra(engine, [(2964, 1, "10.00")], D(2026, 9, 1))
        w.venta(engine, "fuera", 2964, 1, D(2026, 9, 30), cliente=X)  # like 584631
        w.venta(engine, "fuera", 2964, 1, D(2026, 9, 30), signo=-1, cliente=X)  # like 584724
        despues = w.venta(engine, "fuera", 2964, 1, D(2026, 10, 1), cliente=Y)

        _recompute(engine, 2964)

        assert w.consumos(engine) == [(linea, "fuera", despues, 2964, 1, Decimal("10.00"))]

    def test_several_candidates_fall_back_to_the_most_recent_holder(self, engine: Engine) -> None:
        [linea] = w.compra(engine, [(2964, 3, "30.00")])
        a = w.venta(engine, "fuera", 2964, 1, D(2026, 10, 2), cliente=X)
        b = w.venta(engine, "fuera", 2964, 1, D(2026, 10, 3), cliente=X)
        w.venta(engine, "ml", 2964, 1, D(2026, 10, 4))  # someone else's, the most recent: loses it
        w.venta(engine, "fuera", 2964, 1, D(2026, 10, 5), signo=-1, cliente=X)

        _recompute(engine, 2964)

        assert w.consumos(engine) == [
            (linea, "fuera", a, 2964, 1, Decimal("10.00")),
            (linea, "fuera", b, 2964, 1, Decimal("10.00")),
        ]

    def test_no_candidate_falls_back_to_the_most_recent_holder(self, engine: Engine) -> None:
        [linea] = w.compra(engine, [(2964, 2, "20.00")])
        a = w.venta(engine, "fuera", 2964, 1, D(2026, 10, 2), cliente=X)
        w.venta(engine, "tn", 2964, 1, D(2026, 10, 3), cliente=Y)
        w.venta(engine, "fuera", 2964, 1, D(2026, 10, 4), signo=-1, cliente=Z)

        _recompute(engine, 2964)

        assert w.consumos(engine) == [(linea, "fuera", a, 2964, 1, Decimal("10.00"))]

    def test_candidates_count_sales_before_the_purchase_too(self, engine: Engine) -> None:
        [linea] = w.compra(engine, [(2964, 2, "20.00")])
        w.venta(engine, "fuera", 2964, 1, D(2026, 9, 15), cliente=X)  # before the purchase counts
        suya = w.venta(engine, "fuera", 2964, 1, D(2026, 10, 2), cliente=X)
        w.venta(engine, "fuera", 2964, 1, D(2026, 10, 3), cliente=Y)  # most recent holder: loses it
        w.venta(engine, "fuera", 2964, 1, D(2026, 10, 4), signo=-1, cliente=X)

        _recompute(engine, 2964)

        assert w.consumos(engine) == [(linea, "fuera", suya, 2964, 1, Decimal("10.00"))]

    def test_a_unique_sale_before_the_purchase_falls_back_to_the_most_recent_holder(self, engine: Engine) -> None:
        """The customer's only earlier sale predates the purchase, so it holds no
        units: every return still releases units, from the most recent holder."""
        [linea] = w.compra(engine, [(2964, 2, "20.00")])
        w.venta(engine, "fuera", 2964, 1, D(2026, 9, 15), cliente=X)  # X's only sale: before the purchase
        a = w.venta(engine, "fuera", 2964, 1, D(2026, 10, 2), cliente=Y)
        w.venta(engine, "tn", 2964, 1, D(2026, 10, 3), cliente=Z)  # most recent holder: loses it
        w.venta(engine, "fuera", 2964, 1, D(2026, 10, 4), signo=-1, cliente=X)
        despues = w.venta(engine, "ml", 2964, 1, D(2026, 10, 5))

        _recompute(engine, 2964)

        assert w.consumos(engine) == [
            (linea, "fuera", a, 2964, 1, Decimal("10.00")),
            (linea, "ml", despues, 2964, 1, Decimal("10.00")),
        ]

    def test_returning_more_than_the_sale_holds_takes_the_excess_from_the_fallback(self, engine: Engine) -> None:
        [linea] = w.compra(engine, [(2964, 3, "30.00")])
        w.venta(engine, "fuera", 2964, 1, D(2026, 10, 2), cliente=X)
        otra = w.venta(engine, "fuera", 2964, 2, D(2026, 10, 3), cliente=Y)
        w.venta(engine, "fuera", 2964, 2, D(2026, 10, 4), signo=-1, cliente=X)
        despues = w.venta(engine, "fuera", 2964, 3, D(2026, 10, 5), cliente=Z)

        _recompute(engine, 2964)

        assert w.consumos(engine) == [
            (linea, "fuera", otra, 2964, 1, Decimal("10.00")),
            (linea, "fuera", despues, 2964, 2, Decimal("20.00")),
        ]
        assert sum(c[5] for c in w.consumos(engine)) == Decimal("30.00")


def compra_items(db: Session, compra_id: int):
    return db.query(SellInCompraItem).filter(SellInCompraItem.compra_id == compra_id).order_by(SellInCompraItem.id)


@pytest.mark.postgres
class TestAplica:
    """`aplica_condicion`: active AND units left. The single rule."""

    def _aplica(self, engine: Engine) -> list:
        with sessionmaker(bind=engine)() as db:
            return [
                bool(a)
                for (a,) in db.query(compras.aplica_condicion()).select_from(SellInCompra).order_by(SellInCompra.id)
            ]

    def test_an_active_purchase_with_units_left_applies(self, engine: Engine) -> None:
        w.compra(engine, [(2964, 3, "30.00"), (2270, 1, "10.00")])
        w.venta(engine, "fuera", 2964, 3, D(2026, 10, 2))
        _recompute(engine, 2964)

        assert self._aplica(engine) == [True]

    def test_a_used_up_purchase_stops_applying(self, engine: Engine) -> None:
        w.compra(engine, [(2964, 3, "30.00"), (2270, 1, "10.00")])
        w.venta(engine, "fuera", 2964, 3, D(2026, 10, 2))
        w.venta(engine, "tn", 2270, 1, D(2026, 10, 2))
        _recompute(engine, 2964, 2270)

        assert self._aplica(engine) == [False]

    def test_a_voided_purchase_never_applies(self, engine: Engine) -> None:
        w.compra(engine, [(2964, 3, "30.00")], estado="anulada")

        assert self._aplica(engine) == [False]


def _failing_for(line_id: int):
    """`asignar` that raises for the product owning purchase line `line_id`, as bad data would."""
    real = costing_module.asignar

    def fake(lotes, ventas):
        lotes = list(lotes)
        if any(lote.compra_item_id == line_id for lote in lotes):
            raise ValueError(f"bad data on line {line_id}")
        return real(lotes, ventas)

    return fake


@pytest.mark.postgres
class TestFailures:
    """A product whose allocation fails is rolled back alone (isolate_failures=True)
    or stops the whole call (isolate_failures=False)."""

    def test_an_isolated_failure_rolls_back_only_that_product(self, engine: Engine, monkeypatch) -> None:
        [mala] = w.compra(engine, [(2964, 5, "50.00")])
        [buena] = w.compra(engine, [(950, 5, "50.00")])
        guardada = w.venta(engine, "fuera", 2964, 1, D(2026, 10, 2))
        _recompute(engine, 2964)
        w.venta(engine, "fuera", 2964, 1, D(2026, 10, 3))
        otra = w.venta(engine, "tn", 950, 2, D(2026, 10, 3))
        monkeypatch.setattr(costing_module, "asignar", _failing_for(mala))

        result = _recompute(engine, 950, 2964)

        assert w.consumos(engine) == [
            (mala, "fuera", guardada, 2964, 1, Decimal("10.00")),  # untouched: rolled back alone
            (buena, "tn", otra, 950, 2, Decimal("20.00")),
        ]
        assert result.failed == {2964: f"ValueError: bad data on line {mala}"}
        assert (result.products, result.inserted, result.deleted) == (2, 1, 0)

    def test_without_isolation_a_failure_propagates_and_nothing_is_written(self, engine: Engine, monkeypatch) -> None:
        [mala] = w.compra(engine, [(2964, 5, "50.00")])
        w.compra(engine, [(950, 5, "50.00")])
        w.venta(engine, "fuera", 2964, 1, D(2026, 10, 2))
        w.venta(engine, "tn", 950, 2, D(2026, 10, 3))  # 950 goes first and is written in the session
        monkeypatch.setattr(costing_module, "asignar", _failing_for(mala))

        with sessionmaker(bind=engine)() as db:
            with pytest.raises(ValueError, match="bad data"):
                get_costing().recompute(db, [950, 2964], isolate_failures=False)
            db.rollback()

        assert w.consumos(engine) == []


def _always_failing(lotes, ventas):
    raise ValueError("bad data")


def _rows(engine: Engine, table: str) -> int:
    with engine.connect() as conn:
        return conn.execute(text(f"SELECT count(*) FROM {table}")).scalar()


@pytest.mark.postgres
class TestPurchaseRecomputeFailure:
    """Loading and voiding recompute with `isolate_failures=False`: a failed
    recompute takes the whole purchase change down with it."""

    def test_a_failed_recompute_on_load_writes_no_purchase_items_or_audit(self, engine: Engine, monkeypatch) -> None:
        w.venta(engine, "fuera", 2964, 2, D(2026, 10, 3))
        monkeypatch.setattr(costing_module, "asignar", _always_failing)
        data = SellInCompraCreate(
            moneda="ARS",
            monto_total=Decimal("100.00"),
            formula="por_unidad",
            fecha_compra=D(2026, 10, 1),
            lineas=[SellInLineaIn(item_id=2964, cantidad=4, costo_base_unit=Decimal("1000"))],
        )

        with sessionmaker(bind=engine)() as db:
            with pytest.raises(ValueError, match="bad data"):
                compras.crear_compra(db, data, usuario_id=7)

        assert [_rows(engine, t) for t in ("sell_in_compras", "sell_in_compra_items", "auditoria")] == [0, 0, 0]
        assert w.consumos(engine) == []

    def test_a_failed_recompute_on_void_keeps_the_purchase_active_and_unaudited(
        self, engine: Engine, monkeypatch
    ) -> None:
        [linea] = w.compra(engine, [(2964, 4, "40.00")])
        ref = w.venta(engine, "fuera", 2964, 2, D(2026, 10, 3))
        _recompute(engine, 2964)
        monkeypatch.setattr(costing_module, "asignar", _always_failing)

        with sessionmaker(bind=engine)() as db:
            compra_id = db.query(SellInCompra.id).one()[0]
            with pytest.raises(ValueError, match="bad data"):
                compras.anular_compra(db, compra_id, usuario_id=7, motivo="error de carga")

        with engine.connect() as conn:
            assert conn.execute(text("SELECT estado FROM sell_in_compras")).scalar() == "activa"
        assert _rows(engine, "auditoria") == 0
        assert w.consumos(engine) == [(linea, "fuera", ref, 2964, 2, Decimal("20.00"))]


def _db_failing_escribir(db, item_id, deseados, guardados):
    db.execute(text("SELECT 1 / 0"))  # a database error: the transaction is aborted


@pytest.mark.postgres
class TestPurchaseRecomputeDatabaseFailure:
    """A recompute that fails in the database leaves the caller's session rolled
    back and usable, never aborted, on load and on void."""

    def test_a_database_error_on_load_rolls_the_session_back(self, engine: Engine, monkeypatch) -> None:
        monkeypatch.setattr(FifoPurchaseCosting, "_escribir", staticmethod(_db_failing_escribir))
        w.venta(engine, "fuera", 2964, 2, D(2026, 10, 3))
        data = SellInCompraCreate(
            moneda="ARS",
            monto_total=Decimal("100.00"),
            formula="por_unidad",
            fecha_compra=D(2026, 10, 1),
            lineas=[SellInLineaIn(item_id=2964, cantidad=4, costo_base_unit=Decimal("1000"))],
        )

        with sessionmaker(bind=engine)() as db:
            with pytest.raises(DBAPIError):
                compras.crear_compra(db, data, usuario_id=7)
            assert db.execute(text("SELECT count(*) FROM sell_in_compras")).scalar() == 0

        assert [_rows(engine, t) for t in ("sell_in_compras", "sell_in_compra_items", "auditoria")] == [0, 0, 0]

    def test_a_database_error_on_void_rolls_the_session_back(self, engine: Engine, monkeypatch) -> None:
        w.compra(engine, [(2964, 4, "40.00")])
        w.venta(engine, "fuera", 2964, 2, D(2026, 10, 3))
        monkeypatch.setattr(FifoPurchaseCosting, "_escribir", staticmethod(_db_failing_escribir))

        with sessionmaker(bind=engine)() as db:
            compra_id = db.query(SellInCompra.id).one()[0]
            with pytest.raises(DBAPIError):
                compras.anular_compra(db, compra_id, usuario_id=7, motivo="error de carga")
            assert db.execute(text("SELECT estado FROM sell_in_compras")).scalar() == "activa"

        assert _rows(engine, "auditoria") == 0


@pytest.mark.postgres
class TestPrecision:
    """Stored amounts have the column's scale (cents): a re-run compares and writes at that scale."""

    def test_a_rerun_with_amounts_needing_rounding_writes_nothing(self, engine: Engine) -> None:
        w.compra(engine, [(2964, 3, "100.00")])
        w.compra(engine, [(2964, 7, "99.99")], D(2026, 10, 2), moneda="USD", tipo_cambio="1453.123457")
        for dia in range(2, 8):
            w.venta(engine, "fuera", 2964, 1, D(2026, 10, dia))
        _recompute(engine, 2964)
        before = (w.consumos(engine), w.consumo_ids(engine))

        again = _recompute(engine, 2964)

        assert (w.consumos(engine), w.consumo_ids(engine)) == before
        assert (again.inserted, again.deleted) == (0, 0)

    def test_amounts_finer_than_the_column_are_rounded_once_and_never_rewritten(
        self, engine: Engine, monkeypatch
    ) -> None:
        """Whatever precision the allocation returns, it is stored at the column's
        scale and a re-run compares at that scale."""
        real = costing_module.asignar

        def fine(lotes, ventas):
            return [replace(c, descuento_ars=c.descuento_ars / 7) for c in real(lotes, ventas)]

        monkeypatch.setattr(costing_module, "asignar", fine)
        [linea] = w.compra(engine, [(2964, 3, "100.00")])
        ref = w.venta(engine, "fuera", 2964, 1, D(2026, 10, 2))
        _recompute(engine, 2964)
        before = w.consumo_ids(engine)

        again = _recompute(engine, 2964)

        assert w.consumos(engine) == [(linea, "fuera", ref, 2964, 1, Decimal("4.76"))]
        assert w.consumo_ids(engine) == before
        assert (again.inserted, again.deleted) == (0, 0)


@pytest.fixture
def ingreso_sin_fecha(engine: Engine) -> Iterator[None]:
    """Drops the check that forbids `cuenta_desde = 'ingreso'` without `fecha_ingreso`,
    so the recompute's own guard can be exercised; restores it afterwards."""
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE sell_in_compras DROP CONSTRAINT ck_sell_in_compras_ingreso_con_fecha"))
    yield
    w.clean(engine)
    with engine.begin() as conn:
        conn.execute(
            text(
                "ALTER TABLE sell_in_compras ADD CONSTRAINT ck_sell_in_compras_ingreso_con_fecha "
                "CHECK (cuenta_desde <> 'ingreso' OR fecha_ingreso IS NOT NULL)"
            )
        )


@pytest.mark.postgres
class TestSinIngreso:
    def test_a_line_counting_from_a_missing_goods_receipt_does_not_count_yet(
        self, engine: Engine, ingreso_sin_fecha: None
    ) -> None:
        """Fail-safe: counting from the goods receipt with no receipt yet means the
        purchase has not started, so its units are not available to any sale."""
        w.compra(engine, [(2964, 5, "50.00")], D(2026, 10, 1), cuenta_desde="ingreso", fecha_ingreso=None)
        [por_compra] = w.compra(engine, [(2964, 1, "30.00")], D(2026, 10, 1))
        ref = w.venta(engine, "fuera", 2964, 2, D(2026, 10, 3))

        result = _recompute(engine, 2964)

        assert w.consumos(engine) == [(por_compra, "fuera", ref, 2964, 1, Decimal("30.00"))]
        assert result.failed == {}

    def test_a_product_whose_only_line_lacks_its_receipt_writes_nothing(
        self, engine: Engine, ingreso_sin_fecha: None
    ) -> None:
        w.compra(engine, [(2964, 5, "50.00")], D(2026, 10, 1), cuenta_desde="ingreso", fecha_ingreso=None)
        w.venta(engine, "fuera", 2964, 2, D(2026, 10, 3))

        result = _recompute(engine, 2964)

        assert w.consumos(engine) == []
        assert (result.inserted, result.deleted, result.failed) == (0, 0, {})


def _waiting_on_advisory_lock(engine: Engine) -> bool:
    with engine.connect() as conn:
        return bool(
            conn.execute(
                text("SELECT count(*) FROM pg_locks WHERE locktype = 'advisory' AND classid = :ns AND NOT granted"),
                {"ns": costing_module.LOCK_NAMESPACE},
            ).scalar()
        )


@pytest.mark.postgres
class TestConcurrency:
    def test_two_recomputes_of_one_product_serialize(self, engine: Engine) -> None:
        """The second recompute waits on the product's advisory lock until the first
        commits, then reads its rows and writes nothing: no duplicate consumptions."""
        [linea] = w.compra(engine, [(2964, 5, "50.00")])
        ref = w.venta(engine, "fuera", 2964, 2, D(2026, 10, 2))
        Session_ = sessionmaker(bind=engine)
        primera = Session_()
        segunda: dict = {}

        def recompute_segunda() -> None:
            with Session_() as db:
                try:
                    segunda["result"] = get_costing().recompute(db, [2964], isolate_failures=False)
                    db.commit()
                except Exception as exc:  # noqa: BLE001 - surfaced by the assertion below
                    segunda["error"] = exc

        try:
            assert get_costing().recompute(primera, [2964]).inserted == 1  # holds the lock, uncommitted
            hilo = threading.Thread(target=recompute_segunda)
            hilo.start()
            deadline = time.monotonic() + 10
            while not _waiting_on_advisory_lock(engine):
                assert time.monotonic() < deadline, "the second recompute never waited on the lock"
                time.sleep(0.02)
            assert hilo.is_alive() and segunda == {}
            primera.commit()
        finally:
            primera.close()
        hilo.join(timeout=10)

        assert not hilo.is_alive()
        assert "error" not in segunda, segunda.get("error")
        assert (segunda["result"].inserted, segunda["result"].deleted) == (0, 0)
        assert w.consumos(engine) == [(linea, "fuera", ref, 2964, 2, Decimal("20.00"))]
