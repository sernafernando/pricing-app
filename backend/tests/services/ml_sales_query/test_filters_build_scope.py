"""Tests for `app.services.ml_sales_query.filters.build_scope` (PR9.T1).

`build_scope` is a PURE REFACTOR of the query-building logic that used to
live inline in `ml_ventas_ops.py::listar_ventas` (the status derivation,
the group key expression and the group-level collapse rule). These tests
pin its behavior directly against seeded data, independently of the
router.

They pin expected values; they do NOT run the old inline code side by
side, because this same change deletes it. The before/after proof is the
untouched `tests/integration/test_ml_ventas_ops_sales_router.py` suite
staying green after the router was switched to delegate here -- that suite
also covers the status branches this file does not (`in_mediation`,
`cancelled_ml_covered`, a settled claim).

Covers: date range scoping, operation/goods status derivation, pack
grouping (`group_key`), and pagination-shaped ordering (`date_created`
DESC, `order_id` DESC tiebreak).
"""

from __future__ import annotations

from sqlalchemy import func

from datetime import datetime, timezone

import pytest

from app.core.config import settings
from app.models.ml_orders_ops import MlOperationLink, MlOrdersOps, MlShipmentOps
from app.models.rma_claim_ml import RmaClaimML
from app.services.ml_orders_ingestion.link_resolver_service import resolve_links
from app.services.ml_sales_query.filters import SalesFilter, build_scope


@pytest.fixture(autouse=True)
def _seller(monkeypatch):
    monkeypatch.setattr(settings, "ML_USER_ID", 999)
    # `ML_ORDERS_OPS_ENABLED` defaults to False (config.py): `resolve_links`
    # returns `ran=False` without it, so the claim never gets linked and the
    # status reads `paid`. A local `.env` can have it on, which is exactly
    # how this passed here and failed in CI.
    monkeypatch.setattr(settings, "ML_ORDERS_OPS_ENABLED", True)


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
        total_amount=100,
        paid_amount=100,
        currency_id="ARS",
        shipping_id=shipping_id,
    )
    db.add(order)
    if shipping_id is not None and shipping_status is not None:
        db.add(MlShipmentOps(shipment_id=shipping_id, order_id=order_id, status=shipping_status))
    if claim_status is not None:
        db.add(RmaClaimML(claim_id=order_id * 100, resource_id=order_id, status=claim_status))
    db.flush()


def _rows(db, scope):
    """Order-level rows the query returns, oldest-write-order preserved for
    assertions (the router itself re-sorts by group; these tests assert on
    the raw scoped rowset the old inline `base`/`listing_query` produced)."""
    return scope.listing_query.with_entities(
        MlOrdersOps.order_id,
        scope.group_key.label("group_key"),
        scope.op_status_expr.label("operation_status"),
        scope.goods_status_expr.label("goods_status"),
    ).all()


class TestStatusDerivationParity:
    def test_cancelled_order_shows_as_cancelled(self, db):
        _seed_order(db, 1, status="cancelled", date_created=datetime(2026, 1, 1, tzinfo=timezone.utc))
        scope = build_scope(
            db,
            SalesFilter(
                include_unknown=True,
                include_in_dispute=True,
            ),
        )
        rows = {r.order_id: r for r in _rows(db, scope)}
        assert rows[1].operation_status == "cancelled"

    def test_delivered_order_with_no_claim_shows_as_delivered(self, db):
        _seed_order(
            db,
            2,
            status="paid",
            shipping_status="delivered",
            date_created=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )
        scope = build_scope(
            db,
            SalesFilter(
                include_unknown=True,
                include_in_dispute=True,
            ),
        )
        rows = {r.order_id: r for r in _rows(db, scope)}
        assert rows[2].operation_status == "delivered"

    def test_open_claim_forces_in_dispute(self, db):
        # Distinctive ids: this order/claim pair must not collide with one
        # another test in the same worker already linked (the link is keyed
        # on the claim's own id), or the claim would silently not be linked
        # and the status would read `paid`.
        order_id = 930003
        _seed_order(
            db,
            order_id,
            status="paid",
            claim_status="opened",
            date_created=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )
        resultado = resolve_links(db)
        db.commit()

        # Asserted, not assumed: this test read `paid` in CI while passing
        # locally, because `resolve_links` silently no-ops when
        # `ML_ORDERS_OPS_ENABLED` is off (the `_seller` fixture now pins it
        # on). Checking the link itself is what turned "expected in_dispute,
        # got paid" into a message naming the real cause.
        enlaces = (
            db.query(MlOperationLink)
            .filter(MlOperationLink.order_id == order_id, MlOperationLink.entity_type == "claim")
            .all()
        )
        assert resultado.claims_linked >= 1, f"el reclamo no se vinculó: {resultado}"
        assert enlaces, "no hay fila en ml_operation_links para el reclamo de esta orden"

        scope = build_scope(
            db,
            SalesFilter(
                include_unknown=True,
                include_in_dispute=True,
            ),
        )
        rows = {r.order_id: r for r in _rows(db, scope)}
        assert rows[order_id].operation_status == "in_dispute"

    def test_unrecognised_status_is_unknown(self, db):
        _seed_order(db, 4, status="weird_status", date_created=datetime(2026, 1, 1, tzinfo=timezone.utc))
        scope = build_scope(
            db,
            SalesFilter(
                include_unknown=True,
                include_in_dispute=True,
            ),
        )
        rows = {r.order_id: r for r in _rows(db, scope)}
        assert rows[4].operation_status == "unknown"


