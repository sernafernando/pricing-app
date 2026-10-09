"""ml-billing-balance PR 3-iii -- the bounded Brand Ads step of `schedule.run_tick` (ADS-10, D3, D4).

Product Ads and Display come from the captured replays; Brand Ads from the captured 2026-10-05 answers of both
advertisers (date-independent, so they stand in for other days structurally).
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import date, timedelta

import httpx
import pytest

from app.core.config import settings
from app.models.ml_ads import MlAdsDayLedger
from app.services.ml_ads import ingestion, schedule
from tests.services.ml_ads.replay import FakeClock, Replay, gauss_day, make_client, tplink_day

pytestmark = pytest.mark.postgres

TODAY = date(2026, 10, 8)
YESTERDAY = TODAY - timedelta(days=1)
GAUSS = 25713
TPLINK = 714700


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
def window(monkeypatch):
    def set_days(days: int) -> None:
        monkeypatch.setattr(settings, "ML_ADS_RETENTION_DAYS", days)

    return set_days


def _replay(**kwargs) -> Replay:
    return Replay(FakeClock(), {GAUSS: gauss_day(), TPLINK: tplink_day()}, **kwargs)


def _tick(session_factory, replay, monkeypatch, *, refreshed_for=TODAY, deadline=None):
    client = make_client(replay, monkeypatch)
    return schedule.run_tick(
        session_factory, client, now=replay.clock.now, deadline=deadline, refreshed_for=refreshed_for
    )


def _ledger(db, source, advertiser, day) -> MlAdsDayLedger:
    return db.get(MlAdsDayLedger, (source, advertiser, day))


class TestSchedule:
    def test_brand_runs_after_display_for_every_advertiser(
        self, session_factory, pg_ads_db, monkeypatch, window
    ) -> None:
        window(1)
        replay = _replay()

        tick = _tick(session_factory, replay, monkeypatch)

        assert sorted((s.advertiser_id, s.day, s.outcome) for s in tick.brand_steps) == [
            (GAUSS, YESTERDAY, "closed"),
            (TPLINK, YESTERDAY, "closed"),
        ]
        assert (tick.stopped, tick.complete) == (None, True)
        paths = [r.url.path for r in replay.requests]
        first_brand = next(i for i, p in enumerate(paths) if "/brand_ads/" in p)
        assert not any("/display/" in p for p in paths[first_brand:])  # nothing of Display comes after
        assert all(_ledger(pg_ads_db, "brand_ads", a, YESTERDAY).status == "closed" for a in (GAUSS, TPLINK))
        assert tick.as_detail()["brand"]["steps"] == [
            {"advertiser_id": s.advertiser_id, "day": YESTERDAY.isoformat(), "outcome": "closed"}
            for s in tick.brand_steps
        ]

    def test_closed_brand_days_are_not_fetched_again(self, session_factory, monkeypatch, window) -> None:
        window(1)
        replay = _replay()
        _tick(session_factory, replay, monkeypatch)
        already = len(replay.requests)

        again = _tick(session_factory, replay, monkeypatch)

        assert (again.brand_steps, again.complete) == ([], True)
        assert [r.url.path for r in replay.requests[already:]] == ["/advertising/advertisers"]

    def test_the_daily_refresh_refetches_the_recent_brand_days_once(
        self, session_factory, pg_ads_db, monkeypatch, window
    ) -> None:
        window(3)
        replay = _replay()
        _tick(session_factory, replay, monkeypatch)

        tick = _tick(session_factory, replay, monkeypatch, refreshed_for=None)

        days = [TODAY - timedelta(days=n) for n in (3, 2, 1)]
        assert sorted((s.advertiser_id, s.day) for s in tick.brand_steps) == sorted(
            (a, d) for a in (GAUSS, TPLINK) for d in days
        )
        assert len(replay.brand_calls()) == 12  # 6 days at the first tick, 6 refetched; none repeated within a run

    def test_a_brand_failure_never_breaks_product_ads_or_display(
        self, session_factory, pg_ads_db, monkeypatch, window
    ) -> None:
        window(1)
        replay = _replay()
        replay.inject = lambda n, request: httpx.Response(500) if "/brand_ads/" in request.url.path else None

        tick = _tick(session_factory, replay, monkeypatch)

        assert _ledger(pg_ads_db, "product_ads", GAUSS, YESTERDAY).status == "closed"
        assert _ledger(pg_ads_db, "display", GAUSS, YESTERDAY).status == "closed"
        assert [s.outcome for s in tick.brand_steps] == ["error", "error"]  # each advertiser tried once, then skipped
        assert (tick.stopped, tick.complete) == (None, False)  # retried by the next catch-up run

    def test_an_exception_in_the_brand_step_is_isolated_and_reported(
        self, session_factory, pg_ads_db, monkeypatch, window
    ) -> None:
        window(1)

        def boom(*args, **kwargs):
            raise RuntimeError("brand exploded")

        monkeypatch.setattr(ingestion, "run_brand_step", boom)

        tick = _tick(session_factory, _replay(), monkeypatch)

        assert _ledger(pg_ads_db, "display", GAUSS, YESTERDAY).status == "closed"
        assert (tick.complete, tick.stopped) == (False, None)
        assert tick.as_detail()["brand"]["error"] == "RuntimeError: brand exploded"

    def test_a_rate_limit_in_brand_stops_the_run_after_the_rest_finished(
        self, session_factory, pg_ads_db, monkeypatch, window
    ) -> None:
        window(1)
        replay = _replay()
        replay.inject = lambda n, request: httpx.Response(429) if "/brand_ads/" in request.url.path else None

        tick = _tick(session_factory, replay, monkeypatch)

        assert _ledger(pg_ads_db, "display", GAUSS, YESTERDAY).status == "closed"
        assert (tick.stopped, tick.complete) == ("rate_limited", False)

    def test_a_display_exception_does_not_keep_brand_from_running(
        self, session_factory, pg_ads_db, monkeypatch, window
    ) -> None:
        window(1)
        monkeypatch.setattr(ingestion, "run_display_step", lambda *a, **k: 1 / 0)

        tick = _tick(session_factory, _replay(), monkeypatch)

        assert tick.display_error is not None
        assert _ledger(pg_ads_db, "brand_ads", GAUSS, YESTERDAY).status == "closed"

    def test_brand_is_not_started_when_an_earlier_step_ran_out_of_time(
        self, session_factory, monkeypatch, window
    ) -> None:
        window(2)
        replay = _replay()

        tick = _tick(session_factory, replay, monkeypatch, deadline=replay.clock.now() + timedelta(seconds=30))

        assert (tick.stopped, tick.brand_steps, replay.brand_calls()) == ("deadline", [], [])
