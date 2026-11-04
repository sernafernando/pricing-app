"""ml-ads-display-contributions S2: Display brand contributions come off the Display the board subtracts.

"si alguna marca nos aportó para el display también habría que descontarlo de ahí". In position 2 ("Restar toda la
publicidad") Display comes off the KPI totals net of the Display contributions, with the Product Ads rules:
`percentage` p% of each Display day row, `fixed_amount` spread by each row's share of the whole range's Display spend.
A whole-account contribution matches every Display row of its advertiser. Product Ads item rows never take a Display
contribution, even when its campaign id equals theirs. DERIVED fixtures, checkable by hand (no ML capture involved):
product 11 sells Total Gauss 300 over a cost of 400, with 100 of Product Ads, 1,200 of Display (advertiser 25713,
campaign 1) and 500 of Brand Ads in the period.
"""

# ruff: noqa: F811 -- the imported fixtures are re-named by the tests that use them
from __future__ import annotations

import dataclasses
from datetime import date
from decimal import Decimal
from typing import Optional

from app.models.ml_ads import MlAdsCampaignContribution, MlAdsDisplayCampaignDay
from app.services.ml_ads import contributions
from app.services.ml_daily_metrics import board
from tests.integration.test_ml_metricas_board_router import (  # noqa: F401 -- fixtures
    _frozen_clock,
)
from tests.services.ml_daily_metrics.test_board_ads_contributions import _ad as _campaign_ad
from tests.services.ml_daily_metrics.test_board_ads_contributions import _product
from tests.services.ml_daily_metrics.test_board_ads_mode import (
    MLA,
    TODO,
    _compare,
    _display,
    _kpis,
    _ledger_account,
    _sale_with_ads,
)
from tests.services.ml_daily_metrics.test_board_ads_subtract import ON, _ledger

GAUSS = 25713
SEPTEMBER = (date(2026, 9, 1), date(2026, 9, 30))


def _contribution(
    db,
    kind: str,
    value: str,
    first: date = SEPTEMBER[0],
    last: date = SEPTEMBER[1],
    campaign: Optional[int] = None,
    advertiser: int = GAUSS,
    settlement: Optional[str] = None,
    channel: str = "display",
) -> None:
    db.add(
        MlAdsCampaignContribution(
            advertiser_id=advertiser,
            campaign_id=campaign,
            channel=channel,
            kind=kind,
            value=Decimal(value),
            date_from=first,
            date_to=last,
            settlement=settlement,
            created_by_id=1,
            updated_by_id=1,
        )
    )
    db.commit()


def test_a_whole_account_percentage_comes_off_the_display_subtracted(db) -> None:
    _sale_with_ads(db)
    _contribution(db, "percentage", "25")
    k, out, rows = _kpis(db, TODO)
    assert k.tg == Decimal("-1200.00")  # 300 - 100 - (1200 - 300) - 500
    assert out.ads.subtracted_total == 1500.0
    display = out.ads.unattributed.account_level.display
    assert (display.cost_api, display.cost_net, display.contribution, display.subtracted) == (
        1200.0,
        900.0,
        300.0,
        True,
    )
    assert (k.ads.contribution, out.ads.contribution) == (Decimal("0.00"), 0.0)  # the Product Ads one stays apart
    assert rows["11"].tg == Decimal("200.00")  # rows only carry what a row can own


def test_position_one_ignores_display_contributions(db) -> None:
    _sale_with_ads(db)
    _contribution(db, "percentage", "25")
    k, out, _rows = _kpis(db, MLA)
    assert (k.tg, out.ads.subtracted_total) == (Decimal("200.00"), 100.0)


def test_a_fixed_amount_is_spread_by_the_share_of_its_whole_range_display_spend(db) -> None:
    """Range 09-01..09-14 spends 1200 (09-04, in the period) + 300 (09-10, outside it): 1200/1500 of 600 = 480."""
    _sale_with_ads(db)
    _display(db, "300", date(2026, 9, 10))
    _contribution(db, "fixed_amount", "600", last=date(2026, 9, 14), campaign=1, settlement="full")
    k, out, _rows = _kpis(db, TODO)
    display = out.ads.unattributed.account_level.display
    assert (display.cost_net, display.contribution) == (720.0, 480.0)
    assert k.tg == Decimal("-1020.00")  # 300 - 100 - 720 - 500


def test_a_refund_difference_counts_only_up_to_the_display_spend(db) -> None:
    _sale_with_ads(db)
    _contribution(db, "fixed_amount", "5000", settlement="refund_difference")
    k, out, _rows = _kpis(db, TODO)
    assert (out.ads.unattributed.account_level.display.cost_net, k.tg) == (0.0, Decimal("-300.00"))


