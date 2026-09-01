"""Integration tests for `GET /api/ml-ventas-ops/sales` (ml-ventas-listado).

Covers: permission-before-flag gate (403 before 503, same precedent as the
rest of this router), the derived `operation_status`/`goods_status` axes,
filters, deterministic pagination, and per-axis facet counts scoped by the
OTHER active filter.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.core.config import settings
from app.models.ml_orders_ops import MlOrdersOps, MlShipmentOps
from app.models.permiso import Permiso, RolPermisoBase
from app.models.rma_claim_ml import RmaClaimML
from app.services.ml_orders_ingestion.link_resolver_service import resolve_links


@pytest.fixture(autouse=True)
def _flag_on(monkeypatch):
    # The listing is scoped to the configured seller, so the fixtures'
    # seller has to be the configured one.
    monkeypatch.setattr(settings, "ML_USER_ID", 999)
    monkeypatch.setattr(settings, "ML_ORDERS_OPS_ENABLED", True)


def _grant_ml_ops_ver(db, rol_admin) -> None:
    permiso = db.query(Permiso).filter(Permiso.codigo == "ml_ops.ver").first()
    if not permiso:
        permiso = Permiso(
            codigo="ml_ops.ver", nombre="Ver operaciones ML", descripcion="", categoria="ml_ops", orden=200
        )
        db.add(permiso)
        db.flush()
    db.add(RolPermisoBase(rol_id=rol_admin.id, permiso_id=permiso.id))
    db.flush()


def _seed_order(
    db,
    order_id: int,
    *,
    status: str = "paid",
    payment_status: str | None = None,
    covered_by_marketplace: bool | None = None,
    shipping_status: str | None = None,
    date_created: datetime,
    claim_status: str | None = None,
) -> None:
    shipping_id = order_id * 10 if shipping_status is not None else None
    order = MlOrdersOps(
        order_id=order_id,
        status=status,
        payment_status=payment_status,
        covered_by_marketplace=covered_by_marketplace,
        ml_last_updated=date_created,
        date_created=date_created,
        seller_id=999,
        total_amount=100,
        paid_amount=100,
        currency_id="ARS",
        shipping_id=shipping_id,
    )
    db.add(order)
    if shipping_id is not None:
        db.add(MlShipmentOps(shipment_id=shipping_id, order_id=order_id, status=shipping_status))
    if claim_status is not None:
        db.add(RmaClaimML(claim_id=order_id * 100, resource_id=order_id, status=claim_status))
    db.flush()


class TestPermissionAndFlagGate:
    def test_no_permission_is_403(self, client, auth_headers):
        resp = client.get("/api/ml-ventas-ops/sales", headers=auth_headers)
        assert resp.status_code == 403

    def test_flag_off_with_permission_is_503(self, client, admin_auth_headers, db, rol_admin, monkeypatch):
        _grant_ml_ops_ver(db, rol_admin)
        monkeypatch.setattr(settings, "ML_ORDERS_OPS_ENABLED", False)
        resp = client.get("/api/ml-ventas-ops/sales", headers=admin_auth_headers)
        assert resp.status_code == 503

    def test_no_permission_wins_over_flag_off(self, client, auth_headers, monkeypatch):
        """403 must win over 503 regardless of flag state (same precedent
        as the rest of this router)."""
        monkeypatch.setattr(settings, "ML_ORDERS_OPS_ENABLED", False)
        resp = client.get("/api/ml-ventas-ops/sales", headers=auth_headers)
        assert resp.status_code == 403


class TestOperationStatusDerivationInResponse:
    def test_cancelled_order_shows_as_cancelled(self, db, client, admin_auth_headers, rol_admin):
        _grant_ml_ops_ver(db, rol_admin)
        _seed_order(db, 1, status="cancelled", date_created=datetime(2026, 8, 1, tzinfo=timezone.utc))
        db.commit()

        resp = client.get("/api/ml-ventas-ops/sales", headers=admin_auth_headers)

        assert resp.status_code == 200
        body = resp.json()
        sale = next(s for s in body["sales"] if s["order_id"] == 1)
        assert sale["operation_status"] == "cancelled"

    def test_delivered_order_with_no_claim_shows_as_delivered(self, db, client, admin_auth_headers, rol_admin):
        _grant_ml_ops_ver(db, rol_admin)
        _seed_order(
            db,
            2,
            status="paid",
            shipping_status="delivered",
            date_created=datetime(2026, 8, 2, tzinfo=timezone.utc),
        )
        db.commit()

        resp = client.get("/api/ml-ventas-ops/sales", headers=admin_auth_headers)

        sale = next(s for s in resp.json()["sales"] if s["order_id"] == 2)
        assert sale["operation_status"] == "delivered"
        assert sale["goods_status"] == "delivered"

    def test_open_claim_forces_in_dispute_even_when_shipped(self, db, client, admin_auth_headers, rol_admin):
        _grant_ml_ops_ver(db, rol_admin)
        _seed_order(
            db,
            3,
            status="paid",
            shipping_status="delivered",
            claim_status="opened",
            date_created=datetime(2026, 8, 3, tzinfo=timezone.utc),
        )
        resolve_links(db)
        db.commit()

        resp = client.get("/api/ml-ventas-ops/sales", headers=admin_auth_headers)

        sale = next(s for s in resp.json()["sales"] if s["order_id"] == 3)
        assert sale["operation_status"] == "in_dispute"

    def test_unrecognised_status_is_unknown(self, db, client, admin_auth_headers, rol_admin):
        _grant_ml_ops_ver(db, rol_admin)
        _seed_order(db, 4, status="weird_status", date_created=datetime(2026, 8, 4, tzinfo=timezone.utc))
        db.commit()

        resp = client.get("/api/ml-ventas-ops/sales", headers=admin_auth_headers)

        sale = next(s for s in resp.json()["sales"] if s["order_id"] == 4)
        assert sale["operation_status"] == "unknown"


class TestFilters:
    def test_operation_status_filter(self, db, client, admin_auth_headers, rol_admin):
        _grant_ml_ops_ver(db, rol_admin)
        _seed_order(db, 10, status="cancelled", date_created=datetime(2026, 8, 1, tzinfo=timezone.utc))
        _seed_order(
            db, 11, status="paid", shipping_status="delivered", date_created=datetime(2026, 8, 2, tzinfo=timezone.utc)
        )
        db.commit()

        resp = client.get(
            "/api/ml-ventas-ops/sales", params={"operation_status": "cancelled"}, headers=admin_auth_headers
        )

        assert resp.status_code == 200
        body = resp.json()
        assert [s["order_id"] for s in body["sales"]] == [10]

    def test_invalid_operation_status_is_422(self, db, client, admin_auth_headers, rol_admin):
        _grant_ml_ops_ver(db, rol_admin)
        resp = client.get("/api/ml-ventas-ops/sales", params={"operation_status": "bogus"}, headers=admin_auth_headers)
        assert resp.status_code == 422

    def test_goods_status_filter(self, db, client, admin_auth_headers, rol_admin):
        _grant_ml_ops_ver(db, rol_admin)
        _seed_order(
            db, 20, status="paid", shipping_status="shipped", date_created=datetime(2026, 8, 1, tzinfo=timezone.utc)
        )
        _seed_order(
            db,
            21,
            status="paid",
            shipping_status="delivered",
            date_created=datetime(2026, 8, 2, tzinfo=timezone.utc),
        )
        db.commit()

        resp = client.get("/api/ml-ventas-ops/sales", params={"goods_status": "in_transit"}, headers=admin_auth_headers)

        body = resp.json()
        assert [s["order_id"] for s in body["sales"]] == [20]

    def test_sold_month_filter(self, db, client, admin_auth_headers, rol_admin):
        _grant_ml_ops_ver(db, rol_admin)
        _seed_order(db, 30, status="paid", date_created=datetime(2026, 7, 15, tzinfo=timezone.utc))
        _seed_order(db, 31, status="paid", date_created=datetime(2026, 8, 15, tzinfo=timezone.utc))
        db.commit()

        resp = client.get("/api/ml-ventas-ops/sales", params={"sold_month": "2026-08"}, headers=admin_auth_headers)

        body = resp.json()
        assert [s["order_id"] for s in body["sales"]] == [31]

    def test_invalid_sold_month_is_422(self, db, client, admin_auth_headers, rol_admin):
        _grant_ml_ops_ver(db, rol_admin)
        resp = client.get("/api/ml-ventas-ops/sales", params={"sold_month": "not-a-month"}, headers=admin_auth_headers)
        assert resp.status_code == 422


class TestPagination:
    def test_deterministic_tiebreaker_on_equal_date_created(self, db, client, admin_auth_headers, rol_admin):
        """Two orders with the IDENTICAL `date_created` must still sort
        deterministically (by `order_id` DESC) -- not by insertion/DB
        scan order, which Postgres does not guarantee."""
        _grant_ml_ops_ver(db, rol_admin)
        same_moment = datetime(2026, 8, 1, tzinfo=timezone.utc)
        _seed_order(db, 100, status="paid", date_created=same_moment)
        _seed_order(db, 101, status="paid", date_created=same_moment)
        db.commit()

        resp = client.get("/api/ml-ventas-ops/sales", params={"limit": 1, "offset": 0}, headers=admin_auth_headers)
        first_page = [s["order_id"] for s in resp.json()["sales"]]
        resp2 = client.get("/api/ml-ventas-ops/sales", params={"limit": 1, "offset": 1}, headers=admin_auth_headers)
        second_page = [s["order_id"] for s in resp2.json()["sales"]]

        assert first_page == [101]
        assert second_page == [100]

    def test_total_reflects_filtered_count_not_page_size(self, db, client, admin_auth_headers, rol_admin):
        _grant_ml_ops_ver(db, rol_admin)
        for i in range(5):
            _seed_order(db, 200 + i, status="paid", date_created=datetime(2026, 8, 1 + i, tzinfo=timezone.utc))
        db.commit()

        resp = client.get("/api/ml-ventas-ops/sales", params={"limit": 2}, headers=admin_auth_headers)

        body = resp.json()
        assert body["total"] == 5
        assert len(body["sales"]) == 2


class TestFacetCounts:
    def test_facets_scoped_by_the_other_active_filter(self, db, client, admin_auth_headers, rol_admin):
        _grant_ml_ops_ver(db, rol_admin)
        _seed_order(
            db,
            300,
            status="paid",
            shipping_status="shipped",
            date_created=datetime(2026, 8, 1, tzinfo=timezone.utc),
        )
        _seed_order(
            db,
            301,
            status="cancelled",
            shipping_status="shipped",
            date_created=datetime(2026, 8, 2, tzinfo=timezone.utc),
        )
        _seed_order(
            db,
            302,
            status="paid",
            shipping_status="delivered",
            date_created=datetime(2026, 8, 3, tzinfo=timezone.utc),
        )
        db.commit()

        # Filtering goods_status=in_transit (orders 300, 301) must still
        # report the operation_status facet counts WITHIN that scope, not
        # the unfiltered total (which would also count order 302).
        resp = client.get("/api/ml-ventas-ops/sales", params={"goods_status": "in_transit"}, headers=admin_auth_headers)

        facets = resp.json()["facets"]["operation_status"]
        assert facets["paid"] == 1
        assert facets["cancelled"] == 1
        assert facets["delivered"] == 0


class TestSoldMonthOutOfRangeIsNot500:
    """`int("99999")` parses and month 1 is valid, so only `datetime`
    rejects the year — and it did so outside the guard. The existing test
    used "not-a-month", which dies at `int()` and never reaches that line."""

    def test_an_impossible_year_is_422(self, db, client, admin_auth_headers, rol_admin) -> None:
        _grant_ml_ops_ver(db, rol_admin)

        for bad in ("99999-01", "0000-05"):
            resp = client.get("/api/ml-ventas-ops/sales", params={"sold_month": bad}, headers=admin_auth_headers)
            assert resp.status_code == 422, f"{bad} devolvió {resp.status_code}"


class TestListingIsScopedToTheSeller:
    """Without a seller filter the listing scans every row in the table,
    and shows orders belonging to another account if one ever lands there.
    The sweep already scopes its work this way."""

    def test_only_the_configured_seller_is_listed(self, db, client, admin_auth_headers, rol_admin, monkeypatch):
        _grant_ml_ops_ver(db, rol_admin)
        monkeypatch.setattr(settings, "ML_USER_ID", 999)

        when = datetime.now(timezone.utc)
        db.add(MlOrdersOps(order_id=1, seller_id=999, ml_last_updated=when, date_created=when, status="paid"))
        db.add(MlOrdersOps(order_id=2, seller_id=555, ml_last_updated=when, date_created=when, status="paid"))
        db.commit()

        resp = client.get("/api/ml-ventas-ops/sales", headers=admin_auth_headers)

        assert resp.status_code == 200
        body = resp.json()
        assert [row["order_id"] for row in body["sales"]] == [1]
        assert body["total"] == 1
