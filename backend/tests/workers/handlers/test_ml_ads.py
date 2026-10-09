"""`ml_ads.ingest` (ml-billing-balance PR 1c): ADS-5/ADS-7 through the real worker contract.

Postgres only. The ML side is the real client over the captured replays of `tests/fixtures/ml_ads/`;
the flag-off test uses a transport that fails the test on any request.
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import date, datetime, time, timedelta, timezone

import httpx
import pytest
from sqlalchemy import func, select

from app.core.config import settings
from app.models.ml_ads import MlAdsDayLedger
from app.models.worker_job_state import WorkerJobState
from app.services.ml_publications.ml_http import MlHttpClient
from app.services.ml_publications.pacing import Pacer
from app.workers import registry
from app.workers.context import WorkerContext
from app.workers.handlers import ml_ads
from app.workers.scheduling import is_due
from tests.services.ml_ads.replay import FakeClock, Replay, gauss_day, make_client

pytestmark = pytest.mark.postgres

GAUSS = 25713
TODAY = date(2026, 10, 8)


@pytest.fixture()
def session_factory(pg_ads_db):
    @contextmanager
    def factory():
        try:
            yield pg_ads_db
            pg_ads_db.commit()
        except Exception:
            pg_ads_db.rollback()
            raise

    return factory


@pytest.fixture()
def enabled(monkeypatch):
    monkeypatch.setattr(settings, "ML_ADS_ENABLED", True)
    monkeypatch.setattr(settings, "ML_ADS_RETENTION_DAYS", 1)  # a one-day window: yesterday


def make_handler(session_factory, replay, monkeypatch, *, token=None) -> ml_ads.AdsHandler:
    client = make_client(replay, monkeypatch, token=token)
    return ml_ads.AdsHandler(client_factory=lambda pacer: client, session_factory=session_factory, now=replay.clock.now)


def context(replay, seconds: float = 3600.0) -> WorkerContext:
    return WorkerContext(deadline=replay.clock.now() + timedelta(seconds=seconds), worker_name="worker-ml")


class TestFlag:
    def test_with_the_flag_off_nothing_is_called_and_nothing_is_written(
        self, session_factory, pg_ads_db, monkeypatch
    ) -> None:
        assert settings.ML_ADS_ENABLED is False  # the default in code
        calls: list[httpx.Request] = []

        class NoCall(httpx.BaseTransport):
            def handle_request(self, request):
                calls.append(request)
                pytest.fail(f"unexpected ML call: {request.url}")

        clock = FakeClock()
        client = MlHttpClient(
            pacer=Pacer(clock=clock),
            transport=NoCall(),
            token_loader=lambda: {"access_token": "t", "expires_epoch": 9e12},
        )
        handler = ml_ads.AdsHandler(client_factory=lambda pacer: client, session_factory=session_factory, now=clock.now)
        result = handler.run(WorkerContext(deadline=clock.now() + timedelta(seconds=30)))
        # Not a success: the runtime then keeps the handler due, so enabling the flag runs it on the next pass.
        assert (result.success, result.detail, calls) == (False, {"disabled": True}, [])
        assert pg_ads_db.execute(select(func.count()).select_from(MlAdsDayLedger)).scalar_one() == 0
        assert pg_ads_db.execute(select(func.count()).select_from(WorkerJobState)).scalar_one() == 0


class TestSchedule:
    def test_daily_at_10_30_with_a_60_second_catch_up_and_no_notify_channel(self) -> None:
        handler = ml_ads.ads
        assert handler.name == "ml_ads.ingest"
        assert (handler.run_at_local, handler.interval, handler.channels) == (time(10, 30), None, ())
        assert handler.catch_up_interval == timedelta(seconds=60)
        assert handler in registry.ML_PUBLICATIONS_REGISTRY

    def test_an_incomplete_run_unlocks_the_catch_up_and_a_complete_one_waits_for_the_next_slot(self) -> None:
        handler = ml_ads.ads
        noon = datetime(2026, 10, 8, 15, 0, tzinfo=timezone.utc)
        last = noon - timedelta(minutes=2)
        assert is_due(handler, now=noon, last_success_at=last, incomplete=True)
        assert not is_due(handler, now=noon, last_success_at=last, incomplete=False)

    def test_a_run_spends_at_most_15_seconds_on_calls(self, enabled, session_factory, pg_ads_db, monkeypatch) -> None:
        replay = Replay(FakeClock(), {GAUSS: gauss_day()}, advertisers=(GAUSS,))
        result = make_handler(session_factory, replay, monkeypatch).run(context(replay, seconds=3600))
        assert len(replay.requests) == 15  # the advertisers list and 14 pages, one second each on the fake clock
        assert (result.success, result.detail["complete"], result.detail["stopped"]) == (True, False, "deadline")


class TestRun:
    def test_a_finished_pass_reports_complete_and_keeps_only_a_summary_in_detail(
        self, enabled, session_factory, pg_ads_db, monkeypatch
    ) -> None:
        replay = Replay(FakeClock(), {GAUSS: gauss_day()}, advertisers=(GAUSS,))
        handler = make_handler(session_factory, replay, monkeypatch)
        # 15 s per run: a day of 109 calls needs several runs, each one resuming from the ledger.
        for _ in range(20):
            result = handler.run(context(replay))
            replay.clock.advance(60)
            if result.detail["complete"]:
                break
        ledger = pg_ads_db.get(MlAdsDayLedger, ("product_ads", GAUSS, TODAY - timedelta(days=1)))
        assert (ledger.status, result.detail["complete"]) == ("closed", True)
        detail = pg_ads_db.get(WorkerJobState, "ml_ads.ingest").detail
        assert set(detail) == {"at", "complete", "refreshed_for", "stopped", "calls", "steps", "display", "brand"}
        assert detail["display"] == {
            "error": None,
            "steps": [{"advertiser_id": GAUSS, "day": (TODAY - timedelta(days=1)).isoformat(), "outcome": "closed"}],
        }
        assert detail["brand"] == {
            "error": None,
            "steps": [{"advertiser_id": GAUSS, "day": (TODAY - timedelta(days=1)).isoformat(), "outcome": "closed"}],
        }
        assert detail["refreshed_for"] == TODAY.isoformat()

    def test_deleting_the_detail_loses_no_progress(self, enabled, session_factory, pg_ads_db, monkeypatch) -> None:
        replay = Replay(FakeClock(), {GAUSS: gauss_day()}, advertisers=(GAUSS,))
        handler = make_handler(session_factory, replay, monkeypatch)
        handler.run(context(replay))
        read = len(replay.group_pages())
        assert 0 < read < 28
        pg_ads_db.delete(pg_ads_db.get(WorkerJobState, "ml_ads.ingest"))
        pg_ads_db.flush()
        replay.clock.advance(60)
        handler.run(context(replay))
        # The ledger, not the detail, is the cursor: the pages already read are not asked again.
        assert replay.group_pages()[read] == read * 200

    def test_a_missing_token_is_a_finished_run_that_names_the_reason(
        self, enabled, session_factory, pg_ads_db, monkeypatch
    ) -> None:
        replay = Replay(FakeClock(), {GAUSS: gauss_day()}, advertisers=(GAUSS,))
        result = make_handler(session_factory, replay, monkeypatch, token={}).run(context(replay))
        assert (result.success, result.detail["complete"], result.detail["stopped"]) == (True, True, "blocked")
        assert replay.requests == []
