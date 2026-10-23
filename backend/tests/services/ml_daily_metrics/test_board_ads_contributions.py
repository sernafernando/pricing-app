"""ODD `ml-ads-brand-contribution` T2 (S5, S6, S9): brand contributions come off the Product Ads the board subtracts.

A contribution covers part of a campaign's cost: `percentage` p% of each item row in its range, `fixed_amount` an
amount spread over the range's item rows by cost (`full` the whole amount, `refund_difference` capped at the range's
spend). The board subtracts ads net of it; the KPI block keeps ML's gross cost and exposes the contribution apart.
DERIVED fixtures: the arithmetic is chosen so every figure is checkable by hand.
"""

# ruff: noqa: F811 -- the imported fixtures are re-named by the tests that use them
from __future__ import annotations

import dataclasses
from datetime import date
from decimal import Decimal
from typing import Optional

from sqlalchemy import select

from app.models.ml_ads import MlAdsCampaignContribution, MlAdsItemDay
from app.services.ml_daily_metrics import board
from app.services.ml_daily_metrics.kpi_strip import build_board_kpis
from tests.integration.test_ml_metricas_board_router import (  # noqa: F401 -- fixtures
    _day,
    _frozen_clock,
    _producto,
    _pub,
)
from tests.services.ml_daily_metrics.test_board_ads_subtract import ON, _ledger, _rows

AD_DAY = date(2026, 9, 4)  # inside the board period 2026-09-01 .. 2026-09-07


def _ad(db, cost: str, day: date = AD_DAY, campaign: Optional[int] = 7, mla: str = "MLA1", group: int = 1) -> None:
    db.add(
        MlAdsItemDay(
            advertiser_id=1, ad_group_id=group, item_id=mla, day=day, campaign_id=campaign, cost=Decimal(cost), raw={}
        )
    )


def _contribution(db, kind: str, value: str, first: date, last: date, settlement=None, campaign=7, advertiser=1):
    db.add(
        MlAdsCampaignContribution(
            advertiser_id=advertiser,
            campaign_id=campaign,
            kind=kind,
            value=Decimal(value),
            date_from=first,
            date_to=last,
            settlement=settlement,
            created_by_id=1,
            updated_by_id=1,
        )
    )


def _product(db) -> None:
    """Product 11 owns MLA1 and sold it on 09-03: Total Gauss 300 over a cost of 400 (markup 75 before ads)."""
    _producto(db, 11, "Impresora", "Epson")
    _pub(db, 1, "MLA1", 11, 57997)
    _day(db, 11, "MLA1", date(2026, 9, 3), 1, "1000", "300", "400")


def _row(db, f: board.BoardFilter = ON) -> board.Row:
    db.commit()
    return _rows(db, f)["11"]


def _kpis(db, f: board.BoardFilter = ON) -> board.Kpis:
    db.commit()
    with board.Board(db, f, scope_pairs=None) as b:
        return b.kpis()


def test_a_percentage_covers_that_share_of_each_day_cost(db) -> None:
    _product(db)
    _ad(db, "80")
    _contribution(db, "percentage", "50", date(2026, 9, 1), date(2026, 9, 30))
    row = _row(db)
    assert (row.ads_cost, row.tg, row.mtg, row.markup) == (Decimal("40.00"), Decimal("260.00"), Decimal("260.00"), 65)


def test_a_full_fixed_amount_above_the_spend_turns_the_ads_negative_and_raises_total_gauss(db) -> None:
    _product(db)
    _ad(db, "60")
    _contribution(db, "fixed_amount", "100", date(2026, 9, 1), date(2026, 9, 7), settlement="full")
    row = _row(db)
    assert (row.ads_cost, row.tg, row.markup) == (Decimal("-40.00"), Decimal("340.00"), 85)


def test_a_refund_difference_fixed_amount_counts_only_up_to_the_range_spend(db) -> None:
    _product(db)
    _ad(db, "60")
    _contribution(db, "fixed_amount", "100", date(2026, 9, 1), date(2026, 9, 7), settlement="refund_difference")
    row = _row(db)
    assert (row.ads_cost, row.tg, row.markup) == (Decimal("0.00"), Decimal("300.00"), 75)


def test_a_fixed_amount_is_spread_over_its_whole_range_even_past_the_board_period(db) -> None:
    """Range 09-01..09-14 spends 80 (09-04, in the period) + 20 (09-10, outside it): 80% of the 50 lands on 09-04."""
    _product(db)
    _ad(db, "80")
    _ad(db, "20", day=date(2026, 9, 10))
    _contribution(db, "fixed_amount", "50", date(2026, 9, 1), date(2026, 9, 14), settlement="refund_difference")
    row = _row(db)
    assert (row.ads_cost, row.tg, row.markup) == (Decimal("40.00"), Decimal("260.00"), 65)


