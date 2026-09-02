"""Integration tests for `GET /api/ml-ventas-ops/sales` (ml-ventas-listado).

Covers: permission-before-flag gate (403 before 503, same precedent as the
rest of this router), the derived `operation_status`/`goods_status` axes,
filters, deterministic pagination, per-axis facet counts scoped by the
OTHER active filter, and the grouping of a pack's orders into one row.
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
    pack_id: int | None = None,
    total_amount: float = 100,
    shipping_id: int | None = None,
) -> None:
    if shipping_id is None:
        shipping_id = order_id * 10 if shipping_status is not None else None
    order = MlOrdersOps(
        order_id=order_id,
        pack_id=pack_id,
        status=status,
        payment_status=payment_status,
        covered_by_marketplace=covered_by_marketplace,
        ml_last_updated=date_created,
        date_created=date_created,
        seller_id=999,
        total_amount=total_amount,
        paid_amount=total_amount,
        currency_id="ARS",
        shipping_id=shipping_id,
    )
    db.add(order)
    if shipping_id is not None and shipping_status is not None:
        existing = db.query(MlShipmentOps).filter(MlShipmentOps.shipment_id == shipping_id).first()
        if existing is None:
            db.add(MlShipmentOps(shipment_id=shipping_id, order_id=order_id, status=shipping_status))
    if claim_status is not None:
        db.add(RmaClaimML(claim_id=order_id * 100, resource_id=order_id, status=claim_status))
    db.flush()


def _order_ids(body) -> list[int]:
    """Every order id in the page, in group order then member order.

    The listing returns GROUPS now, so a test that used to read
    `sale["order_id"]` has to say which of the two it means. These
    fixtures seed lone orders, so one group is one order -- except in
    `TestPacks`, which is the whole point."""
    return [order["order_id"] for group in body["sales"] for order in group["orders"]]


def _group_holding(body, order_id: int):
    return next(g for g in body["sales"] if any(o["order_id"] == order_id for o in g["orders"]))


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
        sale = _group_holding(body, 1)
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

        sale = _group_holding(resp.json(), 2)
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

        sale = _group_holding(resp.json(), 3)
        assert sale["operation_status"] == "in_dispute"

    def test_unrecognised_status_is_unknown(self, db, client, admin_auth_headers, rol_admin):
        _grant_ml_ops_ver(db, rol_admin)
        _seed_order(db, 4, status="weird_status", date_created=datetime(2026, 8, 4, tzinfo=timezone.utc))
        db.commit()

        resp = client.get("/api/ml-ventas-ops/sales", headers=admin_auth_headers)

        sale = _group_holding(resp.json(), 4)
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
        assert _order_ids(body) == [10]

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
        assert _order_ids(body) == [20]

    def test_sold_month_filter(self, db, client, admin_auth_headers, rol_admin):
        _grant_ml_ops_ver(db, rol_admin)
        _seed_order(db, 30, status="paid", date_created=datetime(2026, 7, 15, tzinfo=timezone.utc))
        _seed_order(db, 31, status="paid", date_created=datetime(2026, 8, 15, tzinfo=timezone.utc))
        db.commit()

        resp = client.get("/api/ml-ventas-ops/sales", params={"sold_month": "2026-08"}, headers=admin_auth_headers)

        body = resp.json()
        assert _order_ids(body) == [31]

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
        first_page = _order_ids(resp.json())
        resp2 = client.get("/api/ml-ventas-ops/sales", params={"limit": 1, "offset": 1}, headers=admin_auth_headers)
        second_page = _order_ids(resp2.json())

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
        assert _order_ids(body) == [1]
        assert body["total"] == 1


class TestPacks:
    """A pack is ONE row.

    Mercado Libre splits a purchase into one order per item, tied together
    by `pack_id`. Rendered one-per-row this reads as several unrelated
    sales -- reported from production on 2026-09-02, where orders
    2000018230951686 and 2000018230945962 (same pack, same shipment, one
    parcel) sat beside 2000018230947902 (a different pack) with the same
    buyer and the same timestamp, and could not be told apart.
    """

    def test_a_pack_is_one_row_carrying_its_orders(self, db, client, admin_auth_headers, rol_admin):
        _grant_ml_ops_ver(db, rol_admin)
        when = datetime(2026, 9, 1, 4, 48, 58, tzinfo=timezone.utc)
        _seed_order(db, 951686, pack_id=816536209, total_amount=27868.10, date_created=when)
        _seed_order(db, 945962, pack_id=816536209, total_amount=24750.00, date_created=when)
        _seed_order(db, 947902, pack_id=816536211, total_amount=27299.00, date_created=when)
        db.commit()

        body = client.get("/api/ml-ventas-ops/sales", headers=admin_auth_headers).json()

        assert body["total"] == 2, "two packs, not three sales"
        assert len(body["sales"]) == 2
        pack = _group_holding(body, 951686)
        assert pack["pack_id"] == 816536209
        assert sorted(o["order_id"] for o in pack["orders"]) == [945962, 951686]
        # What the buyer paid for the parcel, which is the number the
        # operator could not see while the three rows stood apart.
        assert pack["total_amount"] == pytest.approx(52618.10)
        assert _group_holding(body, 947902)["orders"] == [
            o for o in _group_holding(body, 947902)["orders"] if o["order_id"] == 947902
        ]

    def test_an_order_without_a_pack_is_its_own_row(self, db, client, admin_auth_headers, rol_admin):
        _grant_ml_ops_ver(db, rol_admin)
        _seed_order(db, 7, date_created=datetime(2026, 9, 1, tzinfo=timezone.utc))
        db.commit()

        body = client.get("/api/ml-ventas-ops/sales", headers=admin_auth_headers).json()

        assert body["total"] == 1
        group = body["sales"][0]
        assert group["pack_id"] is None
        assert [o["order_id"] for o in group["orders"]] == [7]

    def test_a_pack_id_equal_to_another_order_id_does_not_merge_them(self, db, client, admin_auth_headers, rol_admin):
        """ML draws pack ids and order ids from the same numeric range, so
        an unprefixed `COALESCE(pack_id, order_id)` key would merge a pack
        with an unrelated order that happens to share the number."""
        _grant_ml_ops_ver(db, rol_admin)
        when = datetime(2026, 9, 1, tzinfo=timezone.utc)
        _seed_order(db, 500, pack_id=4242, date_created=when)
        _seed_order(db, 4242, date_created=when)
        db.commit()

        body = client.get("/api/ml-ventas-ops/sales", headers=admin_auth_headers).json()

        assert body["total"] == 2
        assert _group_holding(body, 500)["group_key"] != _group_holding(body, 4242)["group_key"]

    def test_a_pack_whose_orders_disagree_reads_as_mixed(self, db, client, admin_auth_headers, rol_admin):
        """Never collapse a disagreement into one badge: a pack holding a
        cancelled order and a paid one is exactly what deserves a look."""
        _grant_ml_ops_ver(db, rol_admin)
        when = datetime(2026, 9, 1, tzinfo=timezone.utc)
        _seed_order(db, 601, pack_id=777, status="paid", date_created=when)
        _seed_order(db, 602, pack_id=777, status="cancelled", date_created=when)
        db.commit()

        body = client.get("/api/ml-ventas-ops/sales", headers=admin_auth_headers).json()

        assert _group_holding(body, 601)["operation_status"] == "mixed"

    def test_a_filter_keeps_the_whole_pack_not_just_the_matching_order(self, db, client, admin_auth_headers, rol_admin):
        """Filtering the members too would render a pack missing exactly the
        order that failed the filter -- an incomplete parcel shown as a
        complete one."""
        _grant_ml_ops_ver(db, rol_admin)
        when = datetime(2026, 9, 1, tzinfo=timezone.utc)
        _seed_order(db, 701, pack_id=888, status="paid", date_created=when)
        _seed_order(db, 702, pack_id=888, status="cancelled", date_created=when)
        db.commit()

        body = client.get(
            "/api/ml-ventas-ops/sales", params={"operation_status": "cancelled"}, headers=admin_auth_headers
        ).json()

        assert body["total"] == 1
        assert sorted(o["order_id"] for o in body["sales"][0]["orders"]) == [701, 702]

    def test_pagination_never_splits_a_pack_across_two_pages(self, db, client, admin_auth_headers, rol_admin):
        _grant_ml_ops_ver(db, rol_admin)
        _seed_order(db, 801, pack_id=900, date_created=datetime(2026, 9, 2, tzinfo=timezone.utc))
        _seed_order(db, 802, pack_id=900, date_created=datetime(2026, 9, 2, tzinfo=timezone.utc))
        _seed_order(db, 803, date_created=datetime(2026, 9, 1, tzinfo=timezone.utc))
        db.commit()

        first = client.get("/api/ml-ventas-ops/sales", params={"limit": 1}, headers=admin_auth_headers).json()

        assert first["total"] == 2, "two rows: the pack and the lone order"
        assert sorted(_order_ids(first)) == [801, 802], "the pack came back whole on page 1"