class TestDateRangeScoping:
    def test_date_range_excludes_orders_outside_the_window(self, db):
        _seed_order(db, 10, date_created=datetime(2026, 1, 5, tzinfo=timezone.utc))
        _seed_order(db, 11, date_created=datetime(2026, 2, 5, tzinfo=timezone.utc))
        scope = build_scope(
            db,
            SalesFilter(
                include_unknown=True,
                include_in_dispute=True,
                date_range=(
                    datetime(2026, 1, 1, tzinfo=timezone.utc),
                    datetime(2026, 2, 1, tzinfo=timezone.utc),
                ),
            ),
        )
        # Scoped to the ids this test seeds: another test's committed row
        # must not be able to turn this into a false failure.
        ids = {r.order_id for r in _rows(db, scope)} & {10, 11}
        assert ids == {10}


class TestOperationAndGoodsStatusFilters:
    def test_operation_status_filter_scopes_the_listing_query(self, db):
        _seed_order(db, 20, status="cancelled", date_created=datetime(2026, 1, 1, tzinfo=timezone.utc))
        _seed_order(db, 21, status="paid", date_created=datetime(2026, 1, 1, tzinfo=timezone.utc))
        scope = build_scope(
            db, SalesFilter(include_unknown=True, include_in_dispute=True, operation_status="cancelled")
        )
        ids = {r.order_id for r in _rows(db, scope)}
        assert ids == {20}

    def test_goods_status_filter_scopes_the_listing_query(self, db):
        _seed_order(db, 22, shipping_status="delivered", date_created=datetime(2026, 1, 1, tzinfo=timezone.utc))
        _seed_order(db, 23, date_created=datetime(2026, 1, 1, tzinfo=timezone.utc))
        scope = build_scope(db, SalesFilter(include_unknown=True, include_in_dispute=True, goods_status="delivered"))
        ids = {r.order_id for r in _rows(db, scope)}
        assert ids == {22}

    def test_base_is_unaffected_by_status_filters(self, db):
        """`scope.base` (used for members/facets, never for the status-
        filtered page) must NOT carry the status filter -- same contract as
        the old `base` vs `listing_query` split."""
        _seed_order(db, 24, status="cancelled", date_created=datetime(2026, 1, 1, tzinfo=timezone.utc))
        _seed_order(db, 25, status="paid", date_created=datetime(2026, 1, 1, tzinfo=timezone.utc))
        scope = build_scope(
            db, SalesFilter(include_unknown=True, include_in_dispute=True, operation_status="cancelled")
        )
        base_ids = {row.MlOrdersOps.order_id for row in scope.base.all()} & {24, 25}
        assert base_ids == {24, 25}


class TestPackGrouping:
    def test_pack_siblings_share_the_same_group_key(self, db):
        _seed_order(db, 30, pack_id=999, date_created=datetime(2026, 1, 1, tzinfo=timezone.utc))
        _seed_order(db, 31, pack_id=999, date_created=datetime(2026, 1, 1, tzinfo=timezone.utc))
        _seed_order(db, 32, date_created=datetime(2026, 1, 1, tzinfo=timezone.utc))
        scope = build_scope(
            db,
            SalesFilter(
                include_unknown=True,
                include_in_dispute=True,
            ),
        )
        rows = {r.order_id: r.group_key for r in _rows(db, scope)}
        assert rows[30] == rows[31] == "p:999"
        assert rows[32] == "o:32"

    def test_pack_id_equal_to_another_order_id_does_not_collide(self, db):
        _seed_order(db, 40, pack_id=41, date_created=datetime(2026, 1, 1, tzinfo=timezone.utc))
        _seed_order(db, 41, date_created=datetime(2026, 1, 1, tzinfo=timezone.utc))
        scope = build_scope(
            db,
            SalesFilter(
                include_unknown=True,
                include_in_dispute=True,
            ),
        )
        rows = {r.order_id: r.group_key for r in _rows(db, scope)}
        assert rows[40] == "p:41"
        assert rows[41] == "o:41"


class TestPaginationOrderingParity:
    def test_group_key_query_orders_by_date_then_order_id_desc(self, db):
        _seed_order(db, 50, date_created=datetime(2026, 1, 1, tzinfo=timezone.utc))
        _seed_order(db, 51, date_created=datetime(2026, 1, 1, tzinfo=timezone.utc))
        _seed_order(db, 52, date_created=datetime(2026, 1, 2, tzinfo=timezone.utc))
        scope = build_scope(
            db,
            SalesFilter(
                include_unknown=True,
                include_in_dispute=True,
            ),
        )

        key_rows = (
            scope.listing_query.with_entities(
                scope.group_key.label("group_key"),
                func.min(MlOrdersOps.date_created).label("group_date"),
            )
            .group_by("group_key")
            .order_by(func.min(MlOrdersOps.date_created).desc().nullslast(), func.max(MlOrdersOps.order_id).desc())
            .all()
        )
        assert [r.group_key for r in key_rows] == ["o:52", "o:51", "o:50"]
