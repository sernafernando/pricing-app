"""The % of cost sell-in bonus (sell-in-sell-out T25b) in the workers: `sell.drain` recomputes it right after the
FIFO for the drained products, `sell_in.bono` for a created, edited or voided bonus, and every path that moves the
FIFO (the invoice reconcile, voiding a manual purchase) brings it along, so the exclusivity with invoice-based sell in
always reads the FIFO's current units.

Postgres only, in a throwaway schema (`tests.services.sell_in._bono_world`)."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Iterator

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.orm import sessionmaker

from app.services.sell_in import compras
from app.workers.context import WorkerContext
from app.workers.handlers.sell_drain import drain as sell_drain
from app.workers.handlers.sell_in_bono import bono as sell_in_bono
from tests.services.sell_in import _bono_world as b
from tests.services.sell_in import _world as w

D = date


@pytest.fixture(scope="module")
def engine() -> Iterator[Engine]:
    with b.world("sell_in_bono_costo_workers") as engine:
        yield engine


@pytest.fixture(autouse=True)
def _db(monkeypatch: pytest.MonkeyPatch, engine: Engine) -> Iterator[None]:
    monkeypatch.setattr("app.core.database.SessionLocal", sessionmaker(bind=engine))
    yield
    b.clean(engine)


def _ctx() -> WorkerContext:
    return WorkerContext(deadline=datetime.now(timezone.utc) + timedelta(seconds=30), worker_name="w")


def _drain_ventas() -> dict:
    result = sell_drain.run(_ctx())
    assert result.success
    return result.detail


def _drain_bonos() -> dict:
    result = sell_in_bono.run(_ctx())
    assert result.success
    return result.detail


def _fuera(engine: Engine, item_id: int, unidades: int, dia: date, costo_unit: str = "1000.00") -> int:
    ref = w.venta(engine, "fuera", item_id, unidades, dia)
    w.update_venta(engine, "fuera", ref, costo_total=Decimal(costo_unit) * unidades)
    return ref


def _filas(engine: Engine):
    """`(bono_id, venta_ref, unidades, descuento_ars)`."""
    return [(r[0], r[2], r[5], r[6]) for r in b.bono_consumos(engine)]


def _sell_dirty(engine: Engine):
    with engine.connect() as conn:
        return [tuple(r) for r in conn.execute(text("SELECT venta_ref, attempts, last_error FROM sell_dirty"))]


@pytest.mark.postgres
class TestSellDrain:
    def test_a_drained_sale_gets_its_cost_bonus(self, engine: Engine) -> None:
        bono = b.bono_costo(engine, "3.00")
        _drain_bonos()
        ref = _fuera(engine, 2964, 2, D(2026, 10, 5))

        _drain_ventas()

        assert _filas(engine) == [(bono, ref, 2, Decimal("60.00"))]
        assert _sell_dirty(engine) == []

    def test_the_drain_splits_a_sale_between_the_fifo_and_the_cost_bonus(self, engine: Engine) -> None:
        bono = b.bono_costo(engine, "3.00")
        _drain_bonos()
        w.compra(engine, [(2964, 3, "300.00")], D(2026, 10, 1))
        ref = _fuera(engine, 2964, 5, D(2026, 10, 5))

        _drain_ventas()

        assert [(c[2], c[4]) for c in w.consumos(engine)] == [(ref, 3)]
        assert _filas(engine) == [(bono, ref, 2, Decimal("60.00"))]

    def test_a_product_whose_cost_bonus_fails_charges_its_line(self, engine: Engine) -> None:
        b.bono_costo(engine, "3.00", incluye_iva=True)  # 2964 has no VAT rate
        _drain_bonos()
        ref = _fuera(engine, 2964, 1, D(2026, 10, 5))

        detail = _drain_ventas()

        assert detail["failed"] == 1
        [(venta_ref, attempts, error)] = _sell_dirty(engine)
        assert (venta_ref, attempts) == (ref, 1)
        assert "IVA" in error


@pytest.mark.postgres
class TestSellInBono:
    def test_a_new_cost_bonus_applies_to_the_sales_and_generates_no_purchase(self, engine: Engine) -> None:
        ref = _fuera(engine, 2964, 2, D(2026, 10, 5))
        b.pedido(engine, {2964: 4})  # invoiced in the range: an invoice bonus would take it
        _drain_ventas()
        bono = b.bono_costo(engine, "3.00")
        assert b.queued(engine) == [("bono", bono)]

        detail = _drain_bonos()

        assert _filas(engine) == [(bono, ref, 2, Decimal("60.00"))]
        assert b.generadas(engine) == []
        assert (detail["failed"], b.queued(engine)) == (0, [])

    def test_an_edited_cost_bonus_is_recomputed_and_a_voided_one_loses_its_rows(self, engine: Engine) -> None:
        ref = _fuera(engine, 2964, 1, D(2026, 10, 5))
        _drain_ventas()
        bono = b.bono_costo(engine, "3.00")
        _drain_bonos()

        b.update_bono(engine, bono, porcentaje=Decimal("5.00"))
        _drain_bonos()
        assert _filas(engine) == [(bono, ref, 1, Decimal("50.00"))]

        b.update_bono(engine, bono, estado="anulada")
        _drain_bonos()
        assert _filas(engine) == []

    def test_a_cost_bonus_that_fails_charges_its_key(self, engine: Engine) -> None:
        _fuera(engine, 2964, 1, D(2026, 10, 5))
        _drain_ventas()
        bono = b.bono_costo(engine, "3.00", incluye_iva=True)  # 2964 has no VAT rate

        detail = _drain_bonos()

        assert detail["failed"] == 1
        [(tipo, ref_, attempts, error)] = b.queue_rows(engine)
        assert (tipo, ref_, attempts) == ("bono", bono, 1)
        assert "IVA" in error

    def test_an_invoice_bonus_that_takes_the_units_pushes_the_cost_bonus_aside(self, engine: Engine) -> None:
        ref = _fuera(engine, 2964, 5, D(2026, 10, 12))
        _drain_ventas()
        costo = b.bono_costo(engine, "3.00")
        _drain_bonos()
        assert _filas(engine) == [(costo, ref, 5, Decimal("150.00"))]

        b.bono(engine, monto="1.50")
        b.pedido(engine, {2964: 3}, D(2026, 10, 10))  # the old invoice gets loaded: 3 units of sell in
        _drain_bonos()

        assert [(c[2], c[4]) for c in w.consumos(engine)] == [(ref, 3)]
        assert _filas(engine) == [(costo, ref, 2, Decimal("60.00"))]


@pytest.mark.postgres
class TestCompras:
    def test_voiding_a_manual_purchase_gives_its_units_to_the_cost_bonus(self, engine: Engine) -> None:
        w.compra(engine, [(2964, 5, "300.00")], D(2026, 10, 1))
        ref = _fuera(engine, 2964, 5, D(2026, 10, 5))
        costo = b.bono_costo(engine, "3.00")
        _drain_bonos()
        _drain_ventas()
        assert _filas(engine) == []
        with engine.connect() as conn:
            compra_id = conn.execute(text("SELECT id FROM sell_in_compras")).scalar_one()

        with sessionmaker(bind=engine)() as db:
            compras.anular_compra(db, compra_id, 7, "prueba")

        assert w.consumos(engine) == []
        assert _filas(engine) == [(costo, ref, 5, Decimal("150.00"))]
