"""ml-billing-balance PR 1b -- ADS-3 mapper: activity-only facts built from captured ML responses."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from app.services.ml_ads import mapper
from tests.services.ml_ads.captures import group_ads, group_row, load
from tests.services.ml_ads.replay import active_zero_cost, gauss_day

DAY = date(2026, 10, 5)
GAUSS = 25713
TPLINK = 714700


class TestActivityPredicate:
    def test_cost_alone_is_activity(self) -> None:
        assert mapper.has_activity({"cost": 0.01}) is True

    def test_organic_units_without_cost_is_activity(self) -> None:
        # Real zero-cost group of the day: no prints, no clicks, but one organic unit worth 136,200.
        group = active_zero_cost(gauss_day())[0]
        assert group["metrics"]["cost"] == 0.0 and group["metrics"]["prints"] == 0
        assert group["metrics"]["organic_units_quantity"] == 1
        assert mapper.has_activity(group["metrics"]) is True

    def test_organic_only_is_activity(self) -> None:
        # Real revoked ad: cost 0, clicks 0, but one organic unit worth 79,394.
        ad = load("moved_group_2678077237.json")["ads_page"]["body"]["results"][0]
        assert ad["metrics"]["cost"] == 0.0 and ad["metrics"]["organic_units_quantity"] == 1
        assert mapper.has_activity(ad["metrics"]) is True

    def test_all_zero_is_not_activity(self) -> None:
        silent = next(a for a in group_ads(953712626) if a["item_id"] == "MLA3516989956")
        assert mapper.has_activity(silent["metrics"]) is False

    def test_missing_metrics_count_as_zero(self) -> None:
        assert mapper.has_activity({}) is False


class TestMapItem:
    def test_zero_activity_ad_produces_no_row(self) -> None:
        silent = next(a for a in group_ads(953712626) if a["item_id"] == "MLA3516989956")
        assert mapper.map_item(GAUSS, 953712626, DAY, silent) is None

    def test_only_active_ads_of_a_page_become_rows(self) -> None:
        facts = mapper.map_ads_page(GAUSS, 953712626, DAY, {"results": group_ads(953712626)})
        # 33 ads captured, 4 with activity.
        assert len(group_ads(953712626)) == 33
        assert len(facts) == 4

    def test_money_is_decimal_of_the_printed_value(self) -> None:
        item = next(f for f in _gauss_item_facts() if f.item_id == "MLA1150587086")
        assert item.cost == Decimal("63996.44")
        assert isinstance(item.cost, Decimal)
        assert item.direct_amount == Decimal("1053364.0")
        assert item.indirect_amount == Decimal("44285.0")

    def test_direct_indirect_organic_mapped(self) -> None:
        item = next(f for f in _gauss_item_facts() if f.item_id == "MLA1150587086")
        assert (item.direct_units, item.indirect_units, item.organic_units) == (32, 2, 28)
        assert item.organic_amount == Decimal("921620.0")
        assert (item.clicks, item.prints) == (141, 5296)

    def test_keyed_by_reporting_advertiser_and_requested_group(self) -> None:
        item = _gauss_item_facts()[0]
        assert (item.advertiser_id, item.ad_group_id, item.day) == (GAUSS, 953712626, DAY)
        assert item.campaign_id == 357181954

    def test_raw_is_kept_untouched(self) -> None:
        raw = next(a for a in group_ads(953712626) if a["item_id"] == "MLA1150587086")
        assert mapper.map_item(GAUSS, 953712626, DAY, raw).raw == raw

    def test_moved_group_ads_are_keyed_by_the_reporting_advertiser(self) -> None:
        page = load("moved_group_2678077237.json")["ads_page"]["body"]
        facts = mapper.map_ads_page(TPLINK, 2678077237, DAY, page)
        assert facts and all(f.advertiser_id == TPLINK for f in facts)
        assert facts[0].raw["original_advertiser_id"] == 25713

    def test_foreign_or_unknown_item_id_is_still_mapped(self) -> None:
        # ADS-8: ownership is not checked at ingestion time. A real 25713 ad mapped under 714700 is kept as is.
        raw = next(a for a in group_ads(953712626) if a["item_id"] == "MLA1150587086")
        fact = mapper.map_item(TPLINK, 953712626, DAY, raw)
        assert (fact.advertiser_id, fact.item_id, fact.cost) == (TPLINK, "MLA1150587086", Decimal("63996.44"))


class TestMapGroup:
    def test_cost_bearing_group_needs_a_drill(self) -> None:
        raw = group_row(953712626)
        fact = mapper.map_group(GAUSS, DAY, raw)
        assert (fact.ad_group_id, fact.cost, fact.units_quantity) == (953712626, Decimal("64692.18"), 34)
        assert (fact.ad_group_type, fact.external_id, fact.campaign_id) == ("CATALOG", "MLA18382230", 357181954)
        assert fact.needs_drill is True
        assert fact.raw == raw

    def test_active_group_without_cost_is_kept_and_not_drilled(self) -> None:
        raw = active_zero_cost(gauss_day())[0]
        fact = mapper.map_group(GAUSS, DAY, raw)
        assert fact.cost == Decimal("0.0")
        assert (fact.prints, fact.clicks, fact.units_quantity) == (0, 0, 0)
        assert fact.raw["metrics"]["organic_units_amount"] == 136200.0
        assert fact.needs_drill is False

    def test_the_captured_day_yields_72_cost_bearing_and_19_active_groups(self) -> None:
        facts = [f for page in gauss_day()["pages"] for f in mapper.map_groups_page(GAUSS, DAY, page)]
        assert len(facts) == 72 + 19
        assert sum(1 for f in facts if f.needs_drill) == 72
        assert sum(f.cost for f in facts) == Decimal("614060.07")


class TestPerDateSeriesNeverFeedsFacts:
    def test_series_without_identity_creates_no_item_rows(self) -> None:
        series = load("ads_daily_series_group_953712626.json")["response"]["ads"]
        assert len(series) == 7 and "date" in series[0] and "item_id" not in series[0]
        assert mapper.map_ads_page(GAUSS, 953712626, DAY, {"results": series}) == []

    def test_series_without_identity_creates_no_group_rows(self) -> None:
        series = load("ads_daily_series_group_953712626.json")["response"]["ads"]
        assert mapper.map_groups_page(GAUSS, DAY, {"results": series}) == []


class TestParseSummary:
    def test_day_total_and_raw(self) -> None:
        body = load("campaigns_summary_2026_10_05.json")["25713"]["body"]
        summary = mapper.parse_summary(body)
        assert summary.cost == Decimal("614060.07")
        assert summary.raw == body["metrics_summary"]

    def test_zero_spend_day(self) -> None:
        body = load("campaigns_summary_2026_10_05.json")["714700"]["body"]
        assert mapper.parse_summary(body).cost == Decimal("0.0")

    def test_missing_summary_is_none(self) -> None:
        assert mapper.parse_summary({"results": []}) is None


def _gauss_item_facts():
    return mapper.map_ads_page(GAUSS, 953712626, DAY, {"results": group_ads(953712626)})
