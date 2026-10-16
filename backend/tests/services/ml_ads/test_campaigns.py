"""ml-ads-campaigns -- the Product Ads campaigns of the day's `campaigns/search` call, persisted.

Every body is the real 2026-10-05 capture (`campaigns_summary_2026_10_05.json`). Tests that need another shape
(a listing split in two pages, a campaign gone from the list) deep-copy the real body and say so (DERIVED).
"""

from __future__ import annotations

import copy
from contextlib import contextmanager
from datetime import date, datetime, timezone
from decimal import Decimal

import httpx
import pytest
from sqlalchemy import func, select

from app.models.ml_ads import MlAdsCampaign, MlAdsCampaignDay
from app.services.ml_ads import ingestion, mapper
from tests.services.ml_ads.captures import load
from tests.services.ml_ads.replay import SUMMARY_RE, FakeClock, Replay, gauss_day, make_client

DAY = date(2026, 10, 5)
GAUSS = 25713
CANON = 7231635


def _gauss_body() -> dict:
    return load("campaigns_summary_2026_10_05.json")["25713"]["body"]


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


class TestMapCampaigns:
    def test_every_listed_campaign_maps_to_a_catalog_row_and_a_day_row(self) -> None:
        campaigns, days = mapper.map_campaigns(GAUSS, DAY, _gauss_body()["results"])
        assert len(campaigns) == len(days) == 16
        canon = next(c for c in campaigns if c["campaign_id"] == CANON)
        assert canon["name"] == "Canon"
        assert (canon["status"], canon["strategy"], canon["channel"]) == ("active", "PROFITABILITY", "marketplace")
        assert (canon["budget"], canon["daily_budget"], canon["automatic_budget"]) == (
            Decimal("20000.0"),
            Decimal("20000.0"),
            False,
        )
        assert (canon["acos_target"], canon["acos_top_search_target"], canon["roas_target"]) == (
            Decimal("21.98"),
            Decimal("0.0"),
            Decimal("4.55"),
        )
        assert canon["salesforce_event_id"] == 14
        assert canon["date_created"] == datetime(2026, 10, 3, 13, 53, 8, tzinfo=timezone.utc)
        assert "metrics" not in canon["raw"]

    def test_day_rows_carry_mls_metrics_and_add_up_to_the_day_total(self) -> None:
        _, days = mapper.map_campaigns(GAUSS, DAY, _gauss_body()["results"])
        canon = next(d for d in days if d["campaign_id"] == CANON)
        assert (canon["advertiser_id"], canon["day"], canon["cost"], canon["clicks"]) == (
            GAUSS,
            DAY,
            Decimal("30000.99"),
            72,
        )
        assert (canon["direct_amount"], canon["organic_units"], canon["organic_amount"]) == (
            Decimal("574955.0"),
            2,
            Decimal("754989.0"),
        )
        assert canon["raw"]["metrics"]["sov"] == 33.33
        assert sum(d["cost"] for d in days) == Decimal("614060.07")

    def test_an_entry_without_an_integer_id_is_ignored(self) -> None:
        results = _gauss_body()["results"][:2]
        del results[0]["id"]  # DERIVED: a real row with its id removed
        campaigns, days = mapper.map_campaigns(GAUSS, DAY, results)
        assert len(campaigns) == len(days) == 1


def _run(session_factory, replay, monkeypatch, step=ingestion.run_ads_step):
    client = make_client(replay, monkeypatch)
    return step(session_factory, client, GAUSS, DAY, now=replay.clock.now)


def _count(db, model) -> int:
    return db.execute(select(func.count()).select_from(model)).scalar_one()


class TestDayPipelinePersistsCampaigns:
    def test_the_days_summary_call_stores_every_campaign(self, session_factory, pg_ads_db, monkeypatch) -> None:
        replay = Replay(FakeClock(), {GAUSS: gauss_day()})
        assert _run(session_factory, replay, monkeypatch).outcome == "closed"
        assert len(replay.summary_calls()) == 1
        assert (_count(pg_ads_db, MlAdsCampaign), _count(pg_ads_db, MlAdsCampaignDay)) == (16, 16)
        day_cost = pg_ads_db.execute(select(func.sum(MlAdsCampaignDay.cost))).scalar_one()
        assert day_cost == Decimal("614060.07")
        assert pg_ads_db.get(MlAdsCampaign, (GAUSS, CANON)).name == "Canon"

    def test_a_listing_longer_than_its_first_page_is_read_to_the_end(
        self, session_factory, pg_ads_db, monkeypatch
    ) -> None:
        day = gauss_day()
        whole = day["summary"]["results"]
        # DERIVED: the real body split in two pages of 10 and 6, as ML pages a longer listing.
        day["summary"]["results"] = whole[:10]
        day["summary"]["paging"] = {"offset": 0, "total": 16, "limit": 10}
        second = {"paging": {"offset": 10, "total": 16, "limit": 50}, "results": whole[10:]}
        replay = Replay(FakeClock(), {GAUSS: day})
        replay.inject = lambda _, request: (
            httpx.Response(200, json=second)
            if SUMMARY_RE.search(request.url.path) and request.url.params.get("offset") == "10"
            else None
        )
        assert _run(session_factory, replay, monkeypatch).outcome == "closed"
        pages = [dict(r.url.params) for r in replay.summary_calls()]
        assert len(pages) == 2
        assert (pages[1]["offset"], pages[1]["limit"], "metrics_summary" in pages[1]) == ("10", "50", False)
        assert _count(pg_ads_db, MlAdsCampaignDay) == 16

    def test_verify_refreshes_the_day_and_drops_a_campaign_ml_no_longer_lists(
        self, session_factory, pg_ads_db, monkeypatch
    ) -> None:
        replay = Replay(FakeClock(), {GAUSS: gauss_day()})
        _run(session_factory, replay, monkeypatch)
        # DERIVED: the real body without its last (paused, zero) campaign.
        replay.days[GAUSS]["summary"] = copy.deepcopy(replay.days[GAUSS]["summary"])
        gone = replay.days[GAUSS]["summary"]["results"].pop()["id"]
        replay.days[GAUSS]["summary"]["paging"]["total"] = 15
        assert _run(session_factory, replay, monkeypatch, ingestion.verify_ads_day).outcome == "verified"
        assert pg_ads_db.get(MlAdsCampaignDay, (GAUSS, gone, DAY)) is None
        assert pg_ads_db.get(MlAdsCampaign, (GAUSS, gone)) is not None
        assert _count(pg_ads_db, MlAdsCampaignDay) == 15
