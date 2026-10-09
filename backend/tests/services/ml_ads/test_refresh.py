"""ml-billing-balance PR 1c-iii -- ADS-6 daily refresh, verify window and final days, over the captured replays.

The captured day bodies do not depend on the requested date, so the same real 2026-10-05 answer stands in for
every day of a window (a structural replay, as the task asks); money assertions stay in `test_ingestion_day.py`.
Seeded ledger rows are copies of the real `metrics_summary`; a test that perturbs one says so.
"""

from __future__ import annotations

import copy
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest

from app.core.config import settings
from app.models.ml_ads import MlAdsDayLedger
from app.services.ml_ads import schedule, store
from tests.services.ml_ads.replay import (
    GROUPS_RE,
    SUMMARY_RE,
    FakeClock,
    Replay,
    gauss_day,
    make_client,
    tplink_day,
)

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


def _tick(session_factory, replay, monkeypatch, *, token=None, refreshed_for=TODAY, deadline=None):
    client = make_client(replay, monkeypatch, token=token)
    return schedule.run_tick(
        session_factory, client, now=replay.clock.now, deadline=deadline, refreshed_for=refreshed_for
    )


def _ledger(db, advertiser_id, day) -> MlAdsDayLedger:
    return db.get(MlAdsDayLedger, ("product_ads", advertiser_id, day))


def _seed(db, advertiser_id, day, summary, *, status="closed", laps=0, closed_days_ago=30) -> None:
    """A ledger row as an earlier run left it; `summary` is the real `metrics_summary` (or a perturbed copy)."""
    closed_at = datetime(2026, 10, 8, 13, 0, tzinfo=timezone.utc) - timedelta(days=closed_days_ago)
    db.add(
        MlAdsDayLedger(
            source="product_ads",
            advertiser_id=advertiser_id,
            day=day,
            status=status,
            groups_offset=store.GROUPS_DONE,
            summary_cost=Decimal(str(summary["cost"])),
            summary_raw=summary,
            mismatch_laps=laps,
            closed_at=closed_at if status == "closed" else None,
        )
    )
    db.flush()


