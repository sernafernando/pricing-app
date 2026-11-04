"""ml-ads-aportes-robust S8 -- "flag item rows with campaign NULL/0 instead of silent 0".

An item row with no campaign (NULL or 0) can never meet a brand contribution, so its cost always comes off whole. The
KPI block says how much of the period's Product Ads cost that is (`no_campaign`, ML's gross basis like `cost_api`),
instead of the board silently counting a contribution of 0 for it. DERIVED fixtures (no ML capture involved): product
11 owns MLA1 and sells Total Gauss 300 on 09-03; the period is 09-01..09-07.
"""

from __future__ import annotations

import dataclasses
from datetime import date
from decimal import Decimal

from app.services.ml_daily_metrics import board
from app.services.ml_daily_metrics.kpi_strip import build_board_kpis

# Imported only to activate its autouse fixture: the board reads "today" from a frozen clock.
from tests.integration.test_ml_metricas_board_router import _frozen_clock  # noqa: F401
from tests.services.ml_daily_metrics.test_board_ads_contributions import _ad, _contribution, _kpis, _product
from tests.services.ml_daily_metrics.test_board_ads_subtract import ON


def test_the_kpis_report_the_cost_of_item_rows_without_a_campaign(db) -> None:
    """MLA1 spends 50 in campaign 7 (50% covered), 30 with no campaign and 20 with campaign 0; MLA2 (no product) 5
    with no campaign; 40 with no campaign on 09-10, past the period."""
    _product(db)
    _ad(db, "50")
    _ad(db, "30", campaign=None, group=2)
    _ad(db, "20", campaign=0, group=3)
    _ad(db, "5", campaign=None, mla="MLA2")
    _ad(db, "40", campaign=None, day=date(2026, 9, 10), group=2)
    _contribution(db, "percentage", "50", date(2026, 9, 1), date(2026, 9, 30))
    k = _kpis(db)
    assert (k.ads.cost_api, k.ads.contribution, k.ads.no_campaign) == (
        Decimal("105.00"),
        Decimal("25.00"),
        Decimal("55.00"),
    )
    assert build_board_kpis(k, True).ads.no_campaign == 55.0
    filtered = _kpis(db, dataclasses.replace(ON, marcas=("Epson",)))
    assert (filtered.ads.cost_api, filtered.ads.no_campaign) == (Decimal("100.00"), Decimal("50.00"))


def test_no_campaign_is_zero_when_every_row_has_one(db) -> None:
    _product(db)
    _ad(db, "80")
    k = _kpis(db)
    assert (k.ads.cost_api, k.ads.no_campaign) == (Decimal("80.00"), Decimal("0.00"))
    assert build_board_kpis(k, True).ads.no_campaign == 0.0


def test_postgres_sums_the_rows_without_a_campaign(board_pg) -> None:
    """On Postgres: 10.01 with no campaign, 2.50 with campaign 0, 7 in campaign 7."""
    _ad(board_pg, "10.01", campaign=None)
    _ad(board_pg, "2.50", campaign=0, group=2)
    _ad(board_pg, "7", group=3)
    board_pg.flush()
    with board.Board(board_pg, ON, scope_pairs=None) as b:
        k = b.kpis()
    assert (k.ads.cost_api, k.ads.no_campaign) == (Decimal("19.51"), Decimal("12.51"))
