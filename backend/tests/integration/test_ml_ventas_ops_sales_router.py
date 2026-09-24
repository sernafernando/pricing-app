"""Integration tests for `GET /api/ml-ventas-ops/sales` (ml-ventas-listado).

Covers: permission-before-flag gate (403 before 503, same precedent as the
rest of this router), the derived `operation_status`/`goods_status` axes,
filters, deterministic pagination, per-axis facet counts scoped by the
OTHER active filter, and the grouping of a pack's orders into one row.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest

from app.core.config import settings
from app.models.ml_order_metrics import MlOrderMetrics, MlOrderMetricsDirty
from app.models.ml_orders_ops import MlOrdersOps, MlShipmentOps
from app.models.ml_payments import MlPaymentCharge, MlPaymentOps
from app.models.permiso import Permiso, RolPermisoBase
from app.models.rma_claim_ml import RmaClaimML
from app.services.ml_orders_ingestion.link_resolver_service import resolve_links
from app.services.order_metrics.constants import CURRENT_FORMULA_VERSION
from app.services.order_metrics.queue import POISON_THRESHOLD
from app.services.order_metrics.store import recompute_order_metrics


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
    ml_last_updated: datetime | None = None,
    logistic_type: str | None = None,
    has_no_shipping_tag: bool = False,
) -> None:
    if shipping_id is None:
        shipping_id = order_id * 10 if (shipping_status is not None or logistic_type is not None) else None
    order = MlOrdersOps(
        order_id=order_id,
        pack_id=pack_id,
        status=status,
        payment_status=payment_status,
        covered_by_marketplace=covered_by_marketplace,
        # Defaults to the sale date, but separable on purpose: sorting by
        # last update only means something when an OLD sale can have been
        # touched recently, which is the case this listing has to surface.
        ml_last_updated=ml_last_updated or date_created,
        date_created=date_created,
        seller_id=999,
        total_amount=total_amount,
        paid_amount=total_amount,
        currency_id="ARS",
        shipping_id=shipping_id,
        has_no_shipping_tag=has_no_shipping_tag,
    )
    db.add(order)
    if shipping_id is not None and (shipping_status is not None or logistic_type is not None):
        existing = db.query(MlShipmentOps).filter(MlShipmentOps.shipment_id == shipping_id).first()
        if existing is None:
            db.add(
                MlShipmentOps(
                    shipment_id=shipping_id,
                    order_id=order_id,
                    status=shipping_status,
                    logistic_type=logistic_type,
                )
            )
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
        assert [o["order_id"] for o in _group_holding(body, 947902)["orders"]] == [947902]

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

        # The half the name promises and the first assertions do not prove:
        # page 2 must hold the OTHER row, with no member of the pack in it.
        second = client.get(
            "/api/ml-ventas-ops/sales", params={"limit": 1, "offset": 1}, headers=admin_auth_headers
        ).json()

        assert _order_ids(second) == [803]


class TestModoLogistico:
    """The resolved logistic mode (design D1 of ml-ventas-modo-logistico):
    the real shipment ALWAYS outranks the `no_shipping` tag."""

    def test_shipment_wins_over_conflicting_tag(self, db, client, admin_auth_headers, rol_admin):
        """Order 2000016977234624, verified in production: tagged
        `no_shipping` AND carries a delivered `cross_docking` shipment. A
        tag-only badge would call this delivered sale "Retiro"."""
        _grant_ml_ops_ver(db, rol_admin)
        _seed_order(
            db,
            2000016977234624,
            shipping_status="delivered",
            logistic_type="cross_docking",
            has_no_shipping_tag=True,
            date_created=datetime(2026, 9, 1, tzinfo=timezone.utc),
        )
        db.commit()

        body = client.get("/api/ml-ventas-ops/sales", headers=admin_auth_headers).json()

        sale = _group_holding(body, 2000016977234624)
        assert sale["modo_logistico"] == "cross_docking"
        assert sale["orders"][0]["modo_logistico"] == "cross_docking"

    def test_tag_decides_only_when_there_is_no_shipment(self, db, client, admin_auth_headers, rol_admin):
        _grant_ml_ops_ver(db, rol_admin)
        _seed_order(
            db,
            10,
            has_no_shipping_tag=True,
            date_created=datetime(2026, 9, 1, tzinfo=timezone.utc),
        )
        db.commit()

        body = client.get("/api/ml-ventas-ops/sales", headers=admin_auth_headers).json()

        assert _group_holding(body, 10)["modo_logistico"] == "retiro"

    def test_no_shipment_no_tag_reads_as_unknown(self, db, client, admin_auth_headers, rol_admin):
        _grant_ml_ops_ver(db, rol_admin)
        _seed_order(db, 11, date_created=datetime(2026, 9, 1, tzinfo=timezone.utc))
        db.commit()

        body = client.get("/api/ml-ventas-ops/sales", headers=admin_auth_headers).json()

        assert _group_holding(body, 11)["modo_logistico"] == "desconocido"

    def test_unobserved_logistic_type_passes_through(self, db, client, admin_auth_headers, rol_admin):
        _grant_ml_ops_ver(db, rol_admin)
        _seed_order(
            db,
            12,
            logistic_type="a_brand_new_ml_type",
            date_created=datetime(2026, 9, 1, tzinfo=timezone.utc),
        )
        db.commit()

        body = client.get("/api/ml-ventas-ops/sales", headers=admin_auth_headers).json()

        assert _group_holding(body, 12)["modo_logistico"] == "a_brand_new_ml_type"

    def test_pack_mixing_modes_collapses_to_mixed(self, db, client, admin_auth_headers, rol_admin):
        _grant_ml_ops_ver(db, rol_admin)
        when = datetime(2026, 9, 1, tzinfo=timezone.utc)
        _seed_order(db, 21, pack_id=999, logistic_type="cross_docking", date_created=when)
        _seed_order(db, 22, pack_id=999, logistic_type="self_service", date_created=when)
        db.commit()

        body = client.get("/api/ml-ventas-ops/sales", headers=admin_auth_headers).json()

        assert _group_holding(body, 21)["modo_logistico"] == "mixed"

    def test_pack_single_mode_shows_that_mode(self, db, client, admin_auth_headers, rol_admin):
        _grant_ml_ops_ver(db, rol_admin)
        when = datetime(2026, 9, 1, tzinfo=timezone.utc)
        _seed_order(db, 31, pack_id=888, logistic_type="fulfillment", date_created=when)
        _seed_order(db, 32, pack_id=888, logistic_type="fulfillment", date_created=when)
        db.commit()

        body = client.get("/api/ml-ventas-ops/sales", headers=admin_auth_headers).json()

        assert _group_holding(body, 31)["modo_logistico"] == "fulfillment"


class TestFacetTotalsAreRowsNotBuckets:
    """A mixed pack counts in TWO buckets, so summing the buckets
    double-counts it. The listing's "Todas" needs the number of rows it
    would render, or the chip contradicts the table under it."""

    def test_a_mixed_pack_makes_the_bucket_sum_exceed_the_row_count(self, db, client, admin_auth_headers, rol_admin):
        _grant_ml_ops_ver(db, rol_admin)
        when = datetime(2026, 9, 1, tzinfo=timezone.utc)
        _seed_order(db, 901, pack_id=777, status="paid", date_created=when)
        _seed_order(db, 902, pack_id=777, status="cancelled", date_created=when)
        db.commit()

        body = client.get("/api/ml-ventas-ops/sales", headers=admin_auth_headers).json()
        facets = body["facets"]

        assert body["total"] == 1, "one pack, one row"
        assert facets["operation_status"]["paid"] == 1
        assert facets["operation_status"]["cancelled"] == 1
        assert sum(facets["operation_status"].values()) == 2, "the buckets legitimately sum to more"
        # ...and this is the number the chip must show.
        assert facets["operation_status_total"] == 1
        assert facets["goods_status_total"] == 1


class TestAFilterNeverSplitsAPack:
    def test_the_month_filter_keeps_a_pack_that_straddles_midnight_whole(
        self, db, client, admin_auth_headers, rol_admin
    ):
        """A pack whose orders fall either side of a month boundary must
        still come back whole -- the same rule the status filter follows."""
        _grant_ml_ops_ver(db, rol_admin)
        _seed_order(db, 1001, pack_id=555, date_created=datetime(2026, 8, 31, 23, 59, tzinfo=timezone.utc))
        _seed_order(db, 1002, pack_id=555, date_created=datetime(2026, 9, 1, 0, 1, tzinfo=timezone.utc))
        db.commit()

        body = client.get(
            "/api/ml-ventas-ops/sales", params={"sold_month": "2026-09"}, headers=admin_auth_headers
        ).json()

        assert body["total"] == 1
        assert sorted(o["order_id"] for o in body["sales"][0]["orders"]) == [1001, 1002]


def _payment(
    db,
    payment_id: int,
    order_id: int,
    status: str = "approved",
    net_received_amount=None,
    transaction_amount_refunded=None,
) -> None:
    db.add(
        MlPaymentOps(
            payment_id=payment_id,
            order_id=order_id,
            status=status,
            net_received_amount=net_received_amount,
            transaction_amount_refunded=transaction_amount_refunded,
        )
    )


def _stored_metrics(
    db,
    order_id: int,
    *,
    total_gauss=None,
    gauss_status: str = "ok",
    markup_pct=None,
    costo_mercaderia=None,
    formula_version: int = CURRENT_FORMULA_VERSION,
) -> None:
    """Directly seeds a `ml_order_metrics` row (ventas-ml-rediseno PR7) --
    the STORED value the readers must use, deliberately not derived from
    any live payment/cost fixture, so a test using this helper pins the
    reader path, never the producer. `costo_mercaderia` must accompany a
    non-`None` `markup_pct` (`OrderMetrics.__post_init__`'s own invariant:
    a markup against an unknown/zero cost is never a real number)."""
    db.add(
        MlOrderMetrics(
            order_id=order_id,
            total_gauss=total_gauss,
            gauss_status=gauss_status,
            markup_pct=markup_pct,
            costo_mercaderia=costo_mercaderia,
            formula_version=formula_version,
            computed_at=datetime(2026, 9, 1, tzinfo=timezone.utc),
        )
    )


def _charge(db, payment_id: int, name: str, type_: str, amount, refunded=None) -> None:
    db.add(
        MlPaymentCharge(
            payment_id=payment_id,
            name=name,
            type=type_,
            amount=amount,
            refunded=refunded,
        )
    )


class TestNetoInListing:
    """`neto` on `SaleListItem`/`SaleGroup` (ml-neto-en-listado). The rule
    itself is `compute_breakdown`'s (obs #1960/#1966); these tests pin that
    the listing reuses it, never a second copy, and never per-row queries.
    """

    def test_two_approved_payments_are_summed(self, db, client, admin_auth_headers, rol_admin):
        """Order 2000018322969636 -- two approved payments split the total."""
        _grant_ml_ops_ver(db, rol_admin)
        order_id = 2000018322969636
        _seed_order(db, order_id, date_created=datetime(2026, 9, 1, tzinfo=timezone.utc))
        _payment(db, 1, order_id, status="approved", net_received_amount=Decimal("7371.11"))
        _payment(db, 2, order_id, status="approved", net_received_amount=Decimal("12528.89"))
        db.commit()

        body = client.get("/api/ml-ventas-ops/sales", headers=admin_auth_headers).json()

        sale = _group_holding(body, order_id)
        assert sale["neto"] == pytest.approx(19900.00)
        assert sale["orders"][0]["neto"] == pytest.approx(19900.00)

    def test_fully_refunded_sale_nets_exactly_zero(self, db, client, admin_auth_headers, rol_admin):
        """The reported `net_received_amount` stays positive even though
        everything was refunded -- the listing must not show that lie."""
        _grant_ml_ops_ver(db, rol_admin)
        order_id = 2000018325540962
        _seed_order(db, order_id, date_created=datetime(2026, 9, 1, tzinfo=timezone.utc))
        _payment(
            db,
            20,
            order_id,
            status="refunded",
            net_received_amount=Decimal("27614.00"),
            transaction_amount_refunded=Decimal("29000.00"),
        )
        _charge(db, 20, "meli_percentage_fee", "fee", Decimal("1386.00"), refunded=Decimal("1386.00"))
        db.commit()

        body = client.get("/api/ml-ventas-ops/sales", headers=admin_auth_headers).json()

        sale = _group_holding(body, order_id)
        assert sale["neto"] == pytest.approx(0.0)

    def test_order_without_synced_payments_has_neto_none(self, db, client, admin_auth_headers, rol_admin):
        """`None`, never a fabricated zero -- a zero means "returned", not
        "not synced yet"."""
        _grant_ml_ops_ver(db, rol_admin)
        _seed_order(db, 55, date_created=datetime(2026, 9, 1, tzinfo=timezone.utc))
        db.commit()

        body = client.get("/api/ml-ventas-ops/sales", headers=admin_auth_headers).json()

        sale = _group_holding(body, 55)
        assert sale["neto"] is None
        assert sale["orders"][0]["neto"] is None

    def test_pack_neto_is_sum_of_its_orders(self, db, client, admin_auth_headers, rol_admin):
        _grant_ml_ops_ver(db, rol_admin)
        when = datetime(2026, 9, 1, tzinfo=timezone.utc)
        _seed_order(db, 61001, pack_id=61000, date_created=when)
        _seed_order(db, 61002, pack_id=61000, date_created=when)
        _payment(db, 61, 61001, status="approved", net_received_amount=Decimal("1000.00"))
        _payment(db, 62, 61002, status="approved", net_received_amount=Decimal("500.00"))
        db.commit()

        body = client.get("/api/ml-ventas-ops/sales", headers=admin_auth_headers).json()

        pack = _group_holding(body, 61001)
        assert pack["neto"] == pytest.approx(1500.00)

    def test_buyer_charge_does_not_alter_neto(self, db, client, admin_auth_headers, rol_admin):
        """A buyer-paid `financing_fee` refunded alongside a partial return
        must NOT be folded into `seller_refunded` -- only a SELLER charge's
        `refunded` is added back by the formula. If the exclusion were
        dropped, the buyer charge's 40 would wrongly cancel out the 50
        refunded, and neto would read 100 instead of 60."""
        _grant_ml_ops_ver(db, rol_admin)
        order_id = 71
        _seed_order(db, order_id, date_created=datetime(2026, 9, 1, tzinfo=timezone.utc))
        _payment(
            db,
            71,
            order_id,
            status="refunded",
            net_received_amount=Decimal("100.00"),
            transaction_amount_refunded=Decimal("50.00"),
        )
        _charge(db, 71, "meli_percentage_fee", "fee", Decimal("10.00"), refunded=Decimal("10.00"))
        _charge(db, 71, "financing_fee", "fee", Decimal("40.00"), refunded=Decimal("40.00"))
        db.commit()

        body = client.get("/api/ml-ventas-ops/sales", headers=admin_auth_headers).json()

        sale = _group_holding(body, order_id)
        assert sale["neto"] == pytest.approx(60.00)

    def test_sirtac_add_back_carries_neto_depositado_and_retenciones(self, db, client, admin_auth_headers, rol_admin):
        """ml-ventas-neto-iibb-varios PR1.T12: the listing tooltip needs
        `neto_depositado`/`retenciones_recuperables` at both row and group
        level, sourced from the same bulk fields the drawer uses."""
        _grant_ml_ops_ver(db, rol_admin)
        order_id = 81100
        _seed_order(db, order_id, date_created=datetime(2026, 9, 1, tzinfo=timezone.utc))
        _payment(db, 81100, order_id, status="approved", net_received_amount=Decimal("800.00"))
        _charge(db, 81100, "tax_withholding_sirtac-caba", "tax", Decimal("300.00"))
        db.commit()

        body = client.get("/api/ml-ventas-ops/sales", headers=admin_auth_headers).json()

        sale = _group_holding(body, order_id)
        assert sale["neto"] == pytest.approx(1100.00)
        assert sale["neto_depositado"] == pytest.approx(800.00)
        assert sale["retenciones_recuperables"] == pytest.approx(300.00)
        assert sale["orders"][0]["neto_depositado"] == pytest.approx(800.00)
        assert sale["orders"][0]["retenciones_recuperables"] == pytest.approx(300.00)

    def test_no_sirtac_reports_zero_retenciones_not_none(self, db, client, admin_auth_headers, rol_admin):
        _grant_ml_ops_ver(db, rol_admin)
        order_id = 81101
        _seed_order(db, order_id, date_created=datetime(2026, 9, 1, tzinfo=timezone.utc))
        _payment(db, 81101, order_id, status="approved", net_received_amount=Decimal("500.00"))
        db.commit()

        body = client.get("/api/ml-ventas-ops/sales", headers=admin_auth_headers).json()

        sale = _group_holding(body, order_id)
        assert sale["retenciones_recuperables"] == pytest.approx(0.0)
        assert sale["neto_depositado"] == pytest.approx(500.00)

    def test_listing_does_not_query_payments_per_row(self, db, client, admin_auth_headers, rol_admin, query_counter):
        """The whole point of the design: BATCHED, not N+1. Regardless of
        how many rows the page holds, `ml_payments_ops`/`ml_payment_charges`
        are each queried AT MOST THREE times -- once by
        `compute_neto_by_order_ids` (`neto`), once by `iva.descomponer_neto`
        (`neto_sin_iva`, feeding `total_gauss`, ml-ventas-modo-logistico
        PR5), and once more by `compute_neto_desglose_by_order_ids`
        (`neto_depositado`/`retenciones_recuperables`, ml-ventas-neto-iibb-
        varios PR1.T12). All three are bulk, page-wide calls -- never one
        query per row -- so the ceiling moved from 2 to 3, it did not
        become unbounded."""
        _grant_ml_ops_ver(db, rol_admin)
        when = datetime(2026, 9, 1, tzinfo=timezone.utc)
        for i in range(5):
            order_id = 81000 + i
            _seed_order(db, order_id, date_created=when)
            _payment(db, 81000 + i, order_id, status="approved", net_received_amount=Decimal("100.00"))
            _charge(db, 81000 + i, "meli_percentage_fee", "fee", Decimal("10.00"))
        db.commit()

        with query_counter() as counter:
            resp = client.get("/api/ml-ventas-ops/sales", headers=admin_auth_headers)
        assert resp.status_code == 200

        assert counter.matching("ml_payments_ops") <= 3
        assert counter.matching("ml_payment_charges") <= 3


class TestMixedCurrencyPack:
    def test_a_pack_across_two_currencies_reports_no_amount_at_all(self, db, client, admin_auth_headers, rol_admin):
        """Adding ARS to USD produces a number that means nothing. Dropping
        only the currency label would render exactly that number."""
        _grant_ml_ops_ver(db, rol_admin)
        when = datetime(2026, 9, 1, tzinfo=timezone.utc)
        _seed_order(db, 1101, pack_id=666, total_amount=100, date_created=when)
        _seed_order(db, 1102, pack_id=666, total_amount=50, date_created=when)
        db.query(MlOrdersOps).filter(MlOrdersOps.order_id == 1102).update({"currency_id": "USD"})
        db.commit()

        body = client.get("/api/ml-ventas-ops/sales", headers=admin_auth_headers).json()
        group = _group_holding(body, 1101)

        assert group["currency_id"] is None
        assert group["total_amount"] is None, "no fabricated 150"

    def test_a_mixed_currency_pack_reports_no_neto_either(self, db, client, admin_auth_headers, rol_admin):
        """The net cannot escape the rule the amount above obeys.

        A mixed pack rendering a null `total_amount` beside a numeric
        `neto` is worse than either alone: the row reads as MORE
        trustworthy than the honest null sitting next to it, and the
        number it shows is ARS added to USD.
        """
        _grant_ml_ops_ver(db, rol_admin)
        when = datetime(2026, 9, 1, tzinfo=timezone.utc)
        _seed_order(db, 1111, pack_id=777, total_amount=100, date_created=when)
        _seed_order(db, 1112, pack_id=777, total_amount=50, date_created=when)
        db.query(MlOrdersOps).filter(MlOrdersOps.order_id == 1112).update({"currency_id": "USD"})
        # Both orders DO have synced payments: without the currency gate
        # the group would happily sum them.
        _payment(db, 91111, 1111, status="approved", net_received_amount=Decimal("80"))
        _payment(db, 91112, 1112, status="approved", net_received_amount=Decimal("40"))
        db.commit()

        body = client.get("/api/ml-ventas-ops/sales", headers=admin_auth_headers).json()
        group = _group_holding(body, 1111)

        assert group["total_amount"] is None
        assert group["neto"] is None, "no fabricated 120 across two currencies"

    def test_a_mixed_currency_pack_reports_no_tooltip_amounts_either(self, db, client, admin_auth_headers, rol_admin):
        """The Neto cell's tooltip ("MP $X · SIRTAC $Y") must not add ARS to
        USD either. Under the same gate `neto` obeys, a pack showing a
        null Neto next to a summed tooltip would contradict itself."""
        _grant_ml_ops_ver(db, rol_admin)
        when = datetime(2026, 9, 1, tzinfo=timezone.utc)
        _seed_order(db, 1121, pack_id=888, total_amount=100, date_created=when)
        _seed_order(db, 1122, pack_id=888, total_amount=50, date_created=when)
        db.query(MlOrdersOps).filter(MlOrdersOps.order_id == 1122).update({"currency_id": "USD"})
        _payment(db, 91121, 1121, status="approved", net_received_amount=Decimal("80"))
        _payment(db, 91122, 1122, status="approved", net_received_amount=Decimal("40"))
        db.commit()

        body = client.get("/api/ml-ventas-ops/sales", headers=admin_auth_headers).json()
        group = _group_holding(body, 1121)

        assert group["neto_depositado"] is None, "no fabricated 120 across two currencies"
        assert group["retenciones_recuperables"] is None


class TestMultiMemberPackTooltipAmounts:
    def test_a_single_currency_pack_sums_its_members(self, db, client, admin_auth_headers, rol_admin):
        """Two ARS orders in one pack: the tooltip amounts are the members'
        sum, the same all-or-nothing rule `neto` follows."""
        _grant_ml_ops_ver(db, rol_admin)
        when = datetime(2026, 9, 1, tzinfo=timezone.utc)
        _seed_order(db, 1131, pack_id=999, total_amount=100, date_created=when)
        _seed_order(db, 1132, pack_id=999, total_amount=50, date_created=when)
        _payment(db, 91131, 1131, status="approved", net_received_amount=Decimal("80"))
        _payment(db, 91132, 1132, status="approved", net_received_amount=Decimal("40"))
        db.commit()

        body = client.get("/api/ml-ventas-ops/sales", headers=admin_auth_headers).json()
        group = _group_holding(body, 1131)

        assert group["neto_depositado"] == pytest.approx(120)
        assert group["retenciones_recuperables"] == pytest.approx(0)


class TestDateRangeFilter:
    """`date_from`/`date_to` replace the month picker. Both bounds are
    INCLUSIVE, because a user who types the same day twice means that day,
    not an empty set."""

    def _seed_three_days(self, db) -> None:
        _seed_order(db, 40, status="paid", date_created=datetime(2026, 8, 10, 12, tzinfo=timezone.utc))
        _seed_order(db, 41, status="paid", date_created=datetime(2026, 8, 11, 12, tzinfo=timezone.utc))
        _seed_order(db, 42, status="paid", date_created=datetime(2026, 8, 12, 12, tzinfo=timezone.utc))
        db.commit()

    def test_both_bounds_are_inclusive(self, db, client, admin_auth_headers, rol_admin):
        _grant_ml_ops_ver(db, rol_admin)
        self._seed_three_days(db)

        resp = client.get(
            "/api/ml-ventas-ops/sales",
            params={"date_from": "2026-08-10", "date_to": "2026-08-12"},
            headers=admin_auth_headers,
        )

        assert sorted(_order_ids(resp.json())) == [40, 41, 42]

    def test_the_same_day_twice_means_that_day(self, db, client, admin_auth_headers, rol_admin):
        """The obvious way to ask for one day. Treating `to` as exclusive
        would answer "no sales" for a day that had them."""
        _grant_ml_ops_ver(db, rol_admin)
        self._seed_three_days(db)

        resp = client.get(
            "/api/ml-ventas-ops/sales",
            params={"date_from": "2026-08-11", "date_to": "2026-08-11"},
            headers=admin_auth_headers,
        )

        assert _order_ids(resp.json()) == [41]

    def test_only_from_means_from_then_on(self, db, client, admin_auth_headers, rol_admin):
        _grant_ml_ops_ver(db, rol_admin)
        self._seed_three_days(db)

        resp = client.get("/api/ml-ventas-ops/sales", params={"date_from": "2026-08-12"}, headers=admin_auth_headers)

        assert _order_ids(resp.json()) == [42]

    def test_only_to_means_up_to_and_including(self, db, client, admin_auth_headers, rol_admin):
        _grant_ml_ops_ver(db, rol_admin)
        self._seed_three_days(db)

        resp = client.get("/api/ml-ventas-ops/sales", params={"date_to": "2026-08-10"}, headers=admin_auth_headers)

        assert _order_ids(resp.json()) == [40]

    def test_a_range_that_runs_backwards_is_422_not_an_empty_list(self, db, client, admin_auth_headers, rol_admin):
        """Silently answering "no sales" to an impossible range is how a
        typo reads as a bad business day."""
        _grant_ml_ops_ver(db, rol_admin)

        resp = client.get(
            "/api/ml-ventas-ops/sales",
            params={"date_from": "2026-08-12", "date_to": "2026-08-10"},
            headers=admin_auth_headers,
        )

        assert resp.status_code == 422

    def test_an_unparseable_bound_is_422(self, db, client, admin_auth_headers, rol_admin):
        _grant_ml_ops_ver(db, rol_admin)

        resp = client.get("/api/ml-ventas-ops/sales", params={"date_from": "ayer"}, headers=admin_auth_headers)

        assert resp.status_code == 422

    def test_the_range_wins_over_the_legacy_month(self, db, client, admin_auth_headers, rol_admin):
        """`sold_month` is kept so a bookmarked URL does not 422. ANDing
        the two could only ever return less than either asked for."""
        _grant_ml_ops_ver(db, rol_admin)
        self._seed_three_days(db)

        resp = client.get(
            "/api/ml-ventas-ops/sales",
            params={"sold_month": "2026-07", "date_from": "2026-08-11", "date_to": "2026-08-11"},
            headers=admin_auth_headers,
        )

        assert _order_ids(resp.json()) == [41]


class TestSortByLastUpdate:
    """The listing has two independent axes: WHEN the sale happened and
    WHEN ML last touched it. Filtering is always the first -- "the sales of
    this week" cannot start including old ones just because they moved --
    and sorting can be either."""

    def _seed_old_sale_touched_today(self, db) -> None:
        # 50 is the newer SALE; 51 is older but was UPDATED later.
        _seed_order(db, 50, status="paid", date_created=datetime(2026, 8, 20, tzinfo=timezone.utc))
        _seed_order(
            db,
            51,
            status="paid",
            date_created=datetime(2026, 8, 1, tzinfo=timezone.utc),
            ml_last_updated=datetime(2026, 8, 25, tzinfo=timezone.utc),
        )
        db.commit()

    def test_the_default_is_still_the_sale_date(self, db, client, admin_auth_headers, rol_admin):
        _grant_ml_ops_ver(db, rol_admin)
        self._seed_old_sale_touched_today(db)

        resp = client.get("/api/ml-ventas-ops/sales", headers=admin_auth_headers)

        assert _order_ids(resp.json()) == [50, 51]

    def test_sorting_by_update_puts_the_recently_touched_sale_first(self, db, client, admin_auth_headers, rol_admin):
        _grant_ml_ops_ver(db, rol_admin)
        self._seed_old_sale_touched_today(db)

        resp = client.get("/api/ml-ventas-ops/sales", params={"sort": "ml_last_updated"}, headers=admin_auth_headers)

        assert _order_ids(resp.json()) == [51, 50]

    def test_sorting_does_not_change_which_sales_are_returned(self, db, client, admin_auth_headers, rol_admin):
        """Sorting is not a filter. A `date_from` still means the sale
        date even when the order is by update."""
        _grant_ml_ops_ver(db, rol_admin)
        self._seed_old_sale_touched_today(db)

        resp = client.get(
            "/api/ml-ventas-ops/sales",
            params={"sort": "ml_last_updated", "date_from": "2026-08-15"},
            headers=admin_auth_headers,
        )

        assert _order_ids(resp.json()) == [50]

    def test_an_unknown_sort_is_422_not_a_silent_default(self, db, client, admin_auth_headers, rol_admin):
        """Falling back to the default would answer a question nobody
        asked, in an order the caller did not request."""
        _grant_ml_ops_ver(db, rol_admin)

        resp = client.get("/api/ml-ventas-ops/sales", params={"sort": "precio"}, headers=admin_auth_headers)

        assert resp.status_code == 422

    def test_the_last_update_reaches_the_response(self, db, client, admin_auth_headers, rol_admin):
        """The column the operator sorts by has to be visible, otherwise
        the order looks arbitrary."""
        _grant_ml_ops_ver(db, rol_admin)
        self._seed_old_sale_touched_today(db)

        body = client.get("/api/ml-ventas-ops/sales", headers=admin_auth_headers).json()

        group = _group_holding(body, 51)
        assert group["ml_last_updated"] is not None
        assert group["orders"][0]["ml_last_updated"] is not None


# The business-day boundary is NOT tested through the API here on purpose.
# These tests run on SQLite, which DROPS the offset of a tz-aware bound
# instead of converting it, so the comparison happens between a naive UTC
# column and a naive LOCAL bound and lands on the opposite answer from
# Postgres. A test written against that would have to be wrong in
# production to be green here. The boundary logic is pure, so it is pinned
# purely, in `tests/unit/test_ml_ventas_date_bounds.py`.


class TestTotalGaussInListing:
    """ml-ventas-modo-logistico PR5, design D2 -- `total_gauss` on the
    listing is ALWAYS recomputed for the page, never served from
    `MlOrdersOps.total_gauss` (that column is a sort/filter key only).
    """

    def _varios_baseline(self, db) -> None:
        """A 0% "varios" version covering every date -- these tests are not
        ABOUT `VariosDeduccion`; without a version configured it is a
        legitimate unknown that would make every `total_gauss` `None`."""
        from datetime import date as date_type

        from app.models.varios_venta_pct import VariosVentaPct

        db.add(VariosVentaPct(porcentaje=Decimal("0.00"), fecha_desde=date_type(2020, 1, 1), fecha_hasta=None))

    def _item_with_frozen_cost(self, db, order_id, item_id="MLA1", quantity=1, costo_unitario_ars=Decimal("10.00")):
        from app.models.ml_order_item_costo import MlOrderItemCosto
        from app.models.ml_orders_ops import MlOrderItemOps

        db.add(MlOrderItemOps(order_id=order_id, item_id=item_id, seller_sku="SKU-1", quantity=quantity))
        db.add(
            MlOrderItemCosto(
                order_id=order_id,
                item_id=item_id,
                costo_origen=costo_unitario_ars,
                moneda="ARS",
                costo_unitario_ars=costo_unitario_ars,
                iva_pct=Decimal("21.00"),
                precio_unitario=Decimal("121.00"),
                fuente="sku",
                producto_item_id=1,
            )
        )

    def test_stored_total_gauss_agrees_with_recomputed(self, db, client, admin_auth_headers, rol_admin):
        """Pins design D2: even when `MlOrdersOps.total_gauss` is stored
        with a STALE, WRONG value, the listing shows the freshly recomputed
        one, never the stored column."""
        _grant_ml_ops_ver(db, rol_admin)
        order_id = 90001
        when = datetime(2026, 9, 1, tzinfo=timezone.utc)
        _seed_order(db, order_id, date_created=when)
        _payment(db, order_id, order_id, status="approved", net_received_amount=Decimal("121.00"))
        self._item_with_frozen_cost(db, order_id, costo_unitario_ars=Decimal("10.00"))
        self._varios_baseline(db)
        # Deliberately wrong/stale stored value -- the display must NOT
        # agree with this number.
        db.query(MlOrdersOps).filter(MlOrdersOps.order_id == order_id).update(
            {"total_gauss": Decimal("999999.00"), "total_gauss_stale": True}
        )
        db.commit()

        body = client.get("/api/ml-ventas-ops/sales", headers=admin_auth_headers).json()

        sale = _group_holding(body, order_id)
        recomputed = sale["orders"][0]["total_gauss"]
        assert recomputed is not None
        assert recomputed != pytest.approx(999999.00)
        # neto_sin_iva(100.00) - costo(10.00) == 90.00
        assert recomputed == pytest.approx(90.00)

    def test_sort_by_total_gauss_actually_orders_and_puts_nulls_last(self, db, client, admin_auth_headers, rol_admin):
        """The previous version of this test seeded ONE order and asserted
        only `status_code == 200`. Its name promised an ordering; its body
        proved the query parameter is not rejected. With the materialised
        column having had no producer at all, that is precisely the test
        that let a dead feature pass for a live one -- every row NULL, the
        sort silently degrading into sort by id, and nothing failing.

        Three rows, two with values and one without, is the minimum that
        can tell an ordering from an accident.

        ventas-ml-rediseno PR7.T5/T6/T7 (design D2, D1 rationale): the sort
        key is the AUTHORITATIVE `ml_order_metrics` table now, never the
        legacy `MlOrdersOps.total_gauss` mirror -- seeded here via
        `_stored_metrics`, not the legacy column, so this test pins the new
        reader path rather than the deprecated one PR8 will retire."""
        _grant_ml_ops_ver(db, rol_admin)
        when = datetime(2026, 9, 1, tzinfo=timezone.utc)
        _seed_order(db, 90010, date_created=when)
        _seed_order(db, 90011, date_created=when)
        _seed_order(db, 90012, date_created=when)
        _stored_metrics(db, 90010, total_gauss=Decimal("100.00"))
        _stored_metrics(db, 90011, total_gauss=Decimal("900.00"))
        # A deliberately WRONG legacy value: must have no effect on the
        # sort, proving the join no longer reads `MlOrdersOps.total_gauss`.
        db.query(MlOrdersOps).filter_by(order_id=90012).update({"total_gauss": Decimal("999999.00")})
        # 90012 deliberately has NO `ml_order_metrics` row (pending).
        db.commit()

        resp = client.get(
            "/api/ml-ventas-ops/sales",
            params={"sort": "total_gauss"},
            headers=admin_auth_headers,
        )

        assert resp.status_code == 200
        returned = [g["orders"][0]["order_id"] for g in resp.json()["sales"]]
        assert returned[:2] == [90011, 90010], "highest Total Gauss first"
        assert returned[-1] == 90012, "the unknown one goes last, never first"

    def test_list_and_breakdown_total_gauss_agree(self, db, client, admin_auth_headers, rol_admin):
        _grant_ml_ops_ver(db, rol_admin)
        order_id = 90020
        when = datetime(2026, 9, 1, tzinfo=timezone.utc)
        _seed_order(db, order_id, date_created=when)
        _payment(db, order_id, order_id, status="approved", net_received_amount=Decimal("121.00"))
        self._item_with_frozen_cost(db, order_id, costo_unitario_ars=Decimal("10.00"))
        self._varios_baseline(db)
        db.commit()
        # ventas-ml-rediseno PR7.T7: the DETAIL endpoint now reads the
        # STORED row (design D2/D5), never a live recompute -- this test
        # compares it against the listing's still-live per-row value, so
        # the stored row must actually exist first.
        recompute_order_metrics(db, [order_id])
        db.commit()

        list_body = client.get("/api/ml-ventas-ops/sales", headers=admin_auth_headers).json()
        detail_body = client.get(f"/api/ml-ventas-ops/orders/{order_id}", headers=admin_auth_headers).json()

        list_total_gauss = _group_holding(list_body, order_id)["orders"][0]["total_gauss"]
        assert list_total_gauss == pytest.approx(detail_body["total_gauss"])


class TestDetailIvaDecompositionAndDeductionChain(TestTotalGaussInListing):
    """ml-ventas-modo-logistico PR6 -- the detail endpoint now also
    exposes `iva_decomposicion` (PR4's split) and `cadena_total_gauss`
    (PR5's chain), both already computed to produce `total_gauss`. These
    pin the HISTORICAL/absent case first (no synced payments, the actual
    shape of every pre-PR3 sale), then the fully-costed happy path.
    """

    def test_order_without_synced_payments_names_the_reason_never_zero(self, db, client, admin_auth_headers, rol_admin):
        """No `MlPaymentOps` row at all -- the common historical shape.
        `neto_sin_iva`/`total_gauss` must be `None` with a named reason,
        never a fabricated `0`."""
        _grant_ml_ops_ver(db, rol_admin)
        order_id = 90030
        _seed_order(db, order_id, date_created=datetime(2026, 9, 1, tzinfo=timezone.utc))
        db.commit()

        body = client.get(f"/api/ml-ventas-ops/orders/{order_id}", headers=admin_auth_headers).json()

        assert body["total_gauss"] is None
        assert body["iva_decomposicion"]["neto_sin_iva"] is None
        assert body["iva_decomposicion"]["reconcilia"] is False
        assert body["iva_decomposicion"]["diferencia"] is None
        assert "sin_pagos_sincronizados" in body["iva_decomposicion"]["razones"]
        assert body["cadena_total_gauss"]["total_gauss"] is None

    def test_order_without_frozen_cost_blocks_chain_at_that_link_not_zero(
        self, db, client, admin_auth_headers, rol_admin
    ):
        """Payments synced (so `neto_sin_iva` reconciles) but no frozen
        cost row -- the chain must stop AT the cost link with `monto=None`
        for that code, never silently skip it or report a zero cost."""
        from app.models.ml_orders_ops import MlOrderItemOps

        _grant_ml_ops_ver(db, rol_admin)
        order_id = 90031
        _seed_order(db, order_id, date_created=datetime(2026, 9, 1, tzinfo=timezone.utc))
        _payment(db, order_id, order_id, status="approved", net_received_amount=Decimal("121.00"))
        # The item row exists (so it is expected to carry a frozen cost)
        # but has none -- the design's own "counts, not all-or-nothing"
        # case: `items_esperados` is 1, `costos_by_order` is empty.
        db.add(MlOrderItemOps(order_id=order_id, item_id="MLA1", seller_sku="SKU-1", quantity=1))
        self._varios_baseline(db)
        db.commit()
        # ventas-ml-rediseno PR7.T7: `cadena_total_gauss` now reads the
        # STORED chain (ml_order_metrics + ml_venta_deducciones), so it
        # must actually be produced once via the real producer first --
        # `recompute_order_metrics` applies the SAME formula the endpoint
        # used to call live, so the assertions below are unchanged.
        recompute_order_metrics(db, [order_id])
        db.commit()

        body = client.get(f"/api/ml-ventas-ops/orders/{order_id}", headers=admin_auth_headers).json()

        assert "item_sin_costo_congelado" in body["iva_decomposicion"]["razones"]
        assert body["cadena_total_gauss"]["total_gauss"] is None
        lineas = body["cadena_total_gauss"]["lineas"]
        blocked = [linea for linea in lineas if linea["monto"] is None]
        assert blocked, "at least one deduction link must carry the unresolved monto=None"
        # `markup = total_gauss / costo_mercaderia`: an unresolved
        # total_gauss must make markup unknown too, never a fabricated
        # number or a zero.
        assert body["cadena_total_gauss"]["markup"] is None

    def test_fully_costed_order_exposes_componentes_and_full_chain(self, db, client, admin_auth_headers, rol_admin):
        """Happy path: payments synced AND frozen cost present -- every
        component reconciles and the chain resolves end to end."""
        _grant_ml_ops_ver(db, rol_admin)
        order_id = 90032
        _seed_order(db, order_id, date_created=datetime(2026, 9, 1, tzinfo=timezone.utc))
        _payment(db, order_id, order_id, status="approved", net_received_amount=Decimal("121.00"))
        self._item_with_frozen_cost(db, order_id, costo_unitario_ars=Decimal("10.00"))
        self._varios_baseline(db)
        db.commit()
        # ventas-ml-rediseno PR7.T7: same reason as the sibling test above
        # -- the chain is now read from the stored row.
        recompute_order_metrics(db, [order_id])
        db.commit()

        body = client.get(f"/api/ml-ventas-ops/orders/{order_id}", headers=admin_auth_headers).json()

        assert body["iva_decomposicion"]["reconcilia"] is True
        assert body["iva_decomposicion"]["neto_sin_iva"] == pytest.approx(100.00)
        assert body["iva_decomposicion"]["componentes"], "components must be populated on the happy path"
        assert body["iva_decomposicion"]["razones"] == []
        assert body["cadena_total_gauss"]["total_gauss"] is not None
        assert body["cadena_total_gauss"]["lineas"]
        assert all(linea["monto"] is not None for linea in body["cadena_total_gauss"]["lineas"])
        # neto_sin_iva 100.00, costo_mercaderia 10.00 (1 x 10.00), varios 0%
        # -> total_gauss 90.00 -> markup 90.00 / 10.00 * 100 = 900.00%.
        assert body["cadena_total_gauss"]["markup"] == pytest.approx(900.00)


class TestDetailReadsStoredMetrics(TestTotalGaussInListing):
    """ventas-ml-rediseno PR7.T1/T3/T3a (design D9/D13, spec SM R5/R6/R9,
    BREAKDOWN R33): `GET /orders/{id}` sources `total_gauss` and
    `cadena_total_gauss` from `ml_order_metrics`, never a live
    `calcular_total_gauss` call, and exposes `metrics_state` so the panel
    knows when it cannot trust the invariant.
    """

    def test_detail_never_recomputes_live_even_when_stored_disagrees(self, db, client, admin_auth_headers, rol_admin):
        """A fully-costed order whose LIVE recompute would answer 90.00,
        but whose STORED row deliberately carries a different number --
        the response must show the STORED one (SM R5: 'none of them
        recompute Total Gauss/neto/markup live')."""
        _grant_ml_ops_ver(db, rol_admin)
        order_id = 90040
        _seed_order(db, order_id, date_created=datetime(2026, 9, 1, tzinfo=timezone.utc))
        _payment(db, order_id, order_id, status="approved", net_received_amount=Decimal("121.00"))
        self._item_with_frozen_cost(db, order_id, costo_unitario_ars=Decimal("10.00"))
        self._varios_baseline(db)
        _stored_metrics(
            db, order_id, total_gauss=Decimal("42.00"), markup_pct=Decimal("420.00"), costo_mercaderia=Decimal("10.00")
        )
        db.commit()

        body = client.get(f"/api/ml-ventas-ops/orders/{order_id}", headers=admin_auth_headers).json()

        assert body["total_gauss"] == pytest.approx(42.00)
        assert body["total_gauss"] != pytest.approx(90.00), "must never be the live-recomputed value"
        assert body["metrics_state"] == "ok"

    def test_invariant_chain_final_equals_stored_when_not_recalculating(
        self, db, client, admin_auth_headers, rol_admin
    ):
        """BREAKDOWN R33 / SM R6, R9(scenario): when the order is not
        `recalculating`, the chain's rendered final total MUST equal the
        stored `total_gauss` exactly -- an invariant, not approximate."""
        _grant_ml_ops_ver(db, rol_admin)
        order_id = 90041
        _seed_order(db, order_id, date_created=datetime(2026, 9, 1, tzinfo=timezone.utc))
        _payment(db, order_id, order_id, status="approved", net_received_amount=Decimal("121.00"))
        self._item_with_frozen_cost(db, order_id, costo_unitario_ars=Decimal("10.00"))
        self._varios_baseline(db)
        db.commit()
        recompute_order_metrics(db, [order_id])
        db.commit()

        body = client.get(f"/api/ml-ventas-ops/orders/{order_id}", headers=admin_auth_headers).json()

        assert body["metrics_state"] != "recalculating"
        assert body["cadena_total_gauss"]["total_gauss"] == pytest.approx(body["total_gauss"])

    def test_dirty_order_signals_recalculating_and_does_not_assert_invariant(
        self, db, client, admin_auth_headers, rol_admin
    ):
        """A dirty (mid-flight) order: the response signals `recalculating`
        explicitly, and the stored value it still carries (from a PRIOR
        recompute) may legitimately disagree with what a fresh recompute
        would produce -- SM R6 second half: no invariant is claimed while
        recalculating."""
        _grant_ml_ops_ver(db, rol_admin)
        order_id = 90042
        _seed_order(db, order_id, date_created=datetime(2026, 9, 1, tzinfo=timezone.utc))
        # A stale stored value from before the pending input write below.
        _stored_metrics(db, order_id, total_gauss=Decimal("999.00"))
        db.add(MlOrderMetricsDirty(order_id=order_id, reason="test"))
        db.commit()

        body = client.get(f"/api/ml-ventas-ops/orders/{order_id}", headers=admin_auth_headers).json()

        assert body["metrics_state"] == "recalculating"

    def test_parked_order_is_failed_not_recalculating_forever(self, db, client, admin_auth_headers, rol_admin):
        """SM R9(scenario)/design D9: a parked order (attempts >=
        POISON_THRESHOLD) is never shown as `recalculating` -- nothing will
        retry it automatically."""
        _grant_ml_ops_ver(db, rol_admin)
        order_id = 90043
        _seed_order(db, order_id, date_created=datetime(2026, 9, 1, tzinfo=timezone.utc))
        db.add(MlOrderMetricsDirty(order_id=order_id, reason="test", attempts=POISON_THRESHOLD))
        db.commit()

        body = client.get(f"/api/ml-ventas-ops/orders/{order_id}", headers=admin_auth_headers).json()

        assert body["metrics_state"] == "failed"

    def test_order_with_no_stored_row_is_pending_never_a_fabricated_number(
        self, db, client, admin_auth_headers, rol_admin
    ):
        _grant_ml_ops_ver(db, rol_admin)
        order_id = 90044
        _seed_order(db, order_id, date_created=datetime(2026, 9, 1, tzinfo=timezone.utc))
        db.commit()

        body = client.get(f"/api/ml-ventas-ops/orders/{order_id}", headers=admin_auth_headers).json()

        assert body["metrics_state"] == "pending"
        assert body["cadena_total_gauss"]["total_gauss"] is None


class TestSearch:
    """`GET /sales?q=...` (spec `ml-sales-search` R25, R25a, R26, R27;
    PR9.T3-T6). Router-level confirmation that `q` is wired through
    `build_scope`/`apply_search` end to end -- unit coverage of
    `apply_search` itself lives in
    `tests/services/ml_sales_query/test_search.py`.
    """

    def test_search_by_order_id_returns_only_that_order(self, db, client, admin_auth_headers, rol_admin):
        _grant_ml_ops_ver(db, rol_admin)
        _seed_order(db, 95001, date_created=datetime(2026, 9, 1, tzinfo=timezone.utc))
        _seed_order(db, 95002, date_created=datetime(2026, 9, 1, tzinfo=timezone.utc))
        db.commit()

        body = client.get("/api/ml-ventas-ops/sales", params={"q": "95001"}, headers=admin_auth_headers).json()

        assert _order_ids(body) == [95001]

    def test_search_by_order_id_returns_its_pack_siblings_too(self, db, client, admin_auth_headers, rol_admin):
        _grant_ml_ops_ver(db, rol_admin)
        _seed_order(db, 95010, pack_id=95000, date_created=datetime(2026, 9, 1, tzinfo=timezone.utc))
        _seed_order(db, 95011, pack_id=95000, date_created=datetime(2026, 9, 1, tzinfo=timezone.utc))
        db.commit()

        body = client.get("/api/ml-ventas-ops/sales", params={"q": "95010"}, headers=admin_auth_headers).json()

        assert sorted(_order_ids(body)) == [95010, 95011]

    def test_search_by_buyer_nickname(self, db, client, admin_auth_headers, rol_admin):
        _grant_ml_ops_ver(db, rol_admin)
        _seed_order(
            db,
            95020,
            date_created=datetime(2026, 9, 1, tzinfo=timezone.utc),
        )
        db.query(MlOrdersOps).filter_by(order_id=95020).update({"buyer_nickname": "COMPRADOR_UNO"})
        _seed_order(db, 95021, date_created=datetime(2026, 9, 1, tzinfo=timezone.utc))
        db.query(MlOrdersOps).filter_by(order_id=95021).update({"buyer_nickname": "OTRO"})
        db.commit()

        body = client.get("/api/ml-ventas-ops/sales", params={"q": "comprador_uno"}, headers=admin_auth_headers).json()

        assert _order_ids(body) == [95020]

    def test_search_by_partial_item_title(self, db, client, admin_auth_headers, rol_admin):
        """SEARCH R25a: matches the sale's OWN `ml_order_items_ops.title`,
        never through `producto_item_id` -- no `ml_order_item_costos` row
        is seeded for this order at all, and it is still found."""
        from app.models.ml_orders_ops import MlOrderItemOps

        _grant_ml_ops_ver(db, rol_admin)
        _seed_order(db, 95030, date_created=datetime(2026, 9, 1, tzinfo=timezone.utc))
        db.add(MlOrderItemOps(order_id=95030, item_id="MLA9999", title="Zapatilla deportiva talle 42", quantity=1))
        _seed_order(db, 95031, date_created=datetime(2026, 9, 1, tzinfo=timezone.utc))
        db.commit()

        body = client.get("/api/ml-ventas-ops/sales", params={"q": "deportiva"}, headers=admin_auth_headers).json()

        assert _order_ids(body) == [95030]

    def test_search_by_seller_sku(self, db, client, admin_auth_headers, rol_admin):
        from app.models.ml_orders_ops import MlOrderItemOps

        _grant_ml_ops_ver(db, rol_admin)
        _seed_order(db, 95040, date_created=datetime(2026, 9, 1, tzinfo=timezone.utc))
        db.add(MlOrderItemOps(order_id=95040, item_id="MLA1", seller_sku="SKU-ABC-77", quantity=1))
        db.commit()

        body = client.get("/api/ml-ventas-ops/sales", params={"q": "ABC-77"}, headers=admin_auth_headers).json()

        assert _order_ids(body) == [95040]

    def test_search_by_mla_item_id(self, db, client, admin_auth_headers, rol_admin):
        from app.models.ml_orders_ops import MlOrderItemOps

        _grant_ml_ops_ver(db, rol_admin)
        _seed_order(db, 95050, date_created=datetime(2026, 9, 1, tzinfo=timezone.utc))
        db.add(MlOrderItemOps(order_id=95050, item_id="MLA555666", quantity=1))
        _seed_order(db, 95051, date_created=datetime(2026, 9, 1, tzinfo=timezone.utc))
        db.commit()

        body = client.get("/api/ml-ventas-ops/sales", params={"q": "MLA555666"}, headers=admin_auth_headers).json()

        assert _order_ids(body) == [95050]

    def test_no_match_returns_an_explicit_empty_result_not_an_error(self, db, client, admin_auth_headers, rol_admin):
        _grant_ml_ops_ver(db, rol_admin)
        _seed_order(db, 95060, date_created=datetime(2026, 9, 1, tzinfo=timezone.utc))
        db.commit()

        resp = client.get("/api/ml-ventas-ops/sales", params={"q": "no_coincide_con_nada"}, headers=admin_auth_headers)

        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 0
        assert body["sales"] == []

    def test_search_intersects_with_active_toggle_filter_not_replaces_it(
        self, db, client, admin_auth_headers, rol_admin
    ):
        """SEARCH R26: a search term matching orders EXCLUDED by an active
        filter never appears -- intersection, not replacement."""
        _grant_ml_ops_ver(db, rol_admin)
        _seed_order(db, 95070, status="cancelled", date_created=datetime(2026, 9, 1, tzinfo=timezone.utc))
        db.query(MlOrdersOps).filter_by(order_id=95070).update({"buyer_nickname": "mismo_comprador"})
        _seed_order(db, 95071, status="paid", date_created=datetime(2026, 9, 1, tzinfo=timezone.utc))
        db.query(MlOrdersOps).filter_by(order_id=95071).update({"buyer_nickname": "mismo_comprador"})
        db.commit()

        body = client.get(
            "/api/ml-ventas-ops/sales",
            params={"q": "mismo_comprador", "operation_status": "cancelled"},
            headers=admin_auth_headers,
        ).json()

        assert _order_ids(body) == [95070]


class TestFacetCountsObeyTheSearch:
    """SEARCH R26: the chips count the rows the table actually renders. A
    chip reporting the whole period while the table shows one row
    contradicts the table under it."""

    def test_facet_totals_match_the_listing_total_when_searching(
        self, db, client, admin_auth_headers, rol_admin
    ) -> None:
        _grant_ml_ops_ver(db, rol_admin)
        when = datetime(2026, 9, 1, tzinfo=timezone.utc)
        _seed_order(db, 6001, total_amount=100, date_created=when)
        _seed_order(db, 6002, total_amount=100, date_created=when)
        _seed_order(db, 6003, total_amount=100, date_created=when)
        db.commit()

        body = client.get("/api/ml-ventas-ops/sales?q=6001", headers=admin_auth_headers).json()

        assert body["total"] == 1
        assert body["facets"]["operation_status_total"] == 1
        assert body["facets"]["goods_status_total"] == 1
        assert sum(body["facets"]["operation_status"].values()) == 1


class TestSearchStaysInsideTheScope:
    """SEARCH R25/R26 (PR9.T3): the search narrows what the scope already
    allows. It can never reach a sale of ANOTHER seller, nor one outside
    the requested date range."""

    def test_a_match_outside_the_date_range_is_not_returned(self, db, client, admin_auth_headers, rol_admin) -> None:
        _grant_ml_ops_ver(db, rol_admin)
        _seed_order(db, 6101, date_created=datetime(2026, 9, 10, tzinfo=timezone.utc))
        _seed_order(db, 6102, date_created=datetime(2026, 8, 10, tzinfo=timezone.utc))
        db.commit()

        dentro = client.get(
            "/api/ml-ventas-ops/sales?date_from=2026-09-01&date_to=2026-09-30&q=6101",
            headers=admin_auth_headers,
        ).json()
        fuera = client.get(
            "/api/ml-ventas-ops/sales?date_from=2026-09-01&date_to=2026-09-30&q=6102",
            headers=admin_auth_headers,
        ).json()

        assert {o["order_id"] for g in dentro["sales"] for o in g["orders"]} == {6101}
        assert fuera["total"] == 0, "la búsqueda no puede traer una venta fuera del rango"
        assert fuera["sales"] == []

    def test_a_match_of_another_seller_is_not_returned(self, db, client, admin_auth_headers, rol_admin) -> None:
        _grant_ml_ops_ver(db, rol_admin)
        when = datetime(2026, 9, 10, tzinfo=timezone.utc)
        _seed_order(db, 6103, date_created=when)
        _seed_order(db, 6104, date_created=when)
        db.query(MlOrdersOps).filter(MlOrdersOps.order_id == 6104).update({"seller_id": 12345})
        db.commit()

        propia = client.get("/api/ml-ventas-ops/sales?q=6103", headers=admin_auth_headers).json()
        ajena = client.get("/api/ml-ventas-ops/sales?q=6104", headers=admin_auth_headers).json()

        assert {o["order_id"] for g in propia["sales"] for o in g["orders"]} == {6103}
        assert ajena["total"] == 0, "la búsqueda no puede cruzar de vendedor"
        assert ajena["sales"] == []


class TestProductFacets:
    """`GET /sales?marcas=...&subcategorias=...&pms=...` (spec
    `ml-sales-product-filters` PFILT R35-R43, PR9.T16a/T17). Router-level
    wiring confirmation -- unit coverage of the facet EXISTS/conjunction
    logic itself lives in
    `tests/services/ml_sales_query/test_filters_product_facets.py`.
    """

    def _seed_product(self, db, item_id: int, *, marca: str, categoria: str, subcategoria_id: int) -> None:
        from app.models.producto import ProductoERP

        db.add(
            ProductoERP(
                item_id=item_id,
                codigo=f"COD{item_id}",
                descripcion=f"Producto {item_id}",
                marca=marca,
                categoria=categoria,
                subcategoria_id=subcategoria_id,
            )
        )

    def _seed_costo(self, db, order_id: int, item_id: str, producto_item_id: int) -> None:
        from app.models.ml_order_item_costo import MlOrderItemCosto

        db.add(
            MlOrderItemCosto(
                order_id=order_id,
                item_id=item_id,
                variation_id=None,
                costo_origen=100,
                moneda="ARS",
                costo_unitario_ars=100,
                iva_pct=21,
                precio_unitario=150,
                fuente="test",
                producto_item_id=producto_item_id,
            )
        )

    def test_marcas_param_filters_the_listing(self, db, client, admin_auth_headers, rol_admin):
        _grant_ml_ops_ver(db, rol_admin)
        _seed_order(db, 96001, date_created=datetime(2026, 9, 1, tzinfo=timezone.utc))
        _seed_order(db, 96002, date_created=datetime(2026, 9, 1, tzinfo=timezone.utc))
        self._seed_product(db, 96100, marca="Epson", categoria="Impresoras", subcategoria_id=1)
        self._seed_product(db, 96200, marca="Lexmark", categoria="Impresoras", subcategoria_id=1)
        self._seed_costo(db, 96001, "MLA96001", 96100)
        self._seed_costo(db, 96002, "MLA96002", 96200)
        db.commit()

        body = client.get("/api/ml-ventas-ops/sales", params={"marcas": "epson"}, headers=admin_auth_headers).json()

        assert _order_ids(body) == [96001]

    def test_facet_counts_obey_the_product_filter(self, db, client, admin_auth_headers, rol_admin):
        """PFILT + SEARCH R26: the chips count the rows the table renders.
        A chip reporting the whole period while `marcas` shows one row
        contradicts the table under it -- same defect R26 already fixed
        for the free-text search."""
        _grant_ml_ops_ver(db, rol_admin)
        _seed_order(db, 96031, date_created=datetime(2026, 9, 1, tzinfo=timezone.utc))
        _seed_order(db, 96032, date_created=datetime(2026, 9, 1, tzinfo=timezone.utc))
        self._seed_product(db, 96131, marca="Epson", categoria="Impresoras", subcategoria_id=1)
        self._seed_product(db, 96231, marca="Lexmark", categoria="Impresoras", subcategoria_id=1)
        self._seed_costo(db, 96031, "MLA96031", 96131)
        self._seed_costo(db, 96032, "MLA96032", 96231)
        db.commit()

        body = client.get("/api/ml-ventas-ops/sales", params={"marcas": "epson"}, headers=admin_auth_headers).json()

        assert body["total"] == 1
        assert body["facets"]["operation_status_total"] == 1
        assert body["facets"]["goods_status_total"] == 1
        assert sum(body["facets"]["operation_status"].values()) == 1

    def test_subcategorias_and_marcas_combine_as_conjunction(self, db, client, admin_auth_headers, rol_admin):
        _grant_ml_ops_ver(db, rol_admin)
        _seed_order(db, 96010, pack_id=96500, date_created=datetime(2026, 9, 1, tzinfo=timezone.utc))
        _seed_order(db, 96011, pack_id=96500, date_created=datetime(2026, 9, 1, tzinfo=timezone.utc))
        # Different items, each satisfies ONE facet -- must NOT match (R38).
        self._seed_product(db, 96110, marca="Epson", categoria="Consumibles", subcategoria_id=2)
        self._seed_product(db, 96210, marca="Lexmark", categoria="Impresoras", subcategoria_id=1)
        self._seed_costo(db, 96010, "MLA96010", 96110)
        self._seed_costo(db, 96011, "MLA96011", 96210)
        db.commit()

        body = client.get(
            "/api/ml-ventas-ops/sales",
            params={"marcas": "epson", "subcategorias": "1"},
            headers=admin_auth_headers,
        ).json()

        assert _order_ids(body) == []

    def test_a_pm_with_no_assigned_pairs_returns_empty_not_every_sale(self, db, client, admin_auth_headers, rol_admin):
        _grant_ml_ops_ver(db, rol_admin)
        _seed_order(db, 96020, date_created=datetime(2026, 9, 1, tzinfo=timezone.utc))
        self._seed_product(db, 96120, marca="Epson", categoria="Impresoras", subcategoria_id=1)
        self._seed_costo(db, 96020, "MLA96020", 96120)
        db.commit()

        body = client.get("/api/ml-ventas-ops/sales", params={"pms": "99999999"}, headers=admin_auth_headers).json()

        assert _order_ids(body) == []

    def test_non_numeric_subcategoria_id_is_422(self, db, client, admin_auth_headers, rol_admin):
        _grant_ml_ops_ver(db, rol_admin)
        db.commit()

        resp = client.get("/api/ml-ventas-ops/sales", params={"subcategorias": "abc"}, headers=admin_auth_headers)

        assert resp.status_code == 422

    def test_empty_csv_entry_is_422(self, db, client, admin_auth_headers, rol_admin):
        _grant_ml_ops_ver(db, rol_admin)
        db.commit()

        resp = client.get("/api/ml-ventas-ops/sales", params={"marcas": "epson,,lexmark"}, headers=admin_auth_headers)

        assert resp.status_code == 422

    def test_a_brand_or_id_matching_no_product_is_an_empty_result_not_an_error(
        self, db, client, admin_auth_headers, rol_admin
    ):
        _grant_ml_ops_ver(db, rol_admin)
        _seed_order(db, 96030, date_created=datetime(2026, 9, 1, tzinfo=timezone.utc))
        db.commit()

        resp = client.get(
            "/api/ml-ventas-ops/sales", params={"marcas": "marca_inexistente"}, headers=admin_auth_headers
        )

        assert resp.status_code == 200
        assert _order_ids(resp.json()) == []

    def test_no_publication_status_or_official_store_param_exists(self, db, client, admin_auth_headers, rol_admin):
        """PFILT R37/R36a + R40 (T15): none of these params exist on the
        endpoint at all -- FastAPI drops any unknown query param, so the
        SAME request with or without one returns identical rows, proving
        nothing in today's catalog state silently filters a sale."""
        _grant_ml_ops_ver(db, rol_admin)
        _seed_order(db, 96040, date_created=datetime(2026, 9, 1, tzinfo=timezone.utc))
        db.commit()

        without_param = client.get("/api/ml-ventas-ops/sales", headers=admin_auth_headers).json()
        with_unknown_params = client.get(
            "/api/ml-ventas-ops/sales",
            params={
                "estado_mla": "activa",
                "tienda_oficial": "true",
                "con_stock": "true",
                "con_precio": "true",
                "web_transferencia": "true",
                "colores": "rojo",
                "con_mla": "true",
                "nuevos_ultimos_7_dias": "true",
                "auditoria": "true",
            },
            headers=admin_auth_headers,
        ).json()

        assert _order_ids(without_param) == _order_ids(with_unknown_params) == [96040]


class TestProductFacetValueLimits:
    """PFILT R35/T16a: an out-of-range or duplicated facet value must read
    as 422 or as a de-duplicated filter, never as a 500 from the driver."""

    def test_an_out_of_range_id_is_422_not_a_500(self, db, client, admin_auth_headers, rol_admin):
        _grant_ml_ops_ver(db, rol_admin)
        db.commit()

        resp = client.get("/api/ml-ventas-ops/sales?subcategorias=99999999999999999999", headers=admin_auth_headers)

        assert resp.status_code == 422

    def test_duplicated_values_are_deduplicated(self, db, client, admin_auth_headers, rol_admin):
        """Seeded on purpose: comparing two empty results would pass even
        with the de-duplication broken."""
        _grant_ml_ops_ver(db, rol_admin)
        _seed_order(db, 96040, date_created=datetime(2026, 9, 1, tzinfo=timezone.utc))
        TestProductFacets()._seed_product(db, 96140, marca="Epson", categoria="Impresoras", subcategoria_id=1)
        TestProductFacets()._seed_costo(db, 96040, "MLA96040", 96140)
        db.commit()

        una = client.get("/api/ml-ventas-ops/sales?subcategorias=1", headers=admin_auth_headers)
        repetida = client.get("/api/ml-ventas-ops/sales?subcategorias=1,1,1", headers=admin_auth_headers)

        assert una.status_code == repetida.status_code == 200
        assert _order_ids(una.json()) == [96040], "el filtro tiene que traer la venta sembrada"
        assert _order_ids(repetida.json()) == _order_ids(una.json())

    def test_duplicated_brand_names_differ_only_in_case(self, db, client, admin_auth_headers, rol_admin):
        _grant_ml_ops_ver(db, rol_admin)
        _seed_order(db, 96041, date_created=datetime(2026, 9, 1, tzinfo=timezone.utc))
        TestProductFacets()._seed_product(db, 96141, marca="Epson", categoria="Impresoras", subcategoria_id=1)
        TestProductFacets()._seed_costo(db, 96041, "MLA96041", 96141)
        db.commit()

        una = client.get("/api/ml-ventas-ops/sales?marcas=Epson", headers=admin_auth_headers)
        repetida = client.get("/api/ml-ventas-ops/sales?marcas=Epson,EPSON,epson", headers=admin_auth_headers)

        assert una.status_code == repetida.status_code == 200
        assert _order_ids(una.json()) == [96041], "el filtro tiene que traer la venta sembrada"
        assert _order_ids(repetida.json()) == _order_ids(una.json())
