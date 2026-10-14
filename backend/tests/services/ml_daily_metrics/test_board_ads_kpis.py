"""ODD `ml-billing-balance` PR 7b-ii: the board's informational ads KPIs (MA-6, D8).

`kpis.ads` carries the period's Product Ads of the rows the KPIs sum: the unfiltered view reads every ad
line, a filtered view only the filtered rows' owner pairs (ads owned by nobody are zeroed). Ratios stay on the
API cost basis and are NULL on a zero denominator. Brand Ads is never read here. DERIVED fixtures: the figures
are the spec's (cost 100, attributed 500, clicks 20, prints 1,000) so every ratio is checkable by hand.
"""

# ruff: noqa: F811 -- the imported fixtures are re-named by the tests that use them
from __future__ import annotations

import dataclasses
from datetime import date
from decimal import Decimal

from app.models.ml_ads import MlAdsBrandDay, MlAdsItemDay
from app.services.ml_daily_metrics import board
from app.services.ml_daily_metrics.kpi_strip import build_board_kpis
from tests.integration.test_ml_metricas_board_router import (  # noqa: F401 -- fixtures
    URL,
    _day,
    _frozen_clock,
    _producto,
    _pub,
    bg_sessions,
    board_data,
)
from tests.services.ml_daily_metrics.test_board_ads_subtract import OFF, ON

AD_DAY = date(2026, 9, 4)
SOLO = dataclasses.replace(ON, solo_con_ventas=True)


def _full_ad(db, mla: str, day: date = AD_DAY, **values) -> None:
    db.add(MlAdsItemDay(advertiser_id=1, ad_group_id=1, item_id=mla, day=day, raw={}, **values))


def _spec_ads(db) -> None:
    """The spec's figures on MLA1 (product 11): cost 100, direct 300 + indirect 200, clicks 20, prints 1,000."""
    _producto(db, 11, "Impresora", "Epson")
    _pub(db, 1, "MLA1", 11, 57997)
    _day(db, 11, "MLA1", date(2026, 9, 3), 1, "1000", "300", "400")
    _full_ad(
        db,
        "MLA1",
        cost=Decimal("100"),
        direct_amount=Decimal("300"),
        indirect_amount=Decimal("200"),
        direct_units=3,
        indirect_units=2,
        organic_units=4,
        organic_amount=Decimal("80"),
        clicks=20,
        prints=1000,
    )
    db.commit()


def _kpis(db, f: board.BoardFilter, scope_pairs=None) -> board.Kpis:
    with board.Board(db, f, scope_pairs=scope_pairs) as b:
        return b.kpis()


def test_the_spec_figures_give_the_spec_ratios(db) -> None:
    _spec_ads(db)
    ads = build_board_kpis(_kpis(db, SOLO), True).ads
    assert (ads.cost_total, ads.cost_api, ads.clicks, ads.impressions) == (100.0, 100.0, 20, 1000)
    assert (ads.direct_amount, ads.indirect_amount, ads.direct_units, ads.indirect_units) == (300.0, 200.0, 3, 2)
    assert (ads.organic_units, ads.organic_amount) == (4, 80.0)
    assert (ads.acos_pct, ads.roas, ads.cpc, ads.ctr_pct) == (20.0, 5.0, 5.0, 2.0)
    assert ads.tacos_pct == 10.0  # 100 of ads over 1,000 gross


def test_zero_denominators_are_null_not_an_error(db) -> None:
    _producto(db, 11, "Impresora", "Epson")
    _pub(db, 1, "MLA1", 11, 57997)
    _full_ad(db, "MLA1", cost=Decimal("100"))
    db.commit()
    ads = build_board_kpis(_kpis(db, SOLO), True).ads
    assert (ads.acos_pct, ads.cpc, ads.ctr_pct, ads.tacos_pct) == (None, None, None, None)
    assert ads.roas == 0.0
    nothing = build_board_kpis(_kpis(db, dataclasses.replace(SOLO, q="no-such-product")), True).ads
    assert (nothing.cost_total, nothing.roas, nothing.acos_pct) == (0.0, None, None)


def test_off_and_no_margin_view_have_no_ads_block(db) -> None:
    _spec_ads(db)
    assert build_board_kpis(_kpis(db, OFF), True).ads is None
    assert build_board_kpis(_kpis(db, ON), False).ads is None


def test_the_comparison_period_is_not_in_the_kpi(db) -> None:
    _spec_ads(db)
    _full_ad(db, "MLA1", day=date(2026, 8, 28), cost=Decimal("40"), clicks=5)
    db.commit()
    assert build_board_kpis(_kpis(db, SOLO), True).ads.cost_total == 100.0


def test_unfiltered_cost_total_is_every_ad_line_and_total_gauss_drops_by_exactly_that(db) -> None:
    _spec_ads(db)
    _full_ad(db, "MLAX", cost=Decimal("30"))  # owned by nobody
    db.commit()
    k = _kpis(db, SOLO)
    assert build_board_kpis(k, True).ads.cost_total == 130.0
    assert k.tg == Decimal("300.00") - Decimal("130.00")


def test_a_filtered_view_counts_only_its_owner_pairs_and_never_the_unowned_ads(db) -> None:
    _spec_ads(db)
    _producto(db, 12, "Notebook", "Lenovo")
    _pub(db, 2, "MLA2", 12, 57997)
    _full_ad(db, "MLA2", cost=Decimal("70"))
    _full_ad(db, "MLAX", cost=Decimal("30"))
    db.commit()
    epson = dataclasses.replace(SOLO, marcas=("Epson",))
    assert build_board_kpis(_kpis(db, epson), True).ads.cost_total == 100.0
    assert build_board_kpis(_kpis(db, SOLO, scope_pairs=[("EPSON", "CAT")]), True).ads.cost_total == 100.0


def test_brand_ads_never_reduces_the_totals(db) -> None:
    _spec_ads(db)
    db.add(MlAdsBrandDay(advertiser_id=1, day=AD_DAY, cost=Decimal("500"), raw={}))
    db.commit()
    k = _kpis(db, SOLO)
    assert k.tg == Decimal("200.00") and build_board_kpis(k, True).ads.cost_total == 100.0


def test_the_response_serializes_the_block_only_when_on(client, admin_auth_headers, db, board_data) -> None:
    _full_ad(db, "MLA1", day=date(2026, 9, 30), cost=Decimal("12.5"), clicks=5, prints=100)
    db.commit()
    params = {"solo_con_ventas": "true", "date_from": "2026-09-01", "date_to": "2026-09-30"}
    off = client.get(URL, params=params, headers=admin_auth_headers).json()["kpis"]
    on = client.get(URL, params={**params, "restar_publicidad": "true"}, headers=admin_auth_headers).json()["kpis"]
    assert off["ads"] is None
    assert on["ads"]["cost_total"] == 12.5 and on["ads"]["cpc"] == 2.5 and on["ads"]["ctr_pct"] == 5.0
