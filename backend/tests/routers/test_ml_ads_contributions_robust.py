"""ml-ads-aportes-robust S1-S4 -- loading an aporte checks what a person can get wrong.

S1 the brand is mandatory and comes from the marcas catalog (distinct `ProductoERP.marca`), stored with its spelling.
S2 a fixed amount copied with IVA is converted to sin IVA once, when saved.
S3 a `full` amount above the range spend needs an explicit confirmation.
S4 a range ending past the ledger's `data_through` is saved with a warning (the preview says it too).
S7 the loading page's cost is the campaign's item-row cost, the base the aporte and Métricas use.
Campaigns, item days, ledger rows and the ERP product are DERIVED rows (no ML capture involved).
"""

# ruff: noqa: F811 -- the imported fixtures are re-named by the tests that use them
from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

import pytest

from app.models.ml_ads import MlAdsCampaignDay, MlAdsDayLedger, MlAdsItemDay
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

FULL = {"kind": "fixed_amount", "settlement": "full"}


@pytest.fixture()
def catalog(db):
    """The ERP brands come with `campaigns` ("TP-Link", "Epson"); one item-day of 1000 on 10-05; the ledger closed through 10-10."""
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
    for n in range(10):
        db.add(
            MlAdsDayLedger(
                source="product_ads", advertiser_id=ADV, day=date(2026, 10, 1) + timedelta(n), status="closed"
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


class TestOverSpend:
    def test_a_full_amount_above_the_spend_is_rejected_on_value_with_the_spend(
        self, client, db, manager, catalog
    ) -> None:
        response = _create(client, manager, value="5000", **FULL)
        assert response.status_code == 422
        error = response.json()["error"]
        assert error["field"] == "value" and "1000.00" in error["message"]
        assert _rows(db) == []

    def test_confirmed_it_is_saved_as_typed(self, client, db, manager, catalog) -> None:
        response = _create(client, manager, value="5000", confirm_over_spend=True, **FULL)
        assert response.status_code == 201
        assert [r.value for r in _rows(db)] == [Decimal("5000.00")]

    @pytest.mark.parametrize(
        "overrides",
        [{"value": "1000", **FULL}, {"value": "5000", "kind": "fixed_amount", "settlement": "refund_difference"}],
        ids=["full-equal-to-the-spend", "refund-difference-is-capped-anyway"],
    )
    def test_nothing_to_confirm_when_the_net_cannot_go_negative(self, client, manager, catalog, overrides) -> None:
        assert _create(client, manager, **overrides).status_code == 201

    @pytest.mark.parametrize(
        "overrides, expected",
        [
            ({"value": "5000", **FULL}, True),
            ({"value": "5000", **FULL, "date_from": "2026-11-01", "date_to": "2026-11-30"}, True),  # nothing spent yet
            ({"value": "1000", **FULL}, False),
            ({"value": "5000", "kind": "fixed_amount", "settlement": "refund_difference"}, False),
            ({"value": "30"}, False),
        ],
        ids=["full-above", "full-on-a-range-without-spend", "full-equal", "refund-difference", "percentage"],
    )
    def test_the_preview_says_when_saving_needs_the_confirmation(
        self, client, manager, catalog, overrides, expected
    ) -> None:
        got = client.get(f"{BASE}/contributions/preview", headers=manager, params=_contribution(**overrides)).json()
        assert got["over_spend"] is expected
        saved = _create(client, manager, **overrides)
        assert saved.status_code == (422 if expected else 201)


class TestDataThrough:
    def test_a_range_past_the_ledger_is_saved_with_a_warning(self, client, manager, catalog) -> None:
        response = _create(client, manager)
        assert response.status_code == 201
        [warning] = response.json()["warnings"]
        assert "2026-10-10" in warning

    def test_a_range_inside_the_ledger_has_no_warning(self, client, manager, catalog) -> None:
        assert _create(client, manager, date_to="2026-10-10").json()["warnings"] == []

    def test_the_preview_warns_too(self, client, manager, catalog) -> None:
        got = client.get(f"{BASE}/contributions/preview", headers=manager, params=_contribution()).json()
        assert len(got["warnings"]) == 1 and "2026-10-10" in got["warnings"][0]
        assert got["data_through"] == "2026-10-10"


class TestCostBase:
    def test_the_campaign_cost_is_its_item_rows_not_its_campaign_report(self, client, db, manager, catalog) -> None:
        """The campaign report says 999 for 10-05 while its item rows add up to 1000: the page shows 1000."""
        db.add(
            MlAdsCampaignDay(advertiser_id=ADV, campaign_id=CAMP, day=date(2026, 10, 5), cost=Decimal("999"), raw={})
        )
        db.flush()
        got = client.get(
            f"{BASE}/campaigns", headers=manager, params={"date_from": "2026-10-01", "date_to": "2026-10-31"}
        )
        mine = next(c for c in got.json()["campaigns"] if c["campaign_id"] == CAMP)
        assert mine["cost"] == 1000.0
