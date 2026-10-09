"""ml-billing-balance PR 3-ii-a -- Display day ingestion (ADS-9): one `(advertiser, day)` per `run_display_step`.

The ML side is the real client over the captured Display answers of advertiser 25713, 2026-10-05 (one
`display/campaigns` call and one `metrics` call per campaign). A test that swaps or perturbs a real body says so.
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import date, timedelta

import httpx
import pytest
import sqlalchemy as sa

from app.models.ml_ads import MlAdsDayLedger, MlAdsDisplayCampaignDay
from app.services.ml_ads import ingestion
from tests.services.ml_ads.replay import (
    DISPLAY_CAMPAIGNS_RE,
    DISPLAY_METRICS_RE,
    FakeClock,
    Replay,
    gauss_display,
    make_client,
)

pytestmark = pytest.mark.postgres

DAY = date(2026, 10, 5)
GAUSS = 25713
WITH_SPEND = {335306: "27226.79", 301232: "49464.21", 294806: "68.67", 259859: "45179.15"}
CAMPAIGNS = [259859, 281280, 290925, 294806, 301232, 335306, 340339]


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


def _replay(**kwargs) -> Replay:
    return Replay(FakeClock(), {}, **kwargs)  # no Product Ads day: Display is its own pipeline


def _step(session_factory, replay, monkeypatch, day=DAY, **kwargs):
    client = make_client(replay, monkeypatch)
    return ingestion.run_display_step(session_factory, client, GAUSS, day, now=replay.clock.now, **kwargs)


def _display_ledger(db, day=DAY) -> MlAdsDayLedger:
    return db.get(MlAdsDayLedger, ("display", GAUSS, day))


def _spend(db) -> dict[int, str]:
    rows = db.execute(sa.select(MlAdsDisplayCampaignDay)).scalars().all()
    return {r.campaign_id: str(r.consumed_budget) for r in rows}


def _metrics_paths(replay) -> list[int]:
    return [
        int(DISPLAY_METRICS_RE.search(r.url.path).group(2)) for r in replay.display_calls() if "metrics" in r.url.path
    ]


class TestDisplayDay:
    def test_one_campaigns_call_then_one_metrics_call_per_campaign_and_the_day_closes(
        self, session_factory, pg_ads_db, monkeypatch
    ) -> None:
        replay = _replay()

        step = _step(session_factory, replay, monkeypatch)

        assert (step.outcome, step.status, step.calls) == ("closed", "closed", 1 + len(CAMPAIGNS))
        assert len(replay.calls(DISPLAY_CAMPAIGNS_RE)) == 1
        assert _metrics_paths(replay) == CAMPAIGNS  # id order, each campaign exactly once
        assert _spend(pg_ads_db) == WITH_SPEND
        ledger = _display_ledger(pg_ads_db)
        # The campaign count is recorded so a truncated list would be visible; Display has no ML day total of ours.
        assert (ledger.status, ledger.summary_raw, ledger.summary_cost) == ("closed", {"campaigns": 7}, None)
        assert pg_ads_db.get(MlAdsDayLedger, ("product_ads", GAUSS, DAY)) is None

    def test_a_day_without_campaigns_closes_with_a_count_of_zero(self, session_factory, pg_ads_db, monkeypatch) -> None:
        display = gauss_display()
        display["campaigns"]["results"] = []  # a real body emptied: the day has no Display campaigns at all
        replay = _replay(display={GAUSS: display})

        step = _step(session_factory, replay, monkeypatch)

        assert (step.outcome, step.calls) == ("closed", 1)
        assert (_display_ledger(pg_ads_db).summary_raw, _spend(pg_ads_db)) == ({"campaigns": 0}, {})

    def test_refetching_drops_a_campaign_that_lost_its_activity(self, session_factory, pg_ads_db, monkeypatch) -> None:
        _step(session_factory, _replay(), monkeypatch)
        assert set(_spend(pg_ads_db)) == set(WITH_SPEND)

        display = gauss_display()
        # ML restated the day: 335306 now answers like 340339 did (a real body with no row for the day).
        display["metrics"][335306] = display["metrics"][340339]
        replay = _replay(display={GAUSS: display})
        replay.clock.advance(3600)
        _step(session_factory, replay, monkeypatch)

        assert set(_spend(pg_ads_db)) == set(WITH_SPEND) - {335306}
        assert _display_ledger(pg_ads_db).status == "closed"

    def test_rows_of_another_day_survive_a_refetch(self, session_factory, pg_ads_db, monkeypatch) -> None:
        _step(session_factory, _replay(), monkeypatch)
        next_day = DAY + timedelta(days=1)
        display = gauss_display()
        for body in display["metrics"].values():
            for row in body["metrics"]:
                row["date"] = next_day.isoformat()  # real bodies re-dated in the test only
        replay = _replay(display={GAUSS: display})
        replay.clock.advance(3600)
        _step(session_factory, replay, monkeypatch, day=next_day)

        days = pg_ads_db.execute(sa.select(MlAdsDisplayCampaignDay.day).distinct()).scalars().all()
        assert sorted(days) == [DAY, next_day]


class TestCursor:
    def test_a_deadline_mid_day_resumes_at_the_next_campaign(self, session_factory, pg_ads_db, monkeypatch) -> None:
        replay = _replay()

        first = _step(session_factory, replay, monkeypatch, deadline=replay.clock.now() + timedelta(seconds=4))

        assert (first.outcome, first.status, first.calls) == ("deadline", "fetching", 4)
        assert _display_ledger(pg_ads_db).groups_offset == 3  # list + campaigns 0..2 done
        second = _step(session_factory, replay, monkeypatch)
        assert (second.outcome, second.calls) == ("closed", 1 + 4)
        assert sorted(_metrics_paths(replay)) == CAMPAIGNS  # every campaign fetched exactly once across both runs
        assert _spend(pg_ads_db) == WITH_SPEND

    def test_a_429_keeps_what_was_stored_and_the_cursor(self, session_factory, pg_ads_db, monkeypatch) -> None:
        replay = _replay()
        replay.inject = lambda n, request: httpx.Response(429, headers={"retry-after": "60"}) if n == 6 else None

        step = _step(session_factory, replay, monkeypatch)

        assert (step.outcome, step.status) == ("rate_limited", "fetching")
        assert _display_ledger(pg_ads_db).groups_offset == 4
        assert set(_spend(pg_ads_db)) == {259859, 294806}  # the campaigns before the cursor that had activity

    def test_a_5xx_counts_one_attempt_and_leaves_the_day_for_a_later_run(
        self, session_factory, pg_ads_db, monkeypatch
    ) -> None:
        replay = _replay()
        replay.inject = lambda n, request: httpx.Response(503) if n == 1 else None

        step = _step(session_factory, replay, monkeypatch)

        ledger = _display_ledger(pg_ads_db)
        assert (step.outcome, ledger.attempts, ledger.last_error) == ("error", 1, "HTTP 503")
        assert _spend(pg_ads_db) == {}
