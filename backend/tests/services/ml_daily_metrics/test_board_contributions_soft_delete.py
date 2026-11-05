"""ml-ads-aportes-robust S6 -- a soft-deleted aporte covers nothing on the Métricas ML board.

Product Ads (row level) and Display (position 2, account level) both ignore a contribution whose `deleted_at` is set:
the ads come off whole again. DERIVED fixtures from the existing board aporte tests (no ML capture involved).
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from app.models.ml_ads import MlAdsCampaignContribution

# Imported only to activate its autouse fixture: the board reads "today" from a frozen clock.
from tests.integration.test_ml_metricas_board_router import _frozen_clock  # noqa: F401
from tests.services.ml_daily_metrics.test_board_ads_contributions import _ad, _contribution, _product, _row
from tests.services.ml_daily_metrics.test_board_ads_mode import TODO, _kpis, _sale_with_ads
from tests.services.ml_daily_metrics.test_board_display_contributions import SEPTEMBER
from tests.services.ml_daily_metrics.test_board_display_contributions import _contribution as _display_contribution

DELETED_AT = datetime(2026, 9, 20, 12, 0, tzinfo=timezone.utc)


def _delete_all(db) -> None:
    for row in db.query(MlAdsCampaignContribution):
        row.deleted_at, row.deleted_by_id = DELETED_AT, 1
    db.commit()


def test_a_deleted_product_ads_aporte_covers_nothing(db) -> None:
    _product(db)
    _ad(db, "80")
    _contribution(db, "percentage", "50", *SEPTEMBER)
    assert _row(db).ads_cost == Decimal("40.00")
    _delete_all(db)
    row = _row(db)
    assert (row.ads_cost, row.tg) == (Decimal("80.00"), Decimal("220.00"))


def test_a_deleted_display_aporte_covers_nothing(db) -> None:
    _sale_with_ads(db)
    _display_contribution(db, "percentage", "25")
    assert _kpis(db, TODO)[1].ads.unattributed.account_level.display.contribution == 300.0
    _delete_all(db)
    k, out, _rows = _kpis(db, TODO)
    display = out.ads.unattributed.account_level.display
    assert (display.cost_net, display.contribution) == (1200.0, 0.0)
    assert k.tg == Decimal("-1500.00")  # 300 - 100 - 1200 - 500