def test_contributions_of_other_campaigns_advertisers_days_or_channels_change_nothing(db) -> None:
    _sale_with_ads(db)
    before = _kpis(db, TODO)
    _contribution(db, "percentage", "50", campaign=2)
    _contribution(db, "percentage", "50", advertiser=714700)
    _contribution(db, "percentage", "50", first=date(2026, 9, 5), last=date(2026, 9, 30), campaign=1, advertiser=1)
    _contribution(db, "percentage", "50", campaign=1, channel="product_ads")
    after = _kpis(db, TODO)
    assert after[0] == before[0] and after[1] == before[1]
    assert after[1].ads.unattributed.account_level.display.contribution == 0.0


def test_a_display_contribution_never_lands_on_product_ads_rows_with_the_same_ids(db) -> None:
    """Item rows of advertiser 1, campaign 7, and a Display contribution of advertiser 1, campaign 7 at 50%."""
    _product(db)
    _campaign_ad(db, "80")
    db.add(
        MlAdsDisplayCampaignDay(
            advertiser_id=1, campaign_id=7, day=date(2026, 9, 4), consumed_budget=Decimal("40"), raw={}
        )  # DERIVED
    )
    _contribution(db, "percentage", "50", campaign=7, advertiser=1)
    k, out, rows = _kpis(db, dataclasses.replace(ON, restar_todo=True))
    assert (rows["11"].ads_cost, rows["11"].tg) == (Decimal("80.00"), Decimal("220.00"))
    assert (k.ads.cost_api, k.ads.contribution) == (Decimal("80.00"), Decimal("0.00"))
    assert out.ads.unattributed.account_level.display.contribution == 20.0
    assert k.tg == Decimal("200.00")  # 300 - 80 - (40 - 20)


def test_the_comparison_period_display_is_net_of_its_contribution(db) -> None:
    """Comparison 08-25..08-31: Total Gauss 260, Display 100 at 50% and Brand 50 -> 260 - 50 - 50."""
    _compare(db)
    _ledger(db, date(2026, 8, 25), date(2026, 8, 31))
    _ledger_account(db)
    _contribution(db, "percentage", "50", first=date(2026, 8, 20), last=date(2026, 8, 31))
    k = _kpis(db, TODO)[0]
    assert k.prev_tg == Decimal("160.00")
    assert k.tg == Decimal("-1500.00")  # the period has no contribution: 300 - 100 - 1200 - 500


def test_postgres_numeric_spreads_a_display_fixed_amount_to_the_cent(board_pg) -> None:
    """On Postgres: a full 10 over Display days of 30 + 15 + 25 (09-10 is past the period) and 33% of 10.01."""
    for day, cost in ((date(2026, 9, 2), "30"), (date(2026, 9, 3), "15"), (date(2026, 9, 10), "25")):
        board_pg.add(
            MlAdsDisplayCampaignDay(advertiser_id=GAUSS, campaign_id=1, day=day, consumed_budget=Decimal(cost), raw={})
        )
    board_pg.add(
        MlAdsDisplayCampaignDay(
            advertiser_id=1, campaign_id=2, day=date(2026, 9, 4), consumed_budget=Decimal("10.01"), raw={}
        )
    )
    for row in (
        dict(advertiser_id=GAUSS, campaign_id=None, kind="fixed_amount", value=Decimal("10"), settlement="full"),
        dict(advertiser_id=1, campaign_id=2, kind="percentage", value=Decimal("33")),
    ):
        board_pg.add(
            MlAdsCampaignContribution(
                **row,
                channel="display",
                date_from=date(2026, 9, 1),
                date_to=date(2026, 9, 14),
                created_by_id=1,
                updated_by_id=1,
            )
        )
    board_pg.flush()
    with board.Board(board_pg, TODO, scope_pairs=None) as b:
        account = b.account
    assert account.display_api == Decimal("55.01")  # 30 + 15 + 10.01
    assert board.cents(account.display_contribution) == Decimal("9.73")  # 10 x 45/70 = 6.4285... + 3.3033
    assert board.cents(account.display_net) == Decimal("45.28")
    # The Display tab computes the same figure (`contributions.display_contributions`).
    tab = contributions.display_contributions(board_pg, date(2026, 9, 1), date(2026, 9, 7))
    assert board.cents(sum(tab.values())) == board.cents(account.display_contribution)
