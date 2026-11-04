"""ml-billing-balance 6-iii-b -- `GET /api/ml-ads/by-mla|by-product|account-level` (AR-1, AR-3, AR-4, AR-5).

The numbers are the captured, drilled 2026-10-05 group 953712626 (via `test_read_provider._seed`) and the captured
Display campaigns; Brand Ads is the captured all-zero body with the day's cost edited (DERIVED, as in the service
tests). Owners are DERIVED publication rows. Authentication and the permission live in the SQLite test database,
which is also where the ads tables are read from (the `client` fixture's `get_db`).
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from app.models.mercadolibre_item_publicado import MercadoLibreItemPublicado as M
from app.routers import ml_ads
from app.services.ml_ads import mapper, store
from tests.routers.test_ml_publications_links import grant
from tests.services.ml_ads.captures import load
from tests.services.ml_ads.test_brand import ADVERTISERS, _body, _with_spend
from tests.services.ml_ads.test_display import _facts as display_facts
from tests.services.ml_ads.test_read_provider import DAY, GAUSS, T0, TPLINK, _close, _seed

BASE = "/api/ml-ads"
GANANCIA = "ml_metricas.ver_ganancia"
BIG, SMALL = "MLA1150587086", "MLA3505349772"  # captured MLAs with cost on DAY
ORGANIC_ONLY, CLICKS_ONLY = "MLA1417727981", "MLA1824116594"  # captured MLAs with activity but no cost
RANGE = {"date_from": DAY.isoformat(), "date_to": DAY.isoformat()}


@pytest.fixture()
def reader(db, rol_admin, admin_auth_headers):
    grant(db, rol_admin, GANANCIA)
    return admin_auth_headers


def get(client, headers, path, **params):
    return client.get(f"{BASE}/{path}", headers=headers, params={**RANGE, **params})


class TestPermission:
    def test_the_permission_is_the_profit_one(self) -> None:
        assert ml_ads.PERMISO_GANANCIA == GANANCIA

    @pytest.mark.parametrize("path", ["by-mla", "by-product", "account-level", "display"])
    def test_authentication_is_required(self, client, path) -> None:
        assert client.get(f"{BASE}/{path}", params=RANGE).status_code in (401, 403)

    @pytest.mark.parametrize("path", ["by-mla", "by-product", "account-level", "display"])
    def test_without_ver_ganancia_it_is_403_and_names_the_permission(self, client, db, auth_headers, path) -> None:
        response = get(client, auth_headers, path)
        assert response.status_code == 403
        assert GANANCIA in response.json()["error"]["message"]

    def test_the_only_writes_are_the_brand_contributions(self) -> None:
        writes = {route.path for route in ml_ads.router.routes if getattr(route, "methods", set()) - {"GET", "HEAD"}}
        assert writes == {"/ml-ads/contributions", "/ml-ads/contributions/{contribution_id}"}


class TestValidation:
    @pytest.mark.parametrize("path", ["by-mla", "by-product", "account-level", "display"])
    def test_an_inverted_range_is_422(self, client, reader, path) -> None:
        response = get(client, reader, path, date_from="2026-10-06", date_to="2026-10-05")
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "VALIDATION_ERROR"

    @pytest.mark.parametrize("path", ["by-mla", "by-product", "account-level", "display"])
    def test_a_range_over_366_days_is_422_and_366_days_is_fine(self, client, reader, path) -> None:
        start = date(2026, 1, 1)
        over = get(client, reader, path, date_from=start.isoformat(), date_to=(start + timedelta(days=366)).isoformat())
        ok = get(client, reader, path, date_from=start.isoformat(), date_to=(start + timedelta(days=365)).isoformat())
        assert (over.status_code, ok.status_code) == (422, 200)

    def test_a_missing_or_malformed_date_is_422(self, client, reader) -> None:
        assert client.get(f"{BASE}/by-mla", headers=reader).status_code == 422
        assert get(client, reader, "by-mla", date_to="not-a-date").status_code == 422

    def test_mlas_over_500_is_422_and_500_is_fine(self, client, reader) -> None:
        many = lambda n: ",".join(f"MLA{i}" for i in range(n))  # noqa: E731
        assert get(client, reader, "by-mla", mlas=many(501)).status_code == 422
        assert get(client, reader, "by-mla", mlas=many(500)).status_code == 200

    def test_an_empty_mlas_is_422_rather_than_widening_to_every_mla(self, client, reader) -> None:
        assert get(client, reader, "by-mla", mlas=" , ").status_code == 422

    def test_product_ids_must_be_integers_and_at_most_500(self, client, reader) -> None:
        assert get(client, reader, "by-product", product_ids="1,x").status_code == 422
        assert get(client, reader, "by-product", product_ids=",".join(map(str, range(501)))).status_code == 422
        assert get(client, reader, "by-product", product_ids=",".join(map(str, range(500)))).status_code == 200


class TestByMla:
    def test_each_mla_with_cost_has_its_owner_both_bases_and_the_informational_figures(
        self, client, db, reader
    ) -> None:
        _seed(db)
        db.add(M(mlp_id=1, mlp_publicationID=BIG, item_id=10))  # DERIVED owner
        db.flush()
        body = get(client, reader, "by-mla").json()
        rows = {r["mla"]: r for r in body["items"]}
        assert set(rows) == {BIG, SMALL, ORGANIC_ONLY, CLICKS_ONLY}  # zero-cost MLAs are listed (owner decision)
        assert (rows[ORGANIC_ONLY]["cost_api"], rows[ORGANIC_ONLY]["organic_units"]) == (0.0, 6)
        big = rows[BIG]
        assert (big["owner_product_id"], big["cost_api"], big["cost_net"]) == (10, 63996.44, 63996.44)
        assert (big["clicks"], big["prints"], big["direct_units"], big["organic_units"]) == (141, 5296, 32, 28)
        assert (big["direct_amount"], big["indirect_amount"]) == (1053364.0, 44285.0)
        assert rows[SMALL]["owner_product_id"] == 0  # sin producto

    def test_mlas_narrows(self, client, db, reader) -> None:
        _seed(db)
        body = get(client, reader, "by-mla", mlas=f" {SMALL} ,").json()
        assert [r["mla"] for r in body["items"]] == [SMALL]
        assert body["items"][0]["cost_api"] == 695.74

    def test_the_response_carries_the_coverage_of_the_same_range(self, client, db, reader) -> None:
        _close(db, GAUSS, DAY)
        _close(db, TPLINK, DAY, "error")
        coverage = get(client, reader, "by-mla").json()["coverage"]
        assert coverage["data_through"] is None
        assert coverage["missing_days"] == [
            {"source": "product_ads", "advertiser_id": TPLINK, "day": DAY.isoformat(), "status": "error"}
        ]
        assert coverage["mismatch_days"] == []

    def test_a_mismatch_day_is_reported_apart_from_the_missing_ones(self, client, db, reader) -> None:
        _close(db, GAUSS, DAY, "mismatch")
        coverage = get(client, reader, "by-mla").json()["coverage"]
        assert [d["status"] for d in coverage["mismatch_days"]] == ["mismatch"]
        assert coverage["missing_days"] == []

    def test_no_data_is_an_empty_list_not_an_error(self, client, reader) -> None:
        body = get(client, reader, "by-mla").json()
        assert body["items"] == []
        assert body["coverage"]["missing_days"] == []


class TestByProduct:
    def _publish(self, db) -> None:
        db.add_all([M(mlp_id=1, mlp_publicationID=BIG, item_id=10), M(mlp_id=2, mlp_publicationID=SMALL, item_id=10)])
        db.flush()

    def test_it_sums_the_mlas_of_each_owner(self, client, db, reader) -> None:
        _seed(db)
        self._publish(db)
        row = next(p for p in get(client, reader, "by-product").json()["products"] if p["product_id"] == 10)
        assert (row["product_id"], row["mlas_count"], row["cost_api"], row["clicks"]) == (10, 2, 64692.18, 142)

    def test_product_ids_narrows_and_zero_is_sin_producto(self, client, db, reader) -> None:
        _seed(db)
        db.add(M(mlp_id=1, mlp_publicationID=BIG, item_id=10))
        db.flush()
        assert [p["product_id"] for p in get(client, reader, "by-product", product_ids="0").json()["products"]] == [0]
        assert [p["product_id"] for p in get(client, reader, "by-product", product_ids="10, 0").json()["products"]] == [
            0,
            10,
        ]

    def test_the_products_add_up_to_the_mlas(self, client, db, reader) -> None:
        _seed(db)
        db.add(M(mlp_id=1, mlp_publicationID=BIG, item_id=10))
        db.flush()
        by_mla = sum(r["cost_api"] for r in get(client, reader, "by-mla").json()["items"])
        by_product = sum(p["cost_api"] for p in get(client, reader, "by-product").json()["products"])
        assert round(by_mla, 2) == round(by_product, 2) == 64692.18


class TestAccountLevel:
    def test_display_is_subtractable_per_campaign_and_brand_is_informational_only(self, client, db, reader) -> None:
        store.upsert_display_days(db, display_facts(), now=T0)
        # DERIVED: the captured all-zero Brand body with the day's cost edited, as the service tests do.
        brand = mapper.map_brand_day(ADVERTISERS[1], DAY, _with_spend(_body(ADVERTISERS[1]), 1500.0))
        store.upsert_brand_days(db, [brand], now=T0)
        body = get(client, reader, "account-level").json()
        display = body["display"]
        assert (display["cost_api"], display["cost_net"], display["subtractable"]) == (121938.82, 121938.82, True)
        campaign = next(c for c in display["by_campaign"] if c["campaign_id"] == 335306)
        assert (campaign["cost_api"], campaign["cost_net"]) == (27226.79, 27226.79)
        assert body["brand"]["cost_informational"] == 1500.0
        assert body["brand"]["subtractable"] is False
        assert "cost_net" not in body["brand"]  # nothing subtracts Brand Ads (ADS-10)
        assert "coverage" in body

    def test_account_level_spend_is_in_no_mla_row(self, client, db, reader) -> None:
        store.upsert_display_days(db, display_facts(), now=T0)
        assert get(client, reader, "by-mla").json()["items"] == []


class TestDisplay:
    """ml-ads-cupones-display S7: the Display tab's campaigns, totals and daily cost."""

    def _seed(self, db) -> None:
        store.upsert_display_days(db, display_facts(), now=T0)
        body = load("display_day_2026_10_05_25713.json")["campaigns"]["body"]
        store.upsert_display_catalog(db, mapper.map_display_catalog(25713, body), now=T0)

    def test_each_campaign_has_its_catalog_figures_and_computed_ratios(self, client, db, reader) -> None:
        self._seed(db)
        body = get(client, reader, "display").json()
        row = next(c for c in body["campaigns"] if c["campaign_id"] == 335306)
        assert (row["name"], row["goal"], row["status"], row["start_date"], row["end_date"]) == (
            "XeroxB110",
            "conversion",
            "active",
            "2026-09-07",
            "2026-11-01",
        )
        assert (row["cost"], row["prints"], row["clicks"], row["reach"]) == (27226.79, 12576, 21, 3498)
        assert (row["attributed_amount"], row["attributed_units"]) == (1658026.88, 9)
        assert row["ctr"] == pytest.approx(21 / 12576)
        assert row["roas"] == pytest.approx(1658026.88 / 27226.79)
        assert len(body["campaigns"]) == 7

    def test_a_ratio_without_its_base_is_null(self, client, db, reader) -> None:
        self._seed(db)
        rows = {c["campaign_id"]: c for c in get(client, reader, "display").json()["campaigns"]}
        assert rows[294806]["cpc"] is None  # captured: no clicks
        assert (rows[340339]["ctr"], rows[340339]["roas"]) == (None, None)  # paused, no activity

    def test_totals_daily_and_coverage(self, client, db, reader) -> None:
        self._seed(db)
        body = get(client, reader, "display").json()
        assert (body["totals"]["cost"], body["totals"]["clicks"], body["totals"]["attributed_units"]) == (
            121938.82,
            91,
            40,
        )
        assert body["daily"] == [{"day": DAY.isoformat(), "cost": 121938.82}]
        assert "coverage" in body

    def test_each_campaign_carries_its_days(self, client, db, reader) -> None:
        self._seed(db)
        rows = {c["campaign_id"]: c for c in get(client, reader, "display").json()["campaigns"]}
        assert rows[335306]["days"] == [{"day": DAY.isoformat(), "cost": 27226.79, "attributed_amount": 1658026.88}]
        assert rows[340339]["days"] == []  # paused, no activity


