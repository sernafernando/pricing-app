"""ml-ads-campaigns PR C -- the campaigns of days already closed (D-15 and older) are read once (T4).

Every `campaigns/search` answer is the real 2026-10-05 capture of each advertiser
(`campaigns_summary_2026_10_05.json`), date-independent, so it stands in for other days structurally. The
Product Ads, Display and Brand Ads days are seeded closed so the tick has only the backfill left to do.
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import date, timedelta
from decimal import Decimal

import httpx
import pytest
from sqlalchemy import func, select

from app.core.config import settings
from app.models.ml_ads import MlAdsCampaign, MlAdsCampaignDay, MlAdsDayLedger
from app.services.ml_ads import read, schedule
from tests.services.ml_ads.replay import START, SUMMARY_RE, FakeClock, Replay, gauss_day, make_client, tplink_day

pytestmark = pytest.mark.postgres

TODAY = date(2026, 10, 8)
GAUSS = 25713
TPLINK = 714700
D15 = TODAY - timedelta(days=15)
D16 = TODAY - timedelta(days=16)
COST_SOURCES = ("product_ads", "display", "brand_ads")


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
def closed_window(pg_ads_db, monkeypatch):
    """A 16-day window whose Product Ads, Display and Brand Ads days are already closed (minus `leave`)."""

    def seed(*, leave: tuple[tuple[str, date], ...] = ()) -> None:
        monkeypatch.setattr(settings, "ML_ADS_RETENTION_DAYS", 16)
        for n in range(1, 17):
            day = TODAY - timedelta(days=n)
            for source in COST_SOURCES:
                if (source, day) in leave:
                    continue
                for advertiser in (GAUSS, TPLINK) if source != "display" else (GAUSS,):
                    pg_ads_db.add(
                        MlAdsDayLedger(
                            source=source, advertiser_id=advertiser, day=day, status="closed", closed_at=START
                        )
                    )
        pg_ads_db.commit()

    return seed


def _replay() -> Replay:
    return Replay(FakeClock(), {GAUSS: gauss_day(), TPLINK: tplink_day()})


def _tick(session_factory, replay, monkeypatch):
    client = make_client(replay, monkeypatch)
    return schedule.run_tick(session_factory, client, now=replay.clock.now, deadline=None, refreshed_for=TODAY)


def _campaign_days(db, advertiser: int, day: date) -> tuple[int, Decimal]:
    count, cost = db.execute(
        select(func.count(), func.coalesce(func.sum(MlAdsCampaignDay.cost), 0)).where(
            MlAdsCampaignDay.advertiser_id == advertiser, MlAdsCampaignDay.day == day
        )
    ).one()
    return count, Decimal(cost)


class TestCampaignsBackfill:
    def test_closed_days_older_than_d14_get_their_campaigns_once_per_advertiser_day(
        self, session_factory, pg_ads_db, monkeypatch, closed_window
    ) -> None:
        closed_window()
        replay = _replay()

        tick = _tick(session_factory, replay, monkeypatch)

        assert sorted((s.advertiser_id, s.day, s.outcome) for s in tick.campaigns_steps) == [
            (GAUSS, D16, "closed"),
            (GAUSS, D15, "closed"),
            (TPLINK, D16, "closed"),
            (TPLINK, D15, "closed"),
        ]
        assert sorted(r.url.params["date_from"] for r in replay.calls(SUMMARY_RE)) == sorted(
            [D16.isoformat()] * 2 + [D15.isoformat()] * 2
        )
        for day in (D15, D16):
            assert _campaign_days(pg_ads_db, GAUSS, day) == (16, Decimal("614060.07"))
            assert _campaign_days(pg_ads_db, TPLINK, day)[0] == 7
            ledger = pg_ads_db.get(MlAdsDayLedger, ("campaigns", GAUSS, day))
            assert (ledger.status, ledger.summary_cost) == ("closed", Decimal("614060.07"))
        newer = pg_ads_db.execute(
            select(func.count()).where(MlAdsDayLedger.source == "campaigns", MlAdsDayLedger.day > D15)
        ).scalar()
        assert newer == 0  # D-14..D-1 are read by the day fetch and the verify
        assert (tick.stopped, tick.complete) == (None, True)
        assert tick.as_detail()["campaigns"]["error"] is None

    def test_an_old_day_adds_missing_catalog_rows_but_never_overwrites_the_latest(
        self, session_factory, pg_ads_db, monkeypatch, closed_window
    ) -> None:
        closed_window()
        # DERIVED: a catalog row as a newer day's call left it (the name stands in for any newer value).
        pg_ads_db.add(MlAdsCampaign(advertiser_id=GAUSS, campaign_id=7231635, name="newer", raw={}))
        pg_ads_db.commit()

        _tick(session_factory, _replay(), monkeypatch)

        assert pg_ads_db.get(MlAdsCampaign, (GAUSS, 7231635)).name == "newer"
        catalog = pg_ads_db.execute(select(func.count()).where(MlAdsCampaign.advertiser_id == GAUSS)).scalar()
        assert catalog == 16  # the other 15 campaigns of the listing are added

    def test_a_backfilled_day_is_not_read_again(self, session_factory, monkeypatch, closed_window) -> None:
        closed_window()
        replay = _replay()
        _tick(session_factory, replay, monkeypatch)
        already = len(replay.requests)

        again = _tick(session_factory, replay, monkeypatch)

        assert (again.campaigns_steps, again.complete) == ([], True)
        assert [r.url.path for r in replay.requests[already:]] == ["/advertising/advertisers"]

    def test_a_campaigns_failure_never_breaks_the_other_sources(
        self, session_factory, pg_ads_db, monkeypatch, closed_window
    ) -> None:
        closed_window(leave=(("product_ads", TODAY - timedelta(days=1)),))
        replay = _replay()
        old = (D15.isoformat(), D16.isoformat())
        replay.inject = lambda n, request: (
            httpx.Response(500)
            if SUMMARY_RE.search(request.url.path) and request.url.params["date_from"] in old
            else None
        )

        tick = _tick(session_factory, replay, monkeypatch)

        assert pg_ads_db.get(MlAdsDayLedger, ("product_ads", GAUSS, TODAY - timedelta(days=1))).status == "closed"
        assert [s.outcome for s in tick.campaigns_steps] == ["error"] * 4  # each unit tried once, then skipped
        assert (tick.stopped, tick.complete) == (None, False)  # the next catch-up run retries them

    def test_display_and_brand_still_fetch_up_to_yesterday(self, session_factory, monkeypatch, closed_window) -> None:
        yesterday = TODAY - timedelta(days=1)
        closed_window(leave=(("display", yesterday), ("brand_ads", yesterday)))

        tick = _tick(session_factory, _replay(), monkeypatch)

        assert [(s.advertiser_id, s.day) for s in tick.display_steps] == [(GAUSS, yesterday)]
        assert sorted((s.advertiser_id, s.day) for s in tick.brand_steps) == [(GAUSS, yesterday), (TPLINK, yesterday)]

    def test_the_campaigns_cursor_is_not_ads_coverage(self, pg_ads_db, closed_window) -> None:
        closed_window()
        pg_ads_db.add(MlAdsDayLedger(source="campaigns", advertiser_id=GAUSS, day=D16, status="closed"))
        pg_ads_db.commit()

        got = read.ads_coverage(pg_ads_db, D16, TODAY - timedelta(days=1), today=TODAY)

        assert (got.missing_days, got.mismatch_days) == ([], [])  # D-15..D-1 have no campaigns row, by design
