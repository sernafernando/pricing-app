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

    @pytest.mark.parametrize("path", ["by-mla", "by-product", "account-level"])
    def test_authentication_is_required(self, client, path) -> None:
        assert client.get(f"{BASE}/{path}", params=RANGE).status_code in (401, 403)

    @pytest.mark.parametrize("path", ["by-mla", "by-product", "account-level"])
    def test_without_ver_ganancia_it_is_403_and_names_the_permission(self, client, db, auth_headers, path) -> None:
        response = get(client, auth_headers, path)
        assert response.status_code == 403
        assert GANANCIA in response.json()["error"]["message"]

    def test_the_only_writes_are_the_brand_contributions(self) -> None:
        writes = {route.path for route in ml_ads.router.routes if getattr(route, "methods", set()) - {"GET", "HEAD"}}
        assert writes == {"/ml-ads/contributions"}


class TestValidation:
    @pytest.mark.parametrize("path", ["by-mla", "by-product", "account-level"])
    def test_an_inverted_range_is_422(self, client, reader, path) -> None:
        response = get(client, reader, path, date_from="2026-10-06", date_to="2026-10-05")
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "VALIDATION_ERROR"

    @pytest.mark.parametrize("path", ["by-mla", "by-product", "account-level"])
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
