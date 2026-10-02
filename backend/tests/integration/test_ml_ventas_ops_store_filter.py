"""ODD `metricas-ml-tablero` T1: the official-store filter on Ventas ML.

`stores` (CSV of `mlp_official_store_id` values plus the `sin_tienda`
sentinel) is a GROUP filter like the product facets: a pack matches when ANY
item of ANY member is published in one of the chosen stores, and the whole
pack comes back. The list, the KPI strip and the CSV export read the same
param through the same `build_scope`, so they can never disagree.

`facets.stores` counts groups per store bucket WITHOUT the store filter
itself (every facet is scoped by the OTHER filters, never by its own axis).
"""

from __future__ import annotations

import csv
import io
from contextlib import contextmanager
from datetime import datetime, timezone

import pytest
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.mercadolibre_item_publicado import MercadoLibreItemPublicado
from app.models.ml_orders_ops import MlOrderItemOps
from app.routers import ml_ventas_ops
from tests.integration.test_ml_ventas_ops_sales_router import _grant_ml_ops_ver, _order_ids, _seed_order

SEP_1 = datetime(2026, 9, 1, tzinfo=timezone.utc)
GAUSS = 57997
TPLINK = 2645


@pytest.fixture(autouse=True)
def _flag_on(monkeypatch):
    monkeypatch.setattr(settings, "ML_USER_ID", 999)
    monkeypatch.setattr(settings, "ML_ORDERS_OPS_ENABLED", True)


@pytest.fixture(autouse=True)
def _bg_sessions(db, monkeypatch):
    """The export opens its own short sessions; bind them to the test's."""

    @contextmanager
    def _fake():
        session = Session(bind=db.get_bind())
        try:
            yield session
        finally:
            session.close()

    monkeypatch.setattr(ml_ventas_ops, "get_background_db", _fake, raising=False)


def _item(db, order_id: int, mla: str) -> None:
    db.add(MlOrderItemOps(order_id=order_id, item_id=mla, quantity=1, unit_price=100, title=f"Item {mla}"))
    db.flush()


def _publicacion(db, mlp_id: int, mla: str, store_id: int | None) -> None:
    db.add(MercadoLibreItemPublicado(mlp_id=mlp_id, mlp_publicationID=mla, mlp_official_store_id=store_id))
    db.flush()


@pytest.fixture()
def catalogo(db, rol_admin):
    """Four lone sales + one pack:
    - 97001: Gauss MLA
    - 97002: TP-Link MLA
    - 97003: MLA with a publication row but NO store -> sin_tienda
    - 97004: MLA with no publication row at all -> sin_tienda
    - pack 97500 = 97005 (sin tienda) + 97006 (TP-Link) -> matches TP-Link whole
    """
    _grant_ml_ops_ver(db, rol_admin)
    for oid in (97001, 97002, 97003, 97004):
        _seed_order(db, oid, date_created=SEP_1)
    _seed_order(db, 97005, pack_id=97500, date_created=SEP_1)
    _seed_order(db, 97006, pack_id=97500, date_created=SEP_1)
    _publicacion(db, 1, "MLA1001", GAUSS)
    _publicacion(db, 2, "MLA1002", TPLINK)
    _publicacion(db, 3, "MLA1003", None)
    _publicacion(db, 6, "MLA1006", TPLINK)
    _item(db, 97001, "MLA1001")
    _item(db, 97002, "MLA1002")
    _item(db, 97003, "MLA1003")
    _item(db, 97004, "MLA1004")
    _item(db, 97005, "MLA1004")
    _item(db, 97006, "MLA1006")
    db.commit()


class TestStoreFilterOnTheListing:
    def test_one_store_keeps_only_its_sales(self, db, client, admin_auth_headers, catalogo):
        body = client.get("/api/ml-ventas-ops/sales", params={"stores": str(GAUSS)}, headers=admin_auth_headers)

        assert body.status_code == 200
        assert _order_ids(body.json()) == [97001]

    def test_a_pack_with_one_matching_item_comes_back_whole(self, db, client, admin_auth_headers, catalogo):
        body = client.get("/api/ml-ventas-ops/sales", params={"stores": str(TPLINK)}, headers=admin_auth_headers).json()

        assert sorted(_order_ids(body)) == [97002, 97005, 97006]
        assert body["total"] == 2

    def test_sin_tienda_covers_no_publication_row_and_null_store(self, db, client, admin_auth_headers, catalogo):
        body = client.get(
            "/api/ml-ventas-ops/sales", params={"stores": "sin_tienda"}, headers=admin_auth_headers
        ).json()

        # 97003 (row with NULL store), 97004 (no row) and the pack (97005 has
        # no row) -- the pack comes back whole, TP-Link member included.
        assert sorted(_order_ids(body)) == [97003, 97004, 97005, 97006]

    def test_several_stores_are_a_union(self, db, client, admin_auth_headers, catalogo):
        body = client.get(
            "/api/ml-ventas-ops/sales", params={"stores": f"{GAUSS},sin_tienda"}, headers=admin_auth_headers
        ).json()

        assert sorted(_order_ids(body)) == [97001, 97003, 97004, 97005, 97006]

    def test_no_param_filters_nothing(self, db, client, admin_auth_headers, catalogo):
        body = client.get("/api/ml-ventas-ops/sales", headers=admin_auth_headers).json()

        assert body["total"] == 5

    @pytest.mark.parametrize("bad", ["abc", "57997,,2645", "99999999999999"])
    def test_a_bad_token_is_422(self, db, client, admin_auth_headers, catalogo, bad):
        resp = client.get("/api/ml-ventas-ops/sales", params={"stores": bad}, headers=admin_auth_headers)

        assert resp.status_code == 422


