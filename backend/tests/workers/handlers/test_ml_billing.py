"""`ml_billing.sweep` (ml-billing-balance PR 4c-i): the billing lap as a worker handler (BS-8, D12).

The ML side is the real client object with its three billing methods scripted from the captured
periods page; the lock is the shared `cursor_name='billing'` one.
"""

from __future__ import annotations

import json
from datetime import datetime, time, timedelta, timezone
from pathlib import Path
from unittest import mock

import pytest

from app.core.config import settings
from app.models.ml_orders_ops import MlOpsSyncCursor
from app.models.worker_job_state import WorkerJobState
from app.services.ml_billing import billing_lap, billing_sweep_service
from app.services.ml_orders_ingestion import sweep_service
from app.services.ml_webhook_client import BillingFetch, ml_webhook_client
from app.workers import registry
from app.workers.context import WorkerContext
from app.workers.handlers import ml_billing
from app.workers.scheduling import is_due

NOW = datetime(2026, 10, 9, 8, 17, tzinfo=timezone.utc)
PERIODS = json.loads(
    (Path(__file__).resolve().parents[2] / "fixtures" / "ml_billing" / "periods_bill.json").read_text()
)["body"]


def _ctx(db):
    class _Ctx:
        def __enter__(self):
            return db

        def __exit__(self, *a):
            db.commit()
            return False

    return lambda: _Ctx()


class Clock:
    def __init__(self) -> None:
        self.at = NOW

    def __call__(self) -> datetime:
        return self.at


@pytest.fixture()
def clock(db, monkeypatch):
    monkeypatch.setattr(sweep_service, "get_background_db", _ctx(db))
    monkeypatch.setattr(billing_sweep_service, "get_background_db", _ctx(db))
    monkeypatch.setattr(settings, "ML_BILLING_ENABLED", True)
    return Clock()


@pytest.fixture()
def client():
    with (
        mock.patch.object(
            ml_webhook_client, "get_billing_periods", new=mock.AsyncMock(return_value=PERIODS)
        ) as periods,
        mock.patch.object(
            ml_webhook_client,
            "fetch_billing_details",
            new=mock.AsyncMock(return_value=BillingFetch(status=429, body=None, error="HTTP 429")),
        ) as details,
    ):
        yield mock.Mock(periods=periods, details=details)


def make_handler(db, clock, pacer=None) -> ml_billing.BillingHandler:
    pacer = pacer or mock.Mock(acquire=mock.Mock(return_value="granted"))
    return ml_billing.BillingHandler(pacer=pacer, session_factory=_ctx(db), now=clock)


def run(handler, clock, seconds: float = 3600.0):
    return handler.run(WorkerContext(deadline=clock() + timedelta(seconds=seconds), worker_name="worker-ml"))


def detail(db):
    return db.query(WorkerJobState).filter_by(name="ml_billing.sweep").one().detail


class TestFlagAndLock:
    def test_with_the_flag_off_nothing_is_called_and_nothing_is_written(self, db, clock, client, monkeypatch) -> None:
        monkeypatch.setattr(settings, "ML_BILLING_ENABLED", False)
        result = run(make_handler(db, clock), clock)
        assert (result.success, result.detail) == (False, {"disabled": True})
        assert (client.periods.call_count, client.details.call_count) == (0, 0)
        assert db.query(WorkerJobState).count() == 0 and db.query(MlOpsSyncCursor).count() == 0

    def test_a_leftover_cron_run_holding_the_billing_lock_excludes_the_tick(self, db, clock, client) -> None:
        db.add(MlOpsSyncCursor(name="billing", state="running", detail=NOW.isoformat()))
        db.commit()
        result = run(make_handler(db, clock), clock)
        assert result.success is True and client.periods.call_count == 0
        assert detail(db)["complete"] is False  # the catch-up retries; the lock is not ours to release
        assert db.query(MlOpsSyncCursor).filter_by(name="billing").one().state == "running"

    def test_the_lock_is_released_after_every_tick(self, db, clock, client) -> None:
        run(make_handler(db, clock), clock)
        assert db.query(MlOpsSyncCursor).filter_by(name="billing").one().state == "idle"


