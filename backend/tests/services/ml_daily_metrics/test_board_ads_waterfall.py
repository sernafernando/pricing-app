"""ml-ads-aportes S4 -- the "Publicidad restada" waterfall of Métricas ML (Stitch 5736acfc, owner-approved).

`kpis.ads.waterfall` breaks what the board subtracted into the lines the card shows, on the basis the board subtracts
(net of IVA), so the lines add up to `subtracted_total` to the cent:
Product Ads de publicaciones + Product Ads sin producto - aportes (Product Ads) = Product Ads neto;
+ Display - aportes (Display) + Brand Ads only where the view subtracts the account level.
DERIVED fixtures (no ML capture involved). Product 11 owns MLA1 and sells Total Gauss 300 on 09-03. Product Ads:
MLA1 80 in campaign 7 and 20 with no campaign, MLA2 (no product) 10 in campaign 7; campaign 7 has a 50 % aporte.
Display 1,200 with a 25 % whole-account aporte, Brand Ads 500.
"""

from __future__ import annotations

import dataclasses
from datetime import date

# Imported only to activate its autouse fixture: the board reads "today" from a frozen clock.
from tests.integration.test_ml_metricas_board_router import _frozen_clock  # noqa: F401
from tests.services.ml_daily_metrics.test_board_ads_contributions import _ad, _contribution, _product
from tests.services.ml_daily_metrics.test_board_ads_mode import MLA, TODO, _brand, _display, _kpis
from tests.services.ml_daily_metrics.test_board_display_contributions import _contribution as _display_contribution

SEPTEMBER = (date(2026, 9, 1), date(2026, 9, 30))


def _seed(db) -> None:
    _product(db)
    _ad(db, "80")
    _ad(db, "20", campaign=None, group=2)
    _ad(db, "10", mla="MLA2")
    _contribution(db, "percentage", "50", *SEPTEMBER)
    _display(db, "1200")
    _brand(db, "500")
    db.commit()
    _display_contribution(db, "percentage", "25")


def _lines(strip) -> dict:
    return strip.ads.waterfall.model_dump()


def test_restar_toda_breaks_the_whole_subtraction_into_lines_that_add_up(db) -> None:
    _seed(db)
    _k, strip, _rows = _kpis(db, TODO)
    assert _lines(strip) == {
        "product_ads_publications": 100.0,
        "product_ads_sin_producto": 10.0,
        "product_ads_contribution": 45.0,
        "product_ads_net": 65.0,
        "no_campaign": 20.0,
        "display_gross": 1200.0,
        "display_contribution": 300.0,
        "display_net": 900.0,
        "brand": 500.0,
        "account_subtracted": True,
        "total": 1465.0,
    }
    assert strip.ads.subtracted_total == 1465.0


def test_restar_ads_shows_display_and_brand_but_does_not_add_them(db) -> None:
    _seed(db)
    lines = _lines(_kpis(db, MLA)[1])
    assert (lines["product_ads_net"], lines["account_subtracted"], lines["total"]) == (65.0, False, 65.0)
    assert (lines["display_net"], lines["brand"]) == (900.0, 500.0)


def test_a_filtered_view_has_only_its_product_ads(db) -> None:
    """Under a filter there is no account level nor "sin producto": only the filtered rows' Product Ads."""
    _seed(db)
    lines = _lines(_kpis(db, dataclasses.replace(TODO, marcas=("Epson",)))[1])
    assert lines == {
        "product_ads_publications": 100.0,
        "product_ads_sin_producto": None,
        "product_ads_contribution": 40.0,
        "product_ads_net": 60.0,
        "no_campaign": 20.0,
        "display_gross": None,
        "display_contribution": None,
        "display_net": None,
        "brand": None,
        "account_subtracted": False,
        "total": 60.0,
    }


def test_the_lines_add_up_to_the_total_with_amounts_in_fractions_of_a_cent(db) -> None:
    """A 25 % aporte on 1,210.03 of Display covers 302.5075: the net Display is not a whole cent, and the lines
    still add up to the total the board subtracted."""
    _product(db)
    _ad(db, "80.07")
    _ad(db, "10.03", mla="MLA2")
    _display(db, "1210.03")
    _brand(db, "500.01")
    db.commit()
    _display_contribution(db, "percentage", "25")
    lines = _lines(_kpis(db, TODO)[1])
    added = (
        lines["product_ads_publications"]
        + lines["product_ads_sin_producto"]
        - lines["product_ads_contribution"]
        + lines["display_gross"]
        - lines["display_contribution"]
        + lines["brand"]
    )
    assert round(added, 2) == lines["total"]
    assert round(lines["product_ads_net"] + lines["display_net"] + lines["brand"], 2) == lines["total"]