class TestStoreFacetCounts:
    def test_counts_groups_per_store_bucket(self, db, client, admin_auth_headers, catalogo):
        facets = client.get("/api/ml-ventas-ops/sales", headers=admin_auth_headers).json()["facets"]

        # The pack counts under BOTH buckets it touches, like a mixed pack
        # does in the status facets.
        assert facets["stores"] == {str(GAUSS): 1, str(TPLINK): 2, "sin_tienda": 3}
        assert facets["stores_total"] == 5

    def test_the_store_facet_ignores_its_own_filter(self, db, client, admin_auth_headers, catalogo):
        facets = client.get(
            "/api/ml-ventas-ops/sales", params={"stores": str(GAUSS)}, headers=admin_auth_headers
        ).json()["facets"]

        assert facets["stores"][str(TPLINK)] == 2
        assert facets["stores_total"] == 5
        # ...but the OTHER axes are narrowed by it.
        assert facets["operation_status_total"] == 1

    def test_the_store_facet_obeys_the_other_filters(self, db, client, admin_auth_headers, catalogo):
        facets = client.get("/api/ml-ventas-ops/sales", params={"q": "97001"}, headers=admin_auth_headers).json()[
            "facets"
        ]

        assert facets["stores"] == {str(GAUSS): 1}
        assert facets["stores_total"] == 1


class TestStoreFilterReachesKpisAndExport:
    def test_kpis_count_only_the_filtered_store(self, db, client, admin_auth_headers, catalogo):
        params = {"stores": str(TPLINK), "include_unknown": "true", "include_in_dispute": "true"}
        kpis = client.get("/api/ml-ventas-ops/sales/kpis", params=params, headers=admin_auth_headers).json()
        listing = client.get("/api/ml-ventas-ops/sales", params=params, headers=admin_auth_headers).json()

        assert kpis["groups_count"] == listing["total"] == 2

    def test_export_holds_only_the_filtered_store(self, db, client, admin_auth_headers, catalogo):
        resp = client.get("/api/ml-ventas-ops/sales/export", params={"stores": str(GAUSS)}, headers=admin_auth_headers)

        assert resp.status_code == 200
        rows = list(csv.DictReader(io.StringIO(resp.content.decode("utf-8-sig")), delimiter=";"))
        assert len(rows) == 1
        assert "97001" in ";".join(rows[0].values())

    def test_export_rejects_a_bad_token(self, db, client, admin_auth_headers, catalogo):
        resp = client.get("/api/ml-ventas-ops/sales/export", params={"stores": "nope"}, headers=admin_auth_headers)

        assert resp.status_code == 422


class TestStoreFacetOnlyWhenFacetsAreWanted:
    """The store chips' count is a whole-scope aggregate over the order items
    and the publications. The listing needs it; the CSV export's pages never
    read facets, so they must never pay for it."""

    def test_the_listing_counts_stores(self, db, client, admin_auth_headers, catalogo, query_counter):
        with query_counter() as counter:
            resp = client.get("/api/ml-ventas-ops/sales", headers=admin_auth_headers)

        assert resp.status_code == 200
        assert counter.matching("tb_mercadolibre_items_publicados") == 1

    def test_export_pages_never_run_the_store_facet(self, db, client, admin_auth_headers, catalogo, query_counter):
        with query_counter() as counter:
            resp = client.get("/api/ml-ventas-ops/sales/export", headers=admin_auth_headers)

        assert resp.status_code == 200
        assert len(resp.content.decode("utf-8-sig").strip().splitlines()) > 1
        assert counter.matching("tb_mercadolibre_items_publicados") == 0
