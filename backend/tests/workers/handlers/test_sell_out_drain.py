"""`sell_out.drain` (sell-in-sell-out T7 S3): drains `sell_out_dirty`, rebuilds
the queued campaigns (`asignacion.recalcular`) and acks them; a campaign that
keeps failing is charged and parks.

Postgres only: claimed with `FOR UPDATE SKIP LOCKED`. Runs in a throwaway schema
(`tests.services.sell_out._world`).
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Iterator

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import sessionmaker

from app.services.sell_out import asignacion
from app.services.sell_out import queue as so_queue
from app.workers.context import WorkerContext
from app.workers.handlers.sell_out_drain import ERROR_MAX
from app.workers.handlers.sell_out_drain import drain as handler
from app.workers.registry import REGISTRY
from tests.services.sell_out import _world as w

pytestmark = pytest.mark.postgres

D = date
ROUTERS = {"marca": "TP-LINK", "categoria": "Routers"}
SWITCHES = {"marca": "TP-LINK", "categoria": "Switches"}
_RECALCULAR = asignacion.recalcular
_DEAD = OperationalError("SELECT 1", {}, Exception("server closed the connection unexpectedly"))


@pytest.fixture(scope="module")
def engine() -> Iterator[Engine]:
    with w.world("sell_out_drain") as engine:
        yield engine


@pytest.fixture(autouse=True)
def _db(monkeypatch: pytest.MonkeyPatch, engine: Engine) -> Iterator[None]:
    monkeypatch.setattr("app.core.database.SessionLocal", sessionmaker(bind=engine))
    yield
    w.clean(engine)


def _drain() -> dict:
    result = handler.run(WorkerContext(deadline=datetime.now(timezone.utc) + timedelta(seconds=30), worker_name="w"))
    assert result.success
    return result.detail


def _queue(engine: Engine, *ids: int) -> None:
    with sessionmaker(bind=engine)() as db:
        so_queue.enqueue(db, ids)
        db.commit()


def _rompe(monkeypatch: pytest.MonkeyPatch, malo: int, error: Exception = ValueError("dato roto")) -> list:
    """Every rebuild that includes `malo` raises; the rest rebuild. Returns the calls."""
    calls = []

    def _recalcular(db, ids):
        calls.append(sorted(ids))
        if malo in set(ids):
            raise error
        return _RECALCULAR(db, ids)

    monkeypatch.setattr(asignacion, "recalcular", _recalcular)
    return calls


class TestDrain:
    def test_it_is_registered_and_woken_by_its_channel_only(self) -> None:
        assert handler in REGISTRY
        assert handler.name == "sell_out.drain"
        assert handler.channels == (so_queue.CHANNEL,) == ("sell_out_dirty",)
        assert handler.interval is None and handler.run_at_local is None

    def test_a_queued_campaign_is_rebuilt_and_leaves_the_queue(self, engine: Engine) -> None:
        cid = w.campana(engine, [w.grupo(engine, [ROUTERS])])
        ref = w.venta(engine, "fuera", 2964, 2, D(2026, 11, 2))
        _queue(engine, cid)

        detail = _drain()

        assert [(r[0], r[2], r[5], r[6]) for r in w.consumos(engine)] == [(cid, ref, 2, Decimal("20.00"))]
        assert w.queued(engine) == []
        assert detail == {"campanas": 1, "batches": 1, "inserted": 1, "deleted": 0, "pendientes_base": 0, "failed": 0}

    def test_an_empty_queue_does_nothing(self) -> None:
        assert _drain() == {"campanas": 0, "batches": 0, "inserted": 0, "deleted": 0, "pendientes_base": 0, "failed": 0}

    def test_sales_waiting_for_their_base_are_counted(self, engine: Engine) -> None:
        cid = w.campana(engine, [w.grupo(engine, [ROUTERS])], tipo="porcentaje", monto_unit=None, porcentaje="5")
        ref = w.venta(engine, "ml", 2964, 1, D(2026, 11, 2))
        w.execute(engine, "UPDATE ml_sale_lines SET mcosto = 0 WHERE item_row_id = :r", r=ref)  # not settled yet
        _queue(engine, cid)

        assert _drain()["pendientes_base"] == 1
        assert w.queued(engine) == []

    def test_a_campaign_without_its_rate_is_charged_with_the_allocator_message(self, engine: Engine) -> None:
        cid = w.campana(
            engine, [w.grupo(engine, [ROUTERS])], moneda="USD", tc_modo="dia_venta", monto_unit="1.00"
        )  # no BNA rate loaded at all
        w.venta(engine, "fuera", 2964, 1, D(2026, 11, 2))
        _queue(engine, cid)

        detail = _drain()

        [(campana, attempts, error)] = w.queued(engine)
        assert (campana, attempts, detail["failed"]) == (cid, 1, 1)
        assert error.startswith("SellOutAsignacionError: ") and "no BNA rate" in error

    def test_a_failing_batch_is_retried_one_campaign_at_a_time_and_only_the_bad_one_is_charged(
        self, engine: Engine, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        bueno = w.campana(engine, [w.grupo(engine, [ROUTERS])])
        malo = w.campana(engine, [w.grupo(engine, [SWITCHES])])
        ref = w.venta(engine, "fuera", 2964, 1, D(2026, 11, 2))
        _queue(engine, bueno, malo)
        calls = _rompe(monkeypatch, malo)

        detail = _drain()

        assert calls == [[bueno, malo], [bueno], [malo]]
        assert w.queued(engine) == [(malo, 1, "ValueError: dato roto")]
        assert [(r[0], r[2]) for r in w.consumos(engine)] == [(bueno, ref)]
        assert (detail["campanas"], detail["failed"]) == (2, 1)

    def test_a_campaign_charged_in_an_early_batch_is_not_claimed_again_in_the_same_run(
        self, engine: Engine, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(so_queue, "BATCH_SIZE", 2)
        g = w.grupo(engine, [ROUTERS])
        malo, *buenos = [w.campana(engine, [g]) for _ in range(4)]
        for cid in (malo, *buenos):  # queued in this order: the bad one goes in batch 1
            _queue(engine, cid)
        calls = _rompe(monkeypatch, malo)

        detail = _drain()

        assert w.queued(engine) == [(malo, 1, "ValueError: dato roto")]
        assert sum(malo in c for c in calls) == 2  # its batch, then itself; never reclaimed
        assert (detail["campanas"], detail["batches"], detail["failed"]) == (4, 2, 1)

    def test_errors_are_capped(self, engine: Engine, monkeypatch: pytest.MonkeyPatch) -> None:
        malo = w.campana(engine, [w.grupo(engine, [ROUTERS])])
        _queue(engine, malo)
        _rompe(monkeypatch, malo, ValueError("x" * 2000))

        _drain()

        [(_, _, error)] = w.queued(engine)
        assert len(error) == ERROR_MAX == 500


class TestChargeAndPark:
    def test_a_campaign_requeued_after_its_failure_is_not_charged(
        self, engine: Engine, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        malo = w.campana(engine, [w.grupo(engine, [ROUTERS])])
        _queue(engine, malo)
        _rompe(monkeypatch, malo)
        charge = so_queue.charge

        def _charge_tras_reencolar(db, campana_id, error, enqueued_at):
            with engine.begin() as conn:  # a change lands between the failed transaction and the charge
                conn.execute(
                    text("UPDATE sell_out_dirty SET enqueued_at = clock_timestamp() WHERE campana_id = :c"),
                    {"c": campana_id},
                )
            return charge(db, campana_id, error, enqueued_at)

        monkeypatch.setattr(so_queue, "charge", _charge_tras_reencolar)

        detail = _drain()

        assert w.queued(engine) == [(malo, 0, None)]
        assert detail["failed"] == 0

    def test_the_charge_that_reaches_max_attempts_parks_it_and_logs_it(
        self, engine: Engine, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        malo = w.campana(engine, [w.grupo(engine, [ROUTERS])])
        _queue(engine, malo)
        w.execute(engine, "UPDATE sell_out_dirty SET attempts = :n", n=so_queue.MAX_ATTEMPTS - 1)
        _rompe(monkeypatch, malo)

        with caplog.at_level(logging.ERROR, logger="app.workers.handlers.sell_out_drain"):
            _drain()
        _drain()  # parked: not claimed again

        assert w.queued(engine) == [(malo, so_queue.MAX_ATTEMPTS, "ValueError: dato roto")]
        assert [r.getMessage() for r in caplog.records if "parked" in r.getMessage()] == [
            f"sell_out.drain: campaign {malo} parked after {so_queue.MAX_ATTEMPTS} attempts; retried only when it "
            "is queued again: ValueError: dato roto"
        ]

    def test_a_transient_error_charges_nothing(self, engine: Engine, monkeypatch: pytest.MonkeyPatch) -> None:
        cid = w.campana(engine, [w.grupo(engine, [ROUTERS])])
        _queue(engine, cid)
        calls = _rompe(monkeypatch, cid, _DEAD)

        _drain()

        assert len(calls) == 1  # the run stops at once: no one-by-one retry against a dead database
        assert w.queued(engine) == [(cid, 0, None)]

    def test_a_transient_error_while_retrying_one_by_one_charges_nothing_either(
        self, engine: Engine, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        cid = w.campana(engine, [w.grupo(engine, [ROUTERS])])
        _queue(engine, cid)
        calls = []

        def _falla(db, ids):
            calls.append(ids)
            raise ValueError("el lote entero falló") if len(calls) == 1 else _DEAD

        monkeypatch.setattr(asignacion, "recalcular", _falla)

        _drain()

        assert len(calls) == 2
        assert w.queued(engine) == [(cid, 0, None)]

    def test_a_transient_error_while_charging_stops_the_run(
        self, engine: Engine, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        g = w.grupo(engine, [ROUTERS])
        malo, despues = w.campana(engine, [g]), w.campana(engine, [w.grupo(engine, [SWITCHES])])
        _queue(engine, malo)
        _queue(engine, despues)
        _rompe(monkeypatch, malo)

        def _caida(db, campana_id, error, enqueued_at):
            raise _DEAD

        monkeypatch.setattr(so_queue, "charge", _caida)

        detail = _drain()  # no exception escapes the run

        assert w.queued(engine) == [(malo, 0, None), (despues, 0, None)]
        assert detail["failed"] == 0
