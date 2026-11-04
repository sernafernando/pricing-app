"""ml-ads-aportes-robust S1, S2 -- loading an aporte checks what a person can get wrong.

S1 the brand is mandatory and comes from the marcas catalog (distinct `ProductoERP.marca`), stored with its spelling.
S2 a fixed amount copied with IVA is converted to sin IVA once, when saved.
Campaigns, item days and the ERP products are DERIVED rows (no ML capture involved).
"""

# ruff: noqa: F811 -- the imported fixtures are re-named by the tests that use them
from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from app.models.ml_ads import MlAdsItemDay
from tests.routers.test_ml_ads_contributions_write import (  # noqa: F401 -- fixtures
    ADV,
    BASE,
    CAMP,
    _contribution,
    _create,
    _rows,
    campaigns,
    manager,
)


@pytest.fixture()
def catalog(db):
    """The ERP brands come with `campaigns` ("TP-Link", "Epson"); one item-day of 1000 on 10-05."""
    db.add(
        MlAdsItemDay(
            advertiser_id=ADV,
            ad_group_id=CAMP,
            item_id="MLA1",
            day=date(2026, 10, 5),
            campaign_id=CAMP,
            cost=Decimal("1000"),
            raw={},
        )
    )
    db.flush()


class TestBrand:
    def test_the_brand_is_stored_with_the_catalog_spelling(self, client, db, manager, catalog) -> None:
        response = _create(client, manager, brand=" tp-link ")
        assert response.status_code == 201 and response.json()["brand"] == "TP-Link"
        assert [r.brand for r in _rows(db)] == ["TP-Link"]

    @pytest.mark.parametrize("brand", [None, "", "Xerox"], ids=["missing", "blank", "not-in-the-catalog"])
    def test_a_brand_outside_the_catalog_is_the_apps_422_on_brand(self, client, db, manager, catalog, brand) -> None:
        response = _create(client, manager, brand=brand)
        assert response.status_code == 422 and response.json()["error"]["field"] == "brand"
        assert _rows(db) == []

    def test_an_edit_also_needs_a_catalog_brand(self, client, db, manager, catalog) -> None:
        created = _create(client, manager, brand="TP-Link").json()
        edited = client.put(f"{BASE}/contributions/{created['id']}", headers=manager, json=_contribution(brand="Xerox"))
        assert edited.status_code == 422 and edited.json()["error"]["field"] == "brand"
        assert [r.brand for r in _rows(db)] == ["TP-Link"]


class TestIva:
    def test_an_amount_with_iva_is_stored_without_it_once(self, client, db, manager, catalog) -> None:
        response = _create(
            client, manager, value="1210", iva_included=True, kind="fixed_amount", settlement="refund_difference"
        )
        assert response.status_code == 201 and response.json()["value"] == 1000.0
        assert [r.value for r in _rows(db)] == [Decimal("1000.00")]

    def test_the_preview_counts_the_amount_without_iva(self, client, manager, catalog) -> None:
        body = _contribution(value="605", iva_included=True, kind="fixed_amount", settlement="refund_difference")
        got = client.get(f"{BASE}/contributions/preview", headers=manager, params=body).json()
        assert (got["spend"], got["counted"], got["net"]) == (1000.0, 500.0, 500.0)

    def test_a_percentage_has_no_iva_to_take_off(self, client, db, manager, catalog) -> None:
        response = _create(client, manager, iva_included=True)
        assert response.status_code == 422 and response.json()["detail"][0]["loc"][0] == "body"
        assert _rows(db) == []