class TestDisplayContributions:
    """ml-ads-display-contributions S2: a brand contribution for Display, whole account or one campaign.

    The Display days and catalog are the captured 2026-10-05 ones of advertiser 25713; the 2026-10-06 day of 301232,
    the contributions and the Product Ads catalog row are DERIVED."""

    MIX = 301232  # captured: 49464.21 on 2026-10-05

    @pytest.fixture()
    def manager(self, db, rol_admin, admin_auth_headers):
        grant(db, rol_admin, GANANCIA, "ml_metricas.gestionar_aportes_ads")
        TestDisplay()._seed(db)
        from decimal import Decimal

        from app.models.ml_ads import MlAdsCampaign, MlAdsDisplayCampaignDay

        # DERIVED: one more Display day, and a Product Ads campaign whose id collides with a Display one.
        db.add(
            MlAdsDisplayCampaignDay(
                advertiser_id=GAUSS,
                campaign_id=self.MIX,
                day=date(2026, 10, 6),
                consumed_budget=Decimal("1000"),
                raw={},
            )
        )
        db.add(MlAdsCampaign(advertiser_id=GAUSS, campaign_id=self.MIX, name="pads", raw={}))
        from app.models.producto import ProductoERP

        db.add(ProductoERP(item_id=1, codigo="COD1", descripcion="Toner", marca="Xerox"))  # DERIVED: the brand
        db.flush()
        return admin_auth_headers

    @staticmethod
    def _body(**overrides) -> dict:
        body = {
            "channel": "display",
            "advertiser_id": GAUSS,
            "kind": "percentage",
            "value": "10",
            "date_from": "2026-10-01",
            "date_to": "2026-10-31",
            "brand": "Xerox",
        }
        body.update(overrides)
        return {k: v for k, v in body.items() if v is not None}

    @staticmethod
    def _rows(db) -> list[tuple]:
        from app.models.ml_ads import MlAdsCampaignContribution as C

        db.expire_all()
        return [(r.channel, r.advertiser_id, r.campaign_id, r.kind) for r in db.query(C).order_by(C.id)]

    def _post(self, client, headers, **overrides):
        return client.post(f"{BASE}/contributions", headers=headers, json=self._body(**overrides))

    def test_a_whole_account_contribution_is_created_without_a_campaign(self, client, db, manager) -> None:
        response = self._post(client, manager)
        assert response.status_code == 201
        body = response.json()
        assert (body["channel"], body["advertiser_id"], body["campaign_id"], body["value"]) == (
            "display",
            GAUSS,
            None,
            10.0,
        )
        assert self._rows(db) == [("display", GAUSS, None, "percentage")]

    def test_without_a_channel_it_is_product_ads_as_before(self, client, db, manager) -> None:
        response = self._post(client, manager, channel=None, campaign_id=self.MIX)
        assert response.status_code == 201 and response.json()["channel"] == "product_ads"
        assert self._rows(db) == [("product_ads", GAUSS, self.MIX, "percentage")]

    @pytest.mark.parametrize(
        "overrides",
        [{"channel": "product_ads"}, {"channel": None}, {"channel": "brand_ads"}],
        ids=["product-ads-without-campaign", "default-without-campaign", "unknown-channel"],
    )
    def test_a_body_that_breaks_the_channel_shape_is_fastapis_422(self, client, db, manager, overrides) -> None:
        response = self._post(client, manager, **overrides)
        assert response.status_code == 422
        assert response.json()["detail"][0]["loc"][0] == "body"
        assert self._rows(db) == []

    def test_an_overlap_with_the_whole_account_is_the_apps_422_on_date_from(self, client, db, manager) -> None:
        assert self._post(client, manager).status_code == 201
        clash = self._post(client, manager, campaign_id=self.MIX, date_from="2026-10-31", date_to="2026-11-15")
        assert clash.status_code == 422
        error = clash.json()["error"]
        assert error["field"] == "date_from" and "Display" in error["message"]
        assert self._rows(db) == [("display", GAUSS, None, "percentage")]

    def test_an_unknown_display_campaign_is_the_apps_422_on_campaign_id(self, client, db, manager) -> None:
        response = self._post(client, manager, campaign_id=999)
        assert response.status_code == 422 and response.json()["error"]["field"] == "campaign_id"
        assert self._rows(db) == []

    def test_an_edit_cannot_change_the_channel(self, client, db, manager) -> None:
        created = self._post(client, manager, campaign_id=self.MIX).json()
        moved = client.put(
            f"{BASE}/contributions/{created['id']}",
            headers=manager,
            json=self._body(channel="product_ads", campaign_id=self.MIX),
        )
        assert moved.status_code == 422 and moved.json()["error"]["field"] == "channel"
        assert self._rows(db) == [("display", GAUSS, self.MIX, "percentage")]

    def test_the_preview_reads_the_display_spend(self, client, manager) -> None:
        response = client.get(f"{BASE}/contributions/preview", headers=manager, params=self._body(date_to="2026-10-05"))
        assert response.status_code == 200
        assert response.json() == {
            "spend": 121938.82,
            "counted": 12193.88,
            "net": 109744.94,
            "warnings": [],
            "data_through": None,
            "over_spend": False,
        }

    def test_the_display_tab_carries_each_campaign_contribution_and_net(self, client, manager) -> None:
        """301232 at 20% on 10-05 (9892.842) plus a whole-account 10% on 10-06 (100 of its 1000)."""
        assert self._post(client, manager, campaign_id=self.MIX, value="20", date_to="2026-10-05").status_code == 201
        assert self._post(client, manager, date_from="2026-10-06").status_code == 201
        body = get(client, manager, "display", date_from="2026-10-05", date_to="2026-10-06").json()
        rows = {c["campaign_id"]: c for c in body["campaigns"]}
        assert (rows[self.MIX]["cost"], rows[self.MIX]["contribution"], rows[self.MIX]["net"]) == (
            50464.21,
            9992.84,
            40471.37,
        )
        assert (rows[335306]["contribution"], rows[335306]["net"]) == (0.0, 27226.79)
        totals = body["totals"]
        assert (totals["cost"], totals["contribution"], totals["net"]) == (122938.82, 9992.84, 112945.98)

    def test_a_fixed_amount_beyond_the_window_shows_only_the_window_share(self, client, manager) -> None:
        """10000 `full` on 301232 for October; its range spends 50464.21, of which 10-06 alone holds 1000."""
        assert (
            self._post(client, manager, campaign_id=self.MIX, kind="fixed_amount", value="10000", settlement="full")
        ).status_code == 201
        body = get(client, manager, "display", date_from="2026-10-06", date_to="2026-10-06").json()
        [mix] = [c for c in body["campaigns"] if c["campaign_id"] == self.MIX]
        assert (mix["cost"], mix["contribution"], mix["net"]) == (1000.0, 198.16, 801.84)
        assert (body["totals"]["contribution"], body["totals"]["net"]) == (198.16, 801.84)

    def test_the_product_ads_listing_does_not_show_display_contributions(self, client, manager) -> None:
        assert self._post(client, manager, campaign_id=self.MIX).status_code == 201
        listed = get(client, manager, "campaigns", date_from="2026-10-01", date_to="2026-10-31").json()
        [pads] = [c for c in listed["campaigns"] if c["campaign_id"] == self.MIX]
        assert (pads["contributions"], pads["contribution"]) == ([], 0.0)
