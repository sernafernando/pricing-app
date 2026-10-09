"""ml-billing-balance PR 3-iii -- Brand Ads per advertiser per day: endpoint, mapper, store (ADS-10, D5, D11).

Replays the real Brand Ads answers of 2026-10-05 (both advertisers) captured in
`tests/fixtures/ml_ads/brand_ads_day_2026_10_05.json`. Every figure of that day is zero, so the non-zero mapping
is exercised only on a deep copy of a real body whose day value is edited IN THE TEST (said where it happens): it
checks the structure of the captured shape, not a number ML ever sent.
"""

from __future__ import annotations

import copy
from datetime import date, datetime, timezone
from decimal import Decimal

import pytest
import sqlalchemy as sa

from app.models.ml_ads import MlAdsBrandDay
from app.services.ml_ads import endpoints, mapper, store
from tests.services.ml_ads.captures import load

DAY = date(2026, 10, 5)
NOW = datetime(2026, 10, 8, 14, 0, tzinfo=timezone.utc)
ADVERTISERS = (714700, 25713)


def _body(advertiser_id: int = 25713) -> dict:
    return load("brand_ads_day_2026_10_05.json")[str(advertiser_id)]["body"]


def _with_spend(body: dict, cost: float) -> dict:
    """A real body with the day's cost edited (test only): the dashboard point and the summary agree."""
    spent = copy.deepcopy(body)
    spent["dashboard"]["consumed_budget"][0]["y"] = cost
    spent["summary"]["consumed_budget"] = cost
    return spent


class TestEndpoint:
    @pytest.mark.parametrize("advertiser_id", ADVERTISERS)
    def test_request_matches_the_captured_call(self, advertiser_id) -> None:
        captured = load("brand_ads_day_2026_10_05.json")[str(advertiser_id)]["request"]

        built = endpoints.brand_metrics_request(advertiser_id, DAY)

        assert built.path == captured["path"]
        assert dict(built.params) == captured["params"]  # one-day window plus aggregation_type=daily, as sent
        # Brand Ads is Api-Version 1 (D5), not the Product Ads version 2.
        assert dict(built.headers) == {"Api-Version": captured["api_version"]} == {"Api-Version": "1"}

    def test_the_advertiser_in_the_path_is_digits_only(self) -> None:
        with pytest.raises(ValueError):
            endpoints.brand_metrics_request("25713/../1", DAY)


class TestMapper:
    @pytest.mark.parametrize("advertiser_id", ADVERTISERS)
    def test_an_all_zero_day_has_no_fact(self, advertiser_id) -> None:
        assert mapper.map_brand_day(advertiser_id, DAY, _body(advertiser_id)) is None

    def test_cost_comes_from_the_dashboard_consumed_budget_point_of_the_day(self) -> None:
        fact = mapper.map_brand_day(25713, DAY, _with_spend(_body(), 1234.56))

        assert (fact.advertiser_id, fact.day, fact.cost) == (25713, DAY, Decimal("1234.56"))
        assert (fact.prints, fact.clicks) == (0, 0)
        assert fact.raw["summary"]["consumed_budget"] == 1234.56  # the raw answer is kept whole

    def test_activity_without_cost_is_still_a_fact(self) -> None:
        body = _body()
        body["dashboard"]["prints"][0]["y"] = 7  # test-only edit of a real body

        fact = mapper.map_brand_day(25713, DAY, body)

        assert (fact.cost, fact.prints, fact.clicks) == (Decimal("0"), 7, 0)

    def test_a_point_of_another_day_is_not_this_days_fact(self) -> None:
        body = _with_spend(_body(), 99)
        body["dashboard"]["consumed_budget"][0]["x"] = "2026-10-04"

        assert mapper.map_brand_day(25713, DAY, body) is None

    def test_the_ledger_total_is_the_summary_consumed_budget(self) -> None:
        summary = mapper.parse_brand_summary(_with_spend(_body(), 10.5))

        assert summary.cost == Decimal("10.5")
        assert summary.raw["consumed_budget"] == 10.5

    @pytest.mark.parametrize("broken", [{}, {"summary": None}, {"summary": {"clicks": 0}}, {"summary": []}])
    def test_a_body_without_summary_cost_has_no_total(self, broken) -> None:
        assert mapper.parse_brand_summary(broken) is None


@pytest.mark.postgres
class TestStore:
    def test_upsert_is_idempotent_and_keyed_by_advertiser_and_day(self, pg_ads_db) -> None:
        fact = mapper.map_brand_day(25713, DAY, _with_spend(_body(), 10))
        other = mapper.map_brand_day(714700, DAY, _with_spend(_body(714700), 5))

        store.upsert_brand_days(pg_ads_db, [fact, other], now=NOW)
        store.upsert_brand_days(pg_ads_db, [fact], now=NOW)

        rows = pg_ads_db.execute(sa.select(MlAdsBrandDay.advertiser_id, MlAdsBrandDay.cost)).all()
        assert sorted(rows) == [(25713, Decimal("10.00")), (714700, Decimal("5.00"))]

    def test_delete_stale_drops_only_this_days_row_of_an_older_fetch(self, pg_ads_db) -> None:
        old = NOW.replace(hour=10)
        keep = mapper.map_brand_day(714700, DAY, _with_spend(_body(714700), 5))
        gone = mapper.map_brand_day(25713, DAY, _with_spend(_body(), 10))
        store.upsert_brand_days(pg_ads_db, [keep], now=old)
        store.upsert_brand_days(pg_ads_db, [gone], now=old)

        store.delete_stale_brand(pg_ads_db, 25713, DAY, fetch_started_at=NOW)

        assert pg_ads_db.execute(sa.select(MlAdsBrandDay.advertiser_id)).scalars().all() == [714700]