def test_item_rows_without_a_campaign_get_no_contribution(db) -> None:
    _product(db)
    _ad(db, "60", campaign=None)
    _ad(db, "20", campaign=0, group=2)
    _contribution(db, "percentage", "100", date(2026, 9, 1), date(2026, 9, 30), campaign=0)
    row = _row(db)
    assert (row.ads_cost, row.tg) == (Decimal("80.00"), Decimal("220.00"))


def test_the_kpi_block_keeps_the_gross_cost_and_exposes_the_contribution(db) -> None:
    """MLA1 (product 11) spends 80 and MLA2 (no product: "sin producto") 10, both campaign 7 at 50%."""
    _product(db)
    _ad(db, "80")
    _ad(db, "10", mla="MLA2")
    _contribution(db, "percentage", "50", date(2026, 9, 1), date(2026, 9, 30))
    k = _kpis(db)
    assert (k.ads.cost_api, k.ads.cost_total) == (Decimal("90.00"), Decimal("90.00"))
    assert (k.ads.contribution, k.ads.subtracted_total) == (Decimal("45.00"), Decimal("45.00"))
    assert k.ads.unattributed.sin_producto_cost == Decimal("5.00")
    assert k.tg == Decimal("255.00")  # 300 - 40 (MLA1) - 5 (sin producto)
    strip = build_board_kpis(k, True).ads
    assert (strip.cost_total, strip.contribution, strip.subtracted_total) == (90.0, 45.0, 45.0)
    filtered = _kpis(db, dataclasses.replace(ON, marcas=("Epson",)))
    assert (filtered.ads.cost_api, filtered.ads.contribution, filtered.ads.subtracted_total) == (
        Decimal("80.00"),
        Decimal("40.00"),
        Decimal("40.00"),
    )
    assert filtered.tg == Decimal("260.00")


def test_the_comparison_period_is_net_of_its_contribution(db) -> None:
    """Comparison 08-25..08-31 (ledgered): Total Gauss 200, ads 40 at 50% -> 180 (markup 45 over 400)."""
    _product(db)
    _day(db, 11, "MLA1", date(2026, 8, 28), 1, "1000", "200", "400")
    _ad(db, "40", day=date(2026, 8, 27))
    _ledger(db, date(2026, 8, 25), date(2026, 8, 31))
    _contribution(db, "percentage", "50", date(2026, 8, 20), date(2026, 8, 31))
    row = _row(db)
    assert (row.prev_tg, row.markup_prev, row.tg) == (Decimal("180.00"), 45, Decimal("300.00"))
    assert _kpis(db).prev_tg == Decimal("180.00")


def test_contributions_of_other_campaigns_advertisers_or_days_change_nothing(db) -> None:
    _product(db)
    _ad(db, "60")
    _contribution(db, "percentage", "50", date(2026, 9, 1), date(2026, 9, 30), campaign=8)
    _contribution(db, "percentage", "50", date(2026, 9, 1), date(2026, 9, 30), advertiser=2)
    _contribution(db, "fixed_amount", "30", date(2026, 9, 5), date(2026, 9, 30), settlement="full")
    row = _row(db)
    assert (row.ads_cost, row.tg, row.markup) == (Decimal("60.00"), Decimal("240.00"), 60)
    k = _kpis(db)
    assert (k.ads.cost_api, k.ads.contribution, k.ads.subtracted_total) == (
        Decimal("60.00"),
        Decimal("0.00"),
        Decimal("60.00"),
    )


def test_postgres_numeric_spreads_a_fixed_amount_to_the_cent(board_pg) -> None:
    """On Postgres numeric: a full 10 over a range that spent 30 + 15 + 25 lands 30/70, 15/70 and 25/70 of it."""
    for day, cost in ((date(2026, 9, 2), "30"), (date(2026, 9, 3), "15"), (date(2026, 9, 4), "25")):
        _ad(board_pg, cost, day=day)
    _ad(board_pg, "10.01", campaign=8, mla="MLA2")
    _contribution(board_pg, "fixed_amount", "10", date(2026, 9, 1), date(2026, 9, 7), settlement="full")
    _contribution(board_pg, "percentage", "33", date(2026, 9, 1), date(2026, 9, 7), campaign=8)
    board_pg.flush()
    with board.Board(board_pg, ON, scope_pairs=None) as b:
        found = board_pg.execute(select(b.ads_lines.c.mla, b.ads_lines.c.day, b.ads_lines.c.contribution)).all()
    by_key = {(mla, day.day): Decimal(value) for mla, day, value in found}
    assert {key: board.cents(value) for key, value in by_key.items()} == {
        ("MLA1", 2): Decimal("4.29"),
        ("MLA1", 3): Decimal("2.14"),
        ("MLA1", 4): Decimal("3.57"),
        ("MLA2", 4): Decimal("3.30"),  # 33% of 10.01 = 3.3033
    }
    assert board.cents(sum(v for (mla, _d), v in by_key.items() if mla == "MLA1")) == Decimal("10.00")
