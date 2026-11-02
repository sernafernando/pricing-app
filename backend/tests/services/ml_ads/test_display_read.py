"""ml-ads-cupones-display S7 -- the Display tab's read: per campaign (catalog + summed days), period totals and
the daily cost. Days and catalog are the captured 2026-10-05 advertiser 25713 Display day; derived ratios are
computed here (ML's own `ctr` is 0.0 even with clicks)."""

from __future__ import annotations

from dataclasses import replace
from datetime import date, timedelta
from decimal import Decimal

from app.models.ml_ads import MlAdsDayLedger
from app.services.ml_ads import mapper, read, store
from tests.services.ml_ads.captures import load
from tests.services.ml_ads.test_display import ADVERTISER, DAY, NOW
from tests.services.ml_ads.test_display import _facts as display_facts


def _seed(db, *, catalog: bool = True) -> None:
    store.upsert_display_days(db, display_facts(), now=NOW)
    if catalog:
        body = load("display_day_2026_10_05_25713.json")["campaigns"]["body"]
        store.upsert_display_catalog(db, mapper.map_display_catalog(ADVERTISER, body), now=NOW)


def _campaign(got: read.DisplayReport, campaign_id: int) -> read.DisplayCampaignReport:
    return next(c for c in got.campaigns if c.campaign_id == campaign_id)


class TestDisplayReport:
    def test_a_campaign_carries_its_catalog_and_its_summed_figures(self, db) -> None:
        _seed(db)
        row = _campaign(read.display_report(db, DAY, DAY), 335306)
        assert (row.advertiser_id, row.name, row.type, row.goal, row.status) == (
            ADVERTISER,
            "XeroxB110",
            "PROGRAMMATIC",
            "conversion",
            "active",
        )
        assert (row.start_date, row.end_date) == (date(2026, 9, 7), date(2026, 11, 1))
        assert (row.cost, row.prints, row.clicks, row.reach) == (Decimal("27226.79"), 12576, 21, 3498)
        assert (row.attributed_amount, row.attributed_units) == (Decimal("1658026.88"), 9)

    def test_the_ratios_are_computed_not_taken_from_ml(self, db) -> None:
        _seed(db)
        row = _campaign(read.display_report(db, DAY, DAY), 335306)
        assert row.ctr == Decimal(21) / Decimal(12576)  # ML sends ctr 0.0 for this row
        assert row.cpc == Decimal("27226.79") / 21
        assert row.cpm == Decimal("27226.79") * 1000 / 12576
        assert row.roas == Decimal("1658026.88") / Decimal("27226.79")

    def test_a_ratio_without_its_base_is_none(self, db) -> None:
        _seed(db)
        report = read.display_report(db, DAY, DAY)
        no_clicks = _campaign(report, 294806)  # captured: 13 prints, 0 clicks
        assert (no_clicks.clicks, no_clicks.cpc, no_clicks.ctr) == (0, None, Decimal(0))
        paused = _campaign(report, 340339)  # in the catalog, no activity that day
        assert (paused.cost, paused.prints, paused.ctr, paused.cpc, paused.cpm, paused.roas) == (
            Decimal(0),
            0,
            None,
            None,
            None,
            None,
        )

    def test_every_catalog_campaign_is_listed_by_cost_descending(self, db) -> None:
        _seed(db)
        ids = [c.campaign_id for c in read.display_report(db, DAY, DAY).campaigns]
        assert ids[:4] == [301232, 259859, 335306, 294806]
        assert sorted(ids[4:]) == [281280, 290925, 340339]

    def test_a_campaign_missing_from_the_catalog_is_still_listed_without_a_name(self, db) -> None:
        _seed(db, catalog=False)
        row = _campaign(read.display_report(db, DAY, DAY), 335306)
        assert (row.name, row.status, row.cost) == (None, None, Decimal("27226.79"))

    def test_the_totals_sum_the_campaigns_and_recompute_the_ratios(self, db) -> None:
        _seed(db)
        totals = read.display_report(db, DAY, DAY).totals
        assert (totals.cost, totals.prints, totals.clicks) == (Decimal("121938.82"), 47969, 91)
        assert (totals.attributed_amount, totals.attributed_units) == (Decimal("5399874.93"), 40)
        assert totals.roas == Decimal("5399874.93") / Decimal("121938.82")
        assert totals.ctr == Decimal(91) / Decimal(47969)

    def test_the_daily_cost_is_one_point_per_stored_day_and_a_day_without_rows_is_absent(self, db) -> None:
        _seed(db)
        # DERIVED: the captured 335306 day copied two days later (DAY + 1 stays without rows).
        fact = next(f for f in display_facts() if f.campaign_id == 335306)
        later = DAY + timedelta(days=2)
        store.upsert_display_days(db, [replace(fact, day=later, raw={**fact.raw, "date": later.isoformat()})], now=NOW)
        report = read.display_report(db, DAY, later)
        assert report.daily == [
            read.DisplayDayCost(DAY, Decimal("121938.82")),
            read.DisplayDayCost(later, Decimal("27226.79")),
        ]
        assert _campaign(report, 335306).reach == 2 * 3498  # summed per day, like every figure

    def test_outside_the_range_the_figures_are_zero_and_there_are_no_days(self, db) -> None:
        _seed(db)
        report = read.display_report(db, DAY + timedelta(days=1), DAY + timedelta(days=3))
        assert report.daily == []
        assert report.totals.cost == Decimal(0) and report.totals.roas is None
        assert all(c.cost == 0 for c in report.campaigns) and len(report.campaigns) == 7

    def test_a_day_without_attribution_adds_zero_sales(self, db) -> None:
        # DERIVED: the captured 335306 day with its `event_time` block removed.
        fact = next(f for f in display_facts() if f.campaign_id == 335306)
        raw = {k: v for k, v in fact.raw.items() if k != "event_time"}
        store.upsert_display_days(db, [replace(fact, raw=raw)], now=NOW)
        row = _campaign(read.display_report(db, DAY, DAY), 335306)
        assert (row.cost, row.attributed_amount, row.attributed_units, row.roas) == (
            Decimal("27226.79"),
            Decimal(0),
            0,
            Decimal(0),
        )

    def test_a_non_numeric_attribution_reads_zero_instead_of_failing(self, db) -> None:
        # DERIVED: the captured 335306 day with its attribution sent as text.
        fact = next(f for f in display_facts() if f.campaign_id == 335306)
        raw = {**fact.raw, "event_time": {**fact.raw["event_time"], "direct_amount": "n/a", "units_quantity": None}}
        store.upsert_display_days(db, [replace(fact, raw=raw)], now=NOW)
        row = _campaign(read.display_report(db, DAY, DAY), 335306)
        assert (row.cost, row.attributed_amount, row.attributed_units) == (Decimal("27226.79"), Decimal(0), 0)

    def test_a_closed_display_day_without_rows_costs_zero_and_an_unledgered_one_is_absent(self, db) -> None:
        _seed(db)
        # DERIVED ledger rows: DAY + 1 closed by the Display step with no activity; DAY + 2 never fetched.
        db.add(MlAdsDayLedger(source="display", advertiser_id=ADVERTISER, day=DAY + timedelta(days=1), status="closed"))
        db.flush()
        daily = read.display_report(db, DAY, DAY + timedelta(days=2)).daily
        assert daily == [
            read.DisplayDayCost(DAY, Decimal("121938.82")),
            read.DisplayDayCost(DAY + timedelta(days=1), Decimal(0)),
        ]
