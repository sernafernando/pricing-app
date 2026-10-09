"""ml-billing-balance PR 3-i -- Display per campaign per day: endpoints, mapper, store (ADS-9, D5, D11).

Replays the real Display responses of 2026-10-05 (advertiser 25713) captured in
`tests/fixtures/ml_ads/display_day_2026_10_05_25713.json`. Display is account-level: no MLA, no ad group.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal

import pytest
import sqlalchemy as sa

from app.models.ml_ads import MlAdsDisplayCampaignDay
from app.services.ml_ads import endpoints, mapper, store
from tests.services.ml_ads.captures import load

DAY = date(2026, 10, 5)
ADVERTISER = 25713
NOW = datetime(2026, 10, 8, 14, 0, tzinfo=timezone.utc)
WITH_SPEND = {335306: "27226.79", 301232: "49464.21", 294806: "68.67", 259859: "45179.15"}
WITHOUT_ACTIVITY = (340339, 290925, 281280)


def _facts() -> list[mapper.DisplayFact]:
    capture = load("display_day_2026_10_05_25713.json")
    facts: list[mapper.DisplayFact] = []
    for campaign_id, response in capture["metrics"].items():
        facts += mapper.map_display_metrics(ADVERTISER, int(campaign_id), DAY, response["body"])
    return facts


class TestEndpoints:
    def test_requests_match_the_captured_calls(self) -> None:
        capture = load("display_day_2026_10_05_25713.json")

        campaigns = endpoints.display_campaigns_request(ADVERTISER, DAY)
        metrics = endpoints.display_metrics_request(ADVERTISER, 335306, DAY)

        for built, captured in ((campaigns, capture["campaigns"]), (metrics, capture["metrics"]["335306"])):
            assert built.path == captured["request"]["path"]
            assert dict(built.params) == captured["request"]["params"]
            # Display is Api-Version 1 (D5), not the Product Ads version 2.
            assert dict(built.headers) == {"Api-Version": captured["request"]["api_version"]} == {"Api-Version": "1"}

    def test_ids_in_the_path_are_digits_only(self) -> None:
        with pytest.raises(ValueError):
            endpoints.display_metrics_request(ADVERTISER, "1/../2", DAY)
        with pytest.raises(ValueError):
            endpoints.display_campaigns_request("25713/x", DAY)


class TestMapper:
    def test_campaign_ids_come_from_the_campaign_list(self) -> None:
        body = load("display_day_2026_10_05_25713.json")["campaigns"]["body"]
        assert mapper.parse_display_campaigns(body) == [259859, 281280, 290925, 294806, 301232, 335306, 340339]

    def test_only_campaigns_with_activity_become_facts(self) -> None:
        facts = _facts()

        assert {f.campaign_id: str(f.consumed_budget) for f in facts} == WITH_SPEND
        assert not {f.campaign_id for f in facts} & set(WITHOUT_ACTIVITY)

    def test_fact_carries_the_captured_figures_and_raw(self) -> None:
        fact = next(f for f in _facts() if f.campaign_id == 335306)
        entry = load("display_day_2026_10_05_25713.json")["metrics"]["335306"]["body"]["metrics"][0]

        assert (fact.advertiser_id, fact.day) == (ADVERTISER, DAY)
        assert (fact.prints, fact.clicks, fact.reach) == (12576, 21, 3498)
        assert fact.consumed_budget == Decimal("27226.79")
        assert dict(fact.raw) == entry

    def test_a_row_for_another_date_is_not_a_fact_of_this_day(self) -> None:
        body = load("display_day_2026_10_05_25713.json")["metrics"]["335306"]["body"]
        body["metrics"][0]["date"] = "2026-10-04"  # deep copy of a real body, perturbed in the test only

        assert mapper.map_display_metrics(ADVERTISER, 335306, DAY, body) == []

    def test_spend_free_activity_still_counts(self) -> None:
        body = load("display_day_2026_10_05_25713.json")["metrics"]["294806"]["body"]
        body["metrics"][0]["consumed_budget"] = 0.0  # prints 13, reach 12 remain

        (fact,) = mapper.map_display_metrics(ADVERTISER, 294806, DAY, body)
        assert fact.consumed_budget == 0


@pytest.mark.postgres
class TestStore:
    def _count(self, db) -> int:
        return db.execute(sa.select(sa.func.count()).select_from(MlAdsDisplayCampaignDay)).scalar_one()

    def test_upsert_stores_one_row_per_campaign_and_day(self, pg_ads_db) -> None:
        store.upsert_display_days(pg_ads_db, _facts(), now=NOW)

        rows = pg_ads_db.execute(sa.select(MlAdsDisplayCampaignDay)).scalars().all()
        assert {r.campaign_id: str(r.consumed_budget) for r in rows} == WITH_SPEND
        assert {(r.advertiser_id, r.day) for r in rows} == {(ADVERTISER, DAY)}
        assert all(r.raw["date"] == "2026-10-05" for r in rows)

    def test_replaying_the_day_is_idempotent_and_refreshes_the_figures(self, pg_ads_db) -> None:
        store.upsert_display_days(pg_ads_db, _facts(), now=NOW)
        store.upsert_display_days(pg_ads_db, _facts(), now=NOW)
        assert self._count(pg_ads_db) == 4

        body = load("display_day_2026_10_05_25713.json")["metrics"]["335306"]["body"]
        body["metrics"][0]["consumed_budget"] = 27500.5  # ML restated the day
        store.upsert_display_days(pg_ads_db, mapper.map_display_metrics(ADVERTISER, 335306, DAY, body), now=NOW)

        assert self._count(pg_ads_db) == 4
        stored = pg_ads_db.get(MlAdsDisplayCampaignDay, (ADVERTISER, 335306, DAY))
        assert stored.consumed_budget == Decimal("27500.50")

    def test_display_never_creates_per_mla_facts(self, pg_ads_db) -> None:
        store.upsert_display_days(pg_ads_db, _facts(), now=NOW)

        for table in ("ml_ads_item_days", "ml_ads_ad_group_days"):
            assert pg_ads_db.execute(sa.text(f"SELECT count(*) FROM {table}")).scalar_one() == 0
