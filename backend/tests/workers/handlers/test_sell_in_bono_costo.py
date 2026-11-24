"""The % of cost sell-in bonus (sell-in-sell-out T25b) in the workers: `sell.drain` recomputes it right after the
FIFO for the drained products, `sell_in.bono` for a created, edited or voided bonus, and every path that moves the
FIFO (the invoice reconcile, voiding a manual purchase) brings it along, so the exclusivity with invoice-based sell in
always reads the FIFO's current units.

Postgres only, in a throwaway schema (`tests.services.sell_in._bono_world`)."""

from __future__ import annotations

import threading
import time as clock
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Iterator

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.orm import sessionmaker

from app.schemas.sell_in import SellInCompraCreate, SellInLineaIn
from app.services.sell_in import compras
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
    def test_a_drain_without_cost_bonus_failures_keeps_its_detail(self, engine: Engine) -> None:
        b.bono_costo(engine, "3.00")
        _drain_bonos()
        _fuera(engine, 2964, 1, D(2026, 10, 5))

        detail = _drain_ventas()

        assert "bonos_costo_fallidos" not in detail
        assert detail["failed"] == 0


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
