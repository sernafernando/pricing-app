"""ml-billing-balance PR 3-ii-b -- the bounded Display step of `schedule.run_tick` (ADS-9, D3, D4).

Product Ads days come from the captured full-day replays and Display from the captured 2026-10-05 answers of
advertiser 25713. Both are date-independent, so they stand in for other days structurally.
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


def _display_ledger(db, day) -> MlAdsDayLedger:
    return db.get(MlAdsDayLedger, ("display", GAUSS, day))


class TestSchedule:
    def test_display_runs_after_product_ads_for_25713_only(
        self, session_factory, pg_ads_db, monkeypatch, window
    ) -> None:
        window(1)
        replay = _replay()

        tick = _tick(session_factory, replay, monkeypatch)

        yesterday = TODAY - timedelta(days=1)
        assert [(s.advertiser_id, s.day, s.outcome) for s in tick.display_steps] == [(GAUSS, yesterday, "closed")]
        assert (tick.stopped, tick.complete) == (None, True)
        paths = [r.url.path for r in replay.requests]
        first_display = next(i for i, p in enumerate(paths) if "/display/" in p)
        # Nothing of Product Ads comes after (Brand Ads, which follows Display, is covered by test_brand_schedule).
        assert not any("/display/" not in p and "/brand_ads/" not in p for p in paths[first_display:])
        assert all(f"/advertisers/{GAUSS}/" in r.url.path for r in replay.display_calls())
        assert _display_ledger(pg_ads_db, yesterday).status == "closed"
        assert tick.as_detail()["display"]["steps"] == [
            {"advertiser_id": GAUSS, "day": yesterday.isoformat(), "outcome": "closed"}
        ]

    def test_closed_display_days_are_not_fetched_again(self, session_factory, monkeypatch, window) -> None:
        window(1)
        replay = _replay()
        _tick(session_factory, replay, monkeypatch)
        already = len(replay.requests)

        again = _tick(session_factory, replay, monkeypatch)

        assert (again.display_steps, again.complete) == ([], True)
        assert [r.url.path for r in replay.requests[already:]] == ["/advertising/advertisers"]

    def test_the_daily_refresh_refetches_the_recent_display_days_once(
        self, session_factory, pg_ads_db, monkeypatch, window
    ) -> None:
        window(3)
        replay = _replay()
        _tick(session_factory, replay, monkeypatch)  # refreshed_for == today: no daily refresh yet

        tick = _tick(session_factory, replay, monkeypatch, refreshed_for=None)

        assert sorted(s.day for s in tick.display_steps) == [TODAY - timedelta(days=n) for n in (3, 2, 1)]
        assert tick.refreshed_for == TODAY
        assert [_display_ledger(pg_ads_db, s.day).status for s in tick.display_steps] == ["closed"] * 3

    def test_a_display_failure_never_breaks_product_ads(self, session_factory, pg_ads_db, monkeypatch, window) -> None:
        window(1)
        replay = _replay()
        replay.inject = lambda n, request: httpx.Response(500) if "/display/" in request.url.path else None

        tick = _tick(session_factory, replay, monkeypatch)

        yesterday = TODAY - timedelta(days=1)
        assert pg_ads_db.get(MlAdsDayLedger, ("product_ads", GAUSS, yesterday)).status == "closed"
        assert [s.outcome for s in tick.display_steps] == ["error"]
        assert (tick.stopped, tick.complete) == (None, False)  # retried by the next catch-up run

    def test_an_exception_in_the_display_step_is_isolated_and_reported(
        self, session_factory, pg_ads_db, monkeypatch, window
    ) -> None:
        window(1)

        def boom(*args, **kwargs):
            raise RuntimeError("display exploded")

        monkeypatch.setattr(ingestion, "run_display_step", boom)

        tick = _tick(session_factory, _replay(), monkeypatch)

        yesterday = TODAY - timedelta(days=1)
        assert pg_ads_db.get(MlAdsDayLedger, ("product_ads", GAUSS, yesterday)).status == "closed"
        assert (tick.complete, tick.stopped) == (False, None)
        assert tick.as_detail()["display"]["error"] == "RuntimeError: display exploded"

    def test_a_rate_limit_in_display_stops_the_run_after_product_ads_finished(
        self, session_factory, pg_ads_db, monkeypatch, window
    ) -> None:
        window(1)
        replay = _replay()
        replay.inject = lambda n, request: httpx.Response(429) if "/display/" in request.url.path else None

        tick = _tick(session_factory, replay, monkeypatch)

        yesterday = TODAY - timedelta(days=1)
        assert pg_ads_db.get(MlAdsDayLedger, ("product_ads", GAUSS, yesterday)).status == "closed"
        assert (tick.stopped, tick.complete) == ("rate_limited", False)

    def test_display_is_not_started_when_product_ads_ran_out_of_time(
        self, session_factory, monkeypatch, window
    ) -> None:
        window(2)
        replay = _replay()

        tick = _tick(session_factory, replay, monkeypatch, deadline=replay.clock.now() + timedelta(seconds=30))

        assert (tick.stopped, tick.display_steps, replay.display_calls()) == ("deadline", [], [])
