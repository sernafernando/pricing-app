"""The % of cost sell-in bonus (sell-in-sell-out T25b) in the workers: `sell.drain` recomputes it right after the
FIFO for the drained products, `sell_in.bono` for a created, edited or voided bonus, and every path that moves the
FIFO (the invoice reconcile, voiding a manual purchase) brings it along, so the exclusivity with invoice-based sell in
always reads the FIFO's current units.

Postgres only, in a throwaway schema (`tests.services.sell_in._bono_world`)."""

from __future__ import annotations

import logging
import threading
import time as clock
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Iterator

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.orm import sessionmaker

from app.schemas.sell_in import SellInCompraCreate, SellInLineaIn
from app.services.sell_in import bonos_costo, compras
from app.services.sell_in.costing import LOCK_NAMESPACE
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

    def test_a_cost_bonus_failure_is_reported_never_charged_to_a_line_whose_fifo_succeeded(
        self, engine: Engine, caplog: pytest.LogCaptureFixture
    ) -> None:
        # A capped bonus with VAT links 2270 (21 %) to 2964, which has no VAT rate: the component fails.
        b.set_iva(engine, 2270, 21.0)
        bono = b.bono_costo(engine, "3.00", incluye_iva=True, tope_unidades=10)
        _drain_bonos()
        _fuera(engine, 2964, 1, D(2026, 10, 4))  # a sale of the product without VAT
        _drain_ventas()
        [linea] = w.compra(engine, [(2270, 1, "100.00")], D(2026, 10, 1))
        ref = _fuera(engine, 2270, 2, D(2026, 10, 5))

        with caplog.at_level(logging.ERROR):
            detail = _drain_ventas()

        assert (detail["failed"], detail["bonos_costo_fallidos"]) == (0, 1)
        assert _sell_dirty(engine) == []  # acked
        assert [(c[0], c[2], c[4]) for c in w.consumos(engine)] == [(linea, ref, 1)]
        assert _filas(engine) == []  # the failed component keeps its rows (none)
        # One alert per failed bonus (a capture handler may see a record twice: compared as a set).
        errores = {
            r.getMessage() for r in caplog.records if r.levelno == logging.ERROR and "cost bonus" in r.getMessage()
        }
        assert errores == {
            f"sell.drain: cost bonus (bono {bono}) not recomputed for products [2270, 2964]: "
            f"bono {bono}: el producto 2964 no tiene alícuota de IVA"
        }

    def test_an_unexpected_cost_bonus_error_rolls_back_only_its_savepoint_and_charges_no_line(
        self, engine: Engine, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # GGA: an error other than a missing VAT rate (e.g. a CHECK violation) must not abort the batch either.
        [linea] = w.compra(engine, [(2270, 1, "100.00")], D(2026, 10, 1))
        ref = _fuera(engine, 2270, 1, D(2026, 10, 5))

        def boom(db, items):
            db.execute(text("SELECT 1"))  # inside the savepoint
            raise RuntimeError("boom")

        monkeypatch.setattr(bonos_costo, "recalcular", boom)

        detail = _drain_ventas()

        assert (detail["failed"], detail["bonos_costo_fallidos"]) == (0, 1)
        assert _sell_dirty(engine) == []  # acked
        assert [(c[0], c[2], c[4]) for c in w.consumos(engine)] == [(linea, ref, 1)]  # the FIFO committed

    def test_a_sale_moved_to_another_product_moves_its_cost_bonus_row(self, engine: Engine) -> None:
        # GGA: the line is queued under its NEW product only; with no FIFO row, its OLD product was found nowhere and
        # the old row blocked the new one (unique per bonus and sale).
        b.bono_costo(engine, "3.00")
        _drain_bonos()
        ref = _fuera(engine, 2964, 1, D(2026, 10, 5))
        _drain_ventas()
        assert [r[1] for r in b.bono_consumos(engine)] == ["fuera"]
        assert [r[3] for r in b.bono_consumos(engine)] == [2964]

        w.update_venta(engine, "fuera", ref, item_id=2270)
        detail = _drain_ventas()

        assert (detail["failed"], "bonos_costo_fallidos" in detail) == (0, False)
        assert [(r[2], r[3]) for r in b.bono_consumos(engine)] == [(ref, 2270)]

    def test_a_drain_without_cost_bonus_failures_keeps_its_detail(self, engine: Engine) -> None:
        b.bono_costo(engine, "3.00")
        _drain_bonos()
        _fuera(engine, 2964, 1, D(2026, 10, 5))

        detail = _drain_ventas()

        assert "bonos_costo_fallidos" not in detail
        assert detail["failed"] == 0


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


def _compra_2964(engine: Engine) -> int:
    data = SellInCompraCreate(
        moneda="ARS",
        monto_total=Decimal("100.00"),
        formula="por_unidad",
        fecha_compra=D(2026, 10, 1),
        lineas=[SellInLineaIn(item_id=2964, cantidad=2, costo_base_unit=Decimal("1000"))],
    )
    with sessionmaker(bind=engine)() as db:
        return compras.crear_compra(db, data, usuario_id=7).id


def _estado_compras(engine: Engine):
    with engine.connect() as conn:
        return [r[0] for r in conn.execute(text("SELECT estado FROM sell_in_compras ORDER BY id"))]


@pytest.mark.postgres
class TestComprasNoBloquea:
    def test_a_purchase_commits_while_a_cost_bonus_of_its_product_cannot_be_computed(self, engine: Engine) -> None:
        b.bono_costo(engine, "3.00", incluye_iva=True)  # 2964 has no VAT rate
        _fuera(engine, 2964, 2, D(2026, 10, 5))
        _drain_bonos()
        _drain_ventas()
        assert _filas(engine) == []

        _compra_2964(engine)

        assert _estado_compras(engine) == ["activa"]
        assert len(w.consumos(engine)) == 1
        assert _filas(engine) == []

    def test_a_cost_bonus_error_rolls_back_only_its_savepoint_and_queues_its_bonuses(
        self, engine: Engine, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        bono = b.bono_costo(engine, "3.00")
        ref = _fuera(engine, 2964, 2, D(2026, 10, 5))
        _drain_bonos()
        _drain_ventas()
        antes = _filas(engine)
        assert antes == [(bono, ref, 2, Decimal("60.00"))]
        recalcular = bonos_costo.recalcular

        def _falla(db, item_ids=(), *, bono_ids=()):
            db.execute(text("DELETE FROM sell_in_bono_consumos"))  # written, then the error
            raise RuntimeError("boom")

        monkeypatch.setattr(bonos_costo, "recalcular", _falla)
        _compra_2964(engine)

        assert _estado_compras(engine) == ["activa"]
        assert [(c[2], c[4]) for c in w.consumos(engine)] == [(ref, 2)]
        assert _filas(engine) == antes  # the savepoint rolled back: the purchase committed with the old rows
        assert ("bono", bono) in b.queued(engine)  # verifier B1: queued with the purchase, so a drain repairs them

        monkeypatch.setattr(bonos_costo, "recalcular", recalcular)
        _drain_bonos()

        assert _filas(engine) == []  # the FIFO holds both units now: the cost bonus gives them nothing

    def test_a_lock_timeout_on_a_capped_bonus_queues_it_and_a_drain_removes_the_double_count(
        self, engine: Engine
    ) -> None:
        # Verifier B1, its repro: the capped bonus links 2270 to 2964; 2270's product lock is held while a purchase of
        # 2964 is loaded; the purchase commits its FIFO units and the cost bonus must not keep the same units.
        bono = b.bono_costo(engine, "3.00", tope_unidades=10)
        ref = _fuera(engine, 2964, 2, D(2026, 10, 5))
        _drain_bonos()
        _drain_ventas()
        assert _filas(engine) == [(bono, ref, 2, Decimal("60.00"))]
        b.clear_queue(engine)
        tomado, soltar = threading.Event(), threading.Event()

        def _holder() -> None:
            with engine.connect() as conn:
                with conn.begin():
                    conn.execute(text("SELECT pg_advisory_xact_lock(:ns, 2270)"), {"ns": LOCK_NAMESPACE})
                    tomado.set()
                    soltar.wait(15)

        hilo = threading.Thread(target=_holder)
        hilo.start()
        try:
            assert tomado.wait(5)
            _compra_2964(engine)
        finally:
            soltar.set()
            hilo.join()

        assert [(c[2], c[4]) for c in w.consumos(engine)] == [(ref, 2)]
        assert ("bono", bono) in b.queued(engine)

        _drain_bonos()

        assert _filas(engine) == []

    def test_a_purchase_never_waits_long_on_a_capped_bonus_s_other_products(self, engine: Engine) -> None:
        # The capped bonus links 2270 to 2964; another transaction holds 2270's product lock for a while.
        b.bono_costo(engine, "3.00", tope_unidades=10)
        _drain_bonos()
        tomado, soltar = threading.Event(), threading.Event()

        def _holder() -> None:
            with engine.connect() as conn:
                with conn.begin():
                    conn.execute(text("SELECT pg_advisory_xact_lock(:ns, 2270)"), {"ns": LOCK_NAMESPACE})
                    tomado.set()
                    soltar.wait(15)

        hilo = threading.Thread(target=_holder)
        hilo.start()
        try:
            assert tomado.wait(5)
            inicio = clock.monotonic()
            _compra_2964(engine)
            demora = clock.monotonic() - inicio
        finally:
            soltar.set()
            hilo.join()

        assert demora < 8
        assert _estado_compras(engine) == ["activa"]
