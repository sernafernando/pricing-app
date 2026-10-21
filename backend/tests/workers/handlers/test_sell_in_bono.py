"""`sell_in.bono` (sell-in-sell-out T3c-3): drains `sell_in_bono_dirty` and
reconciles the purchases the brand bonuses generate, then acks the keys.

Postgres only: claimed with `FOR UPDATE SKIP LOCKED` and fed by the live
triggers. Runs in a throwaway schema (`tests.services.sell_in._bono_world`).
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

from app.services.sell_in import bono_queue, bonos
from app.workers.context import WorkerContext
from app.workers.handlers.sell_in_bono import bono as handler
from app.workers.registry import REGISTRY
from tests.services.sell_in import _bono_world as b

D = date
_RECONCILIAR = bonos.reconciliar


@pytest.fixture(scope="module")
def engine() -> Iterator[Engine]:
    with b.world("sell_in_bono_handler") as engine:
        yield engine


@pytest.fixture(autouse=True)
def _db(monkeypatch: pytest.MonkeyPatch, engine: Engine) -> Iterator[None]:
    monkeypatch.setattr("app.core.database.SessionLocal", sessionmaker(bind=engine))
    yield
    b.clean(engine)


def _drain() -> dict:
    result = handler.run(WorkerContext(deadline=datetime.now(timezone.utc) + timedelta(seconds=30), worker_name="w"))
    assert result.success
    return result.detail


@pytest.mark.postgres
class TestBonoHandler:
    def test_it_is_registered_and_woken_by_its_channel_only(self) -> None:
        assert handler in REGISTRY
        assert handler.name == "sell_in.bono"
        assert handler.channels == (bono_queue.CHANNEL,) == ("sell_in_bono_dirty",)
        assert handler.interval is None and handler.run_at_local is None

    def test_a_new_bonus_applies_itself_to_the_invoiced_operations(self, engine: Engine) -> None:
        pedido = b.pedido(engine, {2964: 4})
        assert b.queued(engine) == []  # no bonus yet: the gate queues nothing
        bono = b.bono(engine, monto="1.50")
        assert b.queued(engine) == [("bono", bono)]

        detail = _drain()

        assert [(g[0], g[1], g[2], g[4]) for g in b.generadas(engine)] == [(bono, pedido, "activa", Decimal("6.00"))]
        assert b.queued(engine) == []
        assert detail == {"keys": 1, "batches": 1, "creadas": 1, "actualizadas": 0, "anuladas": 0, "failed": 0}

    def test_an_operation_invoiced_later_is_picked_up_by_itself(self, engine: Engine) -> None:
        bono = b.bono(engine)
        _drain()
        pedido = b.pedido(engine, {2964: 2}, None)
        _drain()
        assert b.generadas(engine) == []

        b.update_pedido(engine, pedido, fecha_factura=D(2026, 10, 15))  # the invoice gets linked
        _drain()

        assert [(g[0], g[1], g[2]) for g in b.generadas(engine)] == [(bono, pedido, "activa")]

    def test_an_empty_queue_does_nothing(self) -> None:
        assert _drain() == {"keys": 0, "batches": 0, "creadas": 0, "actualizadas": 0, "anuladas": 0, "failed": 0}

    def test_a_pair_without_rate_charges_its_keys_and_acks_the_rest(self, engine: Engine) -> None:
        ars = b.bono(engine, moneda="ARS")
        b.bono(engine, moneda="USD")
        sin_tc = b.pedido(engine, {2964: 1}, moneda="ARS", tipo_cambio=None)
        b.clear_queue(engine)
        b.update_pedido(engine, sin_tc, proveedor_id=32)  # queues only the operation

        detail = _drain()

        [(tipo, ref, attempts, error)] = b.queue_rows(engine)
        assert (tipo, ref, attempts) == ("pedido", sin_tc, 1)
        assert "tipo de cambio" in error
        assert detail["failed"] == 1
        # The ARS bonus did apply; the USD one waits for a rate.
        assert [g[0] for g in b.generadas(engine)] == [ars]

    def test_a_failing_batch_is_retried_one_key_at_a_time_and_only_the_bad_one_is_charged(
        self, engine: Engine, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        bueno = b.pedido(engine, {2964: 1})
        malo = b.pedido(engine, {2270: 1})
        bono_id = b.bono(engine)
        b.clear_queue(engine)
        b.update_pedido(engine, bueno, proveedor_id=32)
        b.update_pedido(engine, malo, proveedor_id=32)

        def _reconciliar(db, *, bono_ids=(), pedido_ids=()):
            if malo in set(pedido_ids):
                raise ValueError("dato roto")
            return _RECONCILIAR(db, bono_ids=bono_ids, pedido_ids=pedido_ids)

        monkeypatch.setattr(bonos, "reconciliar", _reconciliar)

        detail = _drain()

        assert b.queue_rows(engine) == [("pedido", malo, 1, "ValueError: dato roto")]
        assert [(g[0], g[1]) for g in b.generadas(engine)] == [(bono_id, bueno)]
        assert detail["failed"] == 1

    def test_a_transient_error_charges_nothing(self, engine: Engine, monkeypatch: pytest.MonkeyPatch) -> None:
        b.bono(engine)
        b.clear_queue(engine)
        pedido = b.pedido(engine, {2964: 1})

        calls = []

        def _caida(db, **kwargs):
            calls.append(kwargs)
            raise OperationalError("SELECT 1", {}, Exception("server closed the connection unexpectedly"))

        monkeypatch.setattr(bonos, "reconciliar", _caida)

        _drain()

        assert len(calls) == 1  # the run stops at once: no key-by-key retry against a dead database
        assert b.queue_rows(engine) == [("pedido", pedido, 0, None)]

    def test_a_transient_error_while_retrying_key_by_key_charges_nothing_either(
        self, engine: Engine, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        b.bono(engine)
        b.clear_queue(engine)
        pedido = b.pedido(engine, {2964: 1})
        calls = []

        def _falla(db, **kwargs):
            calls.append(kwargs)
            if len(calls) == 1:
                raise ValueError("el lote entero falló")
            raise OperationalError("SELECT 1", {}, Exception("server closed the connection unexpectedly"))

        monkeypatch.setattr(bonos, "reconciliar", _falla)

        _drain()

        assert len(calls) == 2  # the batch, then the key on its own
        assert b.queue_rows(engine) == [("pedido", pedido, 0, None)]


def _requeue(engine: Engine, key) -> None:
    """What a trigger does when the key's subject changes again: a new version of the row."""
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO sell_in_bono_dirty (tipo, ref) VALUES (:t, :r) ON CONFLICT (tipo, ref) "
                "DO UPDATE SET enqueued_at = clock_timestamp(), attempts = 0, last_error = NULL"
            ),
            {"t": key[0], "r": key[1]},
        )


