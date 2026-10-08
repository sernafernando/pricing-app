"""ml-billing-balance PR 1c -- ADS-5 backfill order and stop conditions, over the captured replays.

The captured day bodies do not depend on the requested date, so the same real 2026-10-05 answer stands in for
every day of a window (a structural replay); money assertions stay in `test_ingestion_day.py`.
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import date, timedelta

import httpx
import pytest

from app.core.config import settings
from app.models.ml_ads import MlAdsDayLedger
from app.services.ml_ads import schedule, store
from tests.services.ml_ads.replay import ADVERTISERS_RE, FakeClock, Replay, gauss_day, make_client, tplink_day

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


def _tick(session_factory, replay, monkeypatch, *, token=None, deadline=None):
    client = make_client(replay, monkeypatch, token=token)
    return schedule.run_tick(session_factory, client, now=replay.clock.now, deadline=deadline)


def _ledger(db, advertiser_id, day) -> MlAdsDayLedger:
    return db.get(MlAdsDayLedger, ("product_ads", advertiser_id, day))


class TestBackfillOrder:
    def test_missing_days_are_ingested_oldest_first_one_advertiser_day_at_a_time(
        self, session_factory, pg_ads_db, monkeypatch, window
    ) -> None:
        window(3)
        replay = Replay(FakeClock(), {GAUSS: gauss_day()}, advertisers=(GAUSS,))
        tick = _tick(session_factory, replay, monkeypatch)
        assert [s.day for s in tick.steps] == [date(2026, 10, 5), date(2026, 10, 6), date(2026, 10, 7)]
        assert [s.outcome for s in tick.steps] == ["closed"] * 3
        assert (tick.stopped, tick.complete, tick.calls) == (
            None,
            True,
            3 * 109 + 1,
        )  # three days and the advertisers list
        assert len(replay.calls(ADVERTISERS_RE)) == 1

    def test_every_advertiser_of_a_day_is_done_before_the_next_day(
        self, session_factory, pg_ads_db, monkeypatch, window
    ) -> None:
        window(2)
        replay = Replay(FakeClock(), {GAUSS: gauss_day(), TPLINK: tplink_day()})
        tick = _tick(session_factory, replay, monkeypatch)
        assert [(s.advertiser_id, s.day.day) for s in tick.steps] == [(GAUSS, 6), (TPLINK, 6), (GAUSS, 7), (TPLINK, 7)]

    def test_an_unfinished_day_is_resumed_before_any_missing_one(
        self, session_factory, pg_ads_db, monkeypatch, window
    ) -> None:
        window(3)
        replay = Replay(FakeClock(), {GAUSS: gauss_day()}, advertisers=(GAUSS,))
        # Day 10-07 was left `fetching` by an earlier run that was cut off.
        store.start_fetch(pg_ads_db, GAUSS, date(2026, 10, 7), now=replay.clock.now())
        tick = _tick(session_factory, replay, monkeypatch)
        assert [s.day for s in tick.steps] == [date(2026, 10, 7), date(2026, 10, 5), date(2026, 10, 6)]

    def test_closed_days_are_never_fetched_again(self, session_factory, monkeypatch, window) -> None:
        window(3)
        replay = Replay(FakeClock(), {GAUSS: gauss_day()}, advertisers=(GAUSS,))
        _tick(session_factory, replay, monkeypatch)
        already = len(replay.requests)
        again = _tick(session_factory, replay, monkeypatch)
        assert (again.steps, again.complete) == ([], True)
        assert [r.url.path for r in replay.requests[already:]] == ["/advertising/advertisers"]

    def test_rate_limit_stops_the_run_and_leaves_the_day_open_for_the_next_one(
        self, session_factory, pg_ads_db, monkeypatch, window
    ) -> None:
        window(2)
        replay = Replay(FakeClock(), {GAUSS: gauss_day()}, advertisers=(GAUSS,))
        replay.inject = lambda n, request: httpx.Response(429, headers={"retry-after": "60"}) if n == 40 else None
        first = _tick(session_factory, replay, monkeypatch)
        assert (first.stopped, first.complete) == ("rate_limited", False)
        assert _ledger(pg_ads_db, GAUSS, date(2026, 10, 6)).status == "fetching"
        assert _ledger(pg_ads_db, GAUSS, date(2026, 10, 7)) is None  # the next day was not started
        replay.inject = None
        second = _tick(session_factory, replay, monkeypatch)
        assert (second.stopped, second.complete) == (None, True)
        assert [_ledger(pg_ads_db, GAUSS, d).status for d in (date(2026, 10, 6), date(2026, 10, 7))] == ["closed"] * 2

    def test_deadline_ends_the_run_incomplete_and_the_next_run_continues(
        self, session_factory, pg_ads_db, monkeypatch, window
    ) -> None:
        window(2)
        replay = Replay(FakeClock(), {GAUSS: gauss_day()}, advertisers=(GAUSS,))
        first = _tick(session_factory, replay, monkeypatch, deadline=replay.clock.now() + timedelta(seconds=30))
        assert (first.stopped, first.complete, first.calls) == ("deadline", False, 30)
        assert _ledger(pg_ads_db, GAUSS, date(2026, 10, 6)).status == "fetching"
        second = _tick(session_factory, replay, monkeypatch)
        assert (second.stopped, second.complete) == (None, True)
        assert [_ledger(pg_ads_db, GAUSS, d).status for d in (date(2026, 10, 6), date(2026, 10, 7))] == ["closed"] * 2

    def test_a_missing_token_blocks_without_spinning(self, session_factory, monkeypatch, window) -> None:
        window(2)
        replay = Replay(FakeClock(), {GAUSS: gauss_day()}, advertisers=(GAUSS,))
        tick = _tick(session_factory, replay, monkeypatch, token={})
        assert (tick.stopped, tick.complete, replay.requests) == ("blocked", True, [])

    def test_an_unreadable_advertisers_list_ends_the_run_before_any_day(
        self, session_factory, pg_ads_db, monkeypatch, window
    ) -> None:
        window(2)
        replay = Replay(FakeClock(), {GAUSS: gauss_day()})
        replay.inject = lambda n, request: httpx.Response(503) if ADVERTISERS_RE.search(request.url.path) else None
        tick = _tick(session_factory, replay, monkeypatch)
        assert (tick.stopped, tick.complete, tick.steps, len(replay.requests)) == ("error", False, [], 1)

    def test_a_poison_day_does_not_block_the_others(self, session_factory, pg_ads_db, monkeypatch, window) -> None:
        window(2)
        replay = Replay(FakeClock(), {GAUSS: gauss_day()}, advertisers=(GAUSS,))
        replay.inject = lambda n, request: (
            httpx.Response(500) if request.url.params.get("date_from") == "2026-10-06" else None
        )
        tick = _tick(session_factory, replay, monkeypatch)
        assert [(s.day, s.outcome) for s in tick.steps] == [(date(2026, 10, 6), "error"), (date(2026, 10, 7), "closed")]
        assert (tick.stopped, tick.complete) == (None, False)  # the failed day is retried by the next run