class TestTicks:
    def test_one_request_per_run_and_a_run_inside_15_seconds_makes_none(self, db, clock, client) -> None:
        handler = make_handler(db, clock)
        run(handler, clock)
        assert client.periods.call_count == 1 and detail(db)["complete"] is False
        clock.at = NOW + timedelta(seconds=5)
        run(handler, clock)
        assert (client.periods.call_count, client.details.call_count) == (1, 0)
        clock.at = NOW + timedelta(seconds=15)
        run(handler, clock)
        assert client.details.call_count == 1  # the first unit of the lap: BILL details of the OPEN period

    def test_the_request_goes_through_the_shared_ml_pacer(self, db, clock, client) -> None:
        pacer = mock.Mock(acquire=mock.Mock(return_value="granted"))
        run(make_handler(db, clock, pacer), clock)
        pacer.acquire.assert_called_once()

    def test_a_pacer_refusing_at_the_deadline_makes_no_request(self, db, clock, client) -> None:
        pacer = mock.Mock(acquire=mock.Mock(return_value="deadline"))
        result = run(make_handler(db, clock, pacer), clock)
        assert result.success is True and client.periods.call_count == 0

    def test_the_request_runs_with_only_the_tick_session_open(self, db, clock, client, monkeypatch) -> None:
        open_now, seen = [0], []
        inner = _ctx(db)

        class Counted:
            def __enter__(self):
                open_now[0] += 1
                return inner().__enter__()

            def __exit__(self, *a):
                open_now[0] -= 1
                return inner().__exit__(*a)

        real = billing_lap.run_billing_tick

        def spy(session, state, now):
            seen.append(open_now[0])
            return real(session, state, now)

        monkeypatch.setattr(billing_lap, "run_billing_tick", spy)
        handler = ml_billing.BillingHandler(
            pacer=mock.Mock(acquire=mock.Mock(return_value="granted")), session_factory=Counted, now=clock
        )
        run(handler, clock)
        assert seen == [1]  # the lock session is closed and nothing is held while the proxy answers

    def test_a_crash_inside_the_tick_keeps_the_worker_alive_and_the_catch_up_on(
        self, db, clock, client, monkeypatch
    ) -> None:
        monkeypatch.setattr(billing_lap, "run_billing_tick", mock.Mock(side_effect=RuntimeError("boom")))
        result = run(make_handler(db, clock), clock)
        assert result.success is True and result.error == "RuntimeError: boom"
        assert detail(db)["complete"] is False
        assert db.query(MlOpsSyncCursor).filter_by(name="billing").one().state == "error"


class TestSchedule:
    def test_daily_at_05_17_with_a_15_second_catch_up_and_no_notify_channel(self) -> None:
        handler = ml_billing.billing
        assert handler.name == "ml_billing.sweep"
        assert (handler.run_at_local, handler.interval, handler.channels) == (time(5, 17), None, ())
        assert handler.catch_up_interval == timedelta(seconds=15)

    def test_an_incomplete_lap_unlocks_the_catch_up_and_a_complete_one_waits_for_the_next_slot(self) -> None:
        noon = datetime(2026, 10, 9, 15, 0, tzinfo=timezone.utc)
        last = noon - timedelta(seconds=20)
        assert is_due(ml_billing.billing, now=noon, last_success_at=last, incomplete=True)
        assert not is_due(ml_billing.billing, now=noon, last_success_at=last, incomplete=False)

    def test_the_registry_holds_exactly_one_billing_scheduler(self) -> None:
        names = [h.name for h in registry.ML_PUBLICATIONS_REGISTRY]
        assert names.count("ml_billing.sweep") == 1
        assert registry.ML_PUBLICATIONS_REGISTRY[-1] is ml_billing.billing
        assert not [h for h in registry.REGISTRY if h.name.startswith("ml_billing")]


class TestNoCron:
    def test_crontab_has_no_billing_sync_entry(self) -> None:
        crontab = (Path(__file__).resolve().parents[4] / "crontab_fixed.txt").read_text()
        assert "sync_ml_billing" not in crontab