def _rompe(monkeypatch: pytest.MonkeyPatch, malo: int) -> None:
    """The whole batch and the bad key on its own raise; the rest reconcile."""

    def _reconciliar(db, *, bono_ids=(), pedido_ids=()):
        if malo in set(pedido_ids):
            raise ValueError("dato roto")
        return _RECONCILIAR(db, bono_ids=bono_ids, pedido_ids=pedido_ids)

    monkeypatch.setattr(bonos, "reconciliar", _reconciliar)


@pytest.mark.postgres
class TestKeyByKeyCharge:
    def test_a_key_requeued_after_its_failure_is_not_charged(
        self, engine: Engine, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        b.bono(engine)
        b.clear_queue(engine)
        malo = b.pedido(engine, {2270: 1})
        _rompe(monkeypatch, malo)
        charge = bono_queue.charge

        def _charge_tras_reencolar(db, key, error, enqueued_at):
            _requeue(engine, key)  # a change lands between the failed transaction and the charge
            return charge(db, key, error, enqueued_at)

        monkeypatch.setattr(bono_queue, "charge", _charge_tras_reencolar)

        detail = _drain()

        assert b.queue_rows(engine) == [("pedido", malo, 0, None)]
        assert detail["failed"] == 0

    def test_the_charge_that_reaches_max_attempts_parks_the_key_and_logs_it(
        self, engine: Engine, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        b.bono(engine)
        b.clear_queue(engine)
        malo = b.pedido(engine, {2270: 1})
        with engine.begin() as conn:
            conn.execute(
                text("UPDATE sell_in_bono_dirty SET attempts = :n WHERE ref = :r"),
                {"n": bono_queue.MAX_ATTEMPTS - 1, "r": malo},
            )
        _rompe(monkeypatch, malo)

        with caplog.at_level(logging.ERROR, logger="app.workers.handlers.sell_in_bono"):
            _drain()

        assert b.queue_rows(engine) == [("pedido", malo, bono_queue.MAX_ATTEMPTS, "ValueError: dato roto")]
        assert [r.getMessage() for r in caplog.records if "parked" in r.getMessage()] == [
            f"sell_in.bono: pedido/{malo} parked after {bono_queue.MAX_ATTEMPTS} attempts; retried only when it "
            "changes again: ValueError: dato roto"
        ]

    def test_a_transient_error_while_charging_stops_the_run_and_keeps_its_counters(
        self, engine: Engine, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        b.bono(engine)
        b.clear_queue(engine)
        bueno = b.pedido(engine, {2964: 1})
        malo = b.pedido(engine, {2270: 1})
        despues = b.pedido(engine, {2964: 2})  # after the bad key: the stopped run leaves it queued
        _rompe(monkeypatch, malo)

        def _caida(db, key, error, enqueued_at):
            raise OperationalError("UPDATE", {}, Exception("server closed the connection unexpectedly"))

        monkeypatch.setattr(bono_queue, "charge", _caida)

        detail = _drain()  # no exception escapes the run

        assert b.queue_rows(engine) == [("pedido", malo, 0, None), ("pedido", despues, 0, None)]
        assert [g[1] for g in b.generadas(engine)] == [bueno]
        assert detail == {"keys": 3, "batches": 1, "creadas": 1, "actualizadas": 0, "anuladas": 0, "failed": 0}


@pytest.mark.postgres
class TestErrorsAndBatches:
    def test_the_joined_errors_of_many_failed_pairs_are_capped(
        self, engine: Engine, caplog: pytest.LogCaptureFixture
    ) -> None:
        for _ in range(30):
            b.bono(engine, moneda="USD")
        b.clear_queue(engine)
        sin_tc = b.pedido(engine, {2964: 1}, moneda="ARS", tipo_cambio=None)
        b.clear_queue(engine)
        b.update_pedido(engine, sin_tc, proveedor_id=32)  # queues only the operation: 30 failed pairs

        with caplog.at_level(logging.WARNING, logger="app.workers.handlers.sell_in_bono"):
            detail = _drain()

        [(_, _, attempts, error)] = b.queue_rows(engine)
        assert (attempts, detail["failed"]) == (1, 1)
        assert len(error) == 500
        assert error.startswith(f"El pedido {sin_tc} no tiene tipo de cambio")
        assert all(len(r.getMessage()) < 700 for r in caplog.records)

    def test_a_key_charged_in_an_early_batch_is_not_claimed_again_in_the_same_run(
        self, engine: Engine, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(bono_queue, "BATCH_SIZE", 2)
        b.bono(engine, moneda="USD")
        sin_tc = b.pedido(engine, {2964: 1}, moneda="ARS", tipo_cambio=None)  # queued first: batch 1
        buenos = [b.pedido(engine, {2964: 1}) for _ in range(3)]
        b.clear_queue(engine)
        for pedido in [sin_tc, *buenos]:
            b.update_pedido(engine, pedido, proveedor_id=32)

        detail = _drain()

        [(_, ref, attempts, _)] = b.queue_rows(engine)
        assert (ref, attempts) == (sin_tc, 1)  # charged once, never reclaimed by the later full batches
        assert sorted(g[1] for g in b.generadas(engine)) == sorted(buenos)
        assert (detail["keys"], detail["batches"], detail["failed"]) == (4, 2, 1)