class TestDailyRefresh:
    def _closed_window(self, db, advertiser, summary, days, *, newest=1):
        for ago in range(newest, days + 1):
            _seed(db, advertiser, TODAY - timedelta(days=ago), summary)

    def test_the_first_run_of_the_day_reingests_d1_to_d3_exactly_once(
        self, session_factory, pg_ads_db, monkeypatch, window
    ) -> None:
        window(3)
        replay = Replay(FakeClock(), {GAUSS: gauss_day()}, advertisers=(GAUSS,))
        _tick(session_factory, replay, monkeypatch)
        before = len(replay.calls(GROUPS_RE))
        daily = _tick(session_factory, replay, monkeypatch, refreshed_for=TODAY - timedelta(days=1))
        assert sorted(s.day for s in daily.steps if s.outcome == "closed") == [
            date(2026, 10, 5),
            date(2026, 10, 6),
            date(2026, 10, 7),
        ]
        assert len(replay.calls(GROUPS_RE)) - before == 3 * 28
        assert daily.refreshed_for == TODAY

        before = len(replay.requests)
        catch_up = _tick(session_factory, replay, monkeypatch, refreshed_for=daily.refreshed_for)
        assert (catch_up.steps, len(replay.requests) - before) == ([], 1)

    def test_nothing_is_refreshed_before_the_10_30_slot(self, session_factory, monkeypatch, window) -> None:
        window(3)
        replay = Replay(FakeClock(), {GAUSS: gauss_day()}, advertisers=(GAUSS,))
        _tick(session_factory, replay, monkeypatch)
        early = FakeClock(datetime(2026, 10, 8, 12, 0, tzinfo=timezone.utc))  # 09:00 in Buenos Aires
        replay.clock = early
        tick = _tick(session_factory, replay, monkeypatch, refreshed_for=TODAY - timedelta(days=1))
        assert (tick.steps, tick.refreshed_for) == ([], TODAY - timedelta(days=1))

    def test_days_d4_to_d14_cost_one_summary_call_and_refetch_only_on_a_mismatch(
        self, session_factory, pg_ads_db, monkeypatch, window
    ) -> None:
        window(14)
        summary = tplink_day()["summary"]["metrics_summary"]
        self._closed_window(pg_ads_db, TPLINK, summary, 14)
        # Perturbed copy of the real summary: ML now reports another figure for D-6 than the ledger holds.
        changed = copy.deepcopy(summary)
        changed["cost"] = 500.0
        pg_ads_db.get(MlAdsDayLedger, ("product_ads", TPLINK, TODAY - timedelta(days=6))).summary_raw = changed
        pg_ads_db.flush()

        replay = Replay(FakeClock(), {TPLINK: tplink_day()}, advertisers=(TPLINK,))
        tick = _tick(session_factory, replay, monkeypatch, refreshed_for=TODAY - timedelta(days=1))

        d9, d6 = TODAY - timedelta(days=9), TODAY - timedelta(days=6)
        assert len(replay.calls_for_day(SUMMARY_RE, d9)) == 1
        assert replay.calls_for_day(GROUPS_RE, d9) == []
        assert len(replay.calls_for_day(GROUPS_RE, d6)) == 2  # reopened and refetched
        assert _ledger(pg_ads_db, TPLINK, d6).status == "closed"
        assert _ledger(pg_ads_db, TPLINK, d6).summary_cost == Decimal("0.0")
        assert _ledger(pg_ads_db, TPLINK, d9).verified_at is not None
        assert tick.complete

    def test_a_day_is_verified_once_per_local_day(self, session_factory, pg_ads_db, monkeypatch, window) -> None:
        window(5)
        summary = tplink_day()["summary"]["metrics_summary"]
        self._closed_window(pg_ads_db, TPLINK, summary, 5)
        replay = Replay(FakeClock(), {TPLINK: tplink_day()}, advertisers=(TPLINK,))
        _tick(session_factory, replay, monkeypatch, refreshed_for=TODAY)
        verified = len(replay.summary_calls())
        assert verified == 2  # D-4 and D-5
        _tick(session_factory, replay, monkeypatch, refreshed_for=TODAY)
        assert len(replay.summary_calls()) == verified

    def test_days_older_than_d14_become_final_without_a_call(
        self, session_factory, pg_ads_db, monkeypatch, window
    ) -> None:
        window(14)
        summary = tplink_day()["summary"]["metrics_summary"]
        self._closed_window(pg_ads_db, TPLINK, summary, 14)
        old, edge = TODAY - timedelta(days=15), TODAY - timedelta(days=14)
        _seed(pg_ads_db, TPLINK, old, summary)
        replay = Replay(FakeClock(), {TPLINK: tplink_day()}, advertisers=(TPLINK,))
        _tick(session_factory, replay, monkeypatch, refreshed_for=TODAY)
        assert (_ledger(pg_ads_db, TPLINK, old).final, _ledger(pg_ads_db, TPLINK, edge).final) == (True, False)
        assert replay.calls_for_day(SUMMARY_RE, old) == []

    def test_a_mismatch_is_retried_on_the_next_three_daily_runs_then_left(
        self, session_factory, pg_ads_db, monkeypatch, window
    ) -> None:
        window(8)
        day = copy.deepcopy(tplink_day())
        day["summary"]["metrics_summary"]["cost"] = 100.0  # perturbed real answer: groups (0) never add up to it
        summary = tplink_day()["summary"]["metrics_summary"]
        self._closed_window(pg_ads_db, TPLINK, summary, 8)
        stuck = TODAY - timedelta(days=8)
        ledger = _ledger(pg_ads_db, TPLINK, stuck)
        ledger.status = "mismatch"
        ledger.closed_at = None
        pg_ads_db.flush()

        replay = Replay(FakeClock(), {TPLINK: day}, advertisers=(TPLINK,))
        for _ in range(4):
            _tick(session_factory, replay, monkeypatch, refreshed_for=TODAY - timedelta(days=1))
        ledger = _ledger(pg_ads_db, TPLINK, stuck)
        assert (ledger.status, ledger.mismatch_laps) == ("mismatch", 3)
        assert len(replay.calls_for_day(GROUPS_RE, stuck)) == 3 * 2
