"""ventas-ml-rediseno PR20.T7 — `recompute_group_metrics(db, group_keys)`.

Reads each group's CURRENT member order ids from `ml_orders_ops` (by
`pack_id`, never a cached member list -- a member can have changed pack
since the group was last computed), sums `total_gauss`/`costo_mercaderia`/
`neto`/`neto_sin_iva` all-or-nothing (reusing `aggregate_pack_metrics`'s
core), and derives `gauss_status` via `group_gauss_status`. A pack with a
recalculating/pending/missing member returns `gauss_status='unresolved'`
(no resolvable numeric value), NEVER a partial sum (SM R10, KPI R19).
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from app.models.ml_order_metrics import MlOrderMetrics, MlOrderMetricsDirty
from app.models.ml_orders_ops import MlOrdersOps
from app.services.ml_group_metrics.compute import recompute_group_metrics


def _order(db, order_id: int, pack_id=None, seller_id: int = 999) -> None:
    db.add(
        MlOrdersOps(
            order_id=order_id,
            pack_id=pack_id,
            status="paid",
            ml_last_updated=datetime(2026, 9, 20, tzinfo=timezone.utc),
            date_created=datetime(2026, 9, 15, tzinfo=timezone.utc),
            seller_id=seller_id,
        )
    )


def _stored(
    db,
    order_id: int,
    total_gauss=Decimal("50.00"),
    costo_mercaderia=Decimal("30.00"),
    neto=Decimal("100.00"),
    neto_sin_iva=Decimal("82.64"),
    gauss_status="ok",
) -> None:
    db.add(
        MlOrderMetrics(
            order_id=order_id,
            neto=neto,
            neto_sin_iva=neto_sin_iva,
            iva_reconcilia=True,
            costo_mercaderia=costo_mercaderia,
            total_gauss=total_gauss,
            markup_pct=Decimal("166.67") if total_gauss is not None else None,
            gauss_status=gauss_status,
            formula_version=2,
            computed_at=datetime.now(timezone.utc),
        )
    )


class TestRecomputeGroupMetricsPack:
    def test_two_resolved_members_sum_all_or_nothing(self, db):
        _order(db, 1, pack_id=555)
        _order(db, 2, pack_id=555)
        db.flush()
        _stored(db, 1, total_gauss=Decimal("50.00"), costo_mercaderia=Decimal("30.00"))
        _stored(db, 2, total_gauss=Decimal("20.00"), costo_mercaderia=Decimal("10.00"))
        db.commit()

        result = recompute_group_metrics(db, ["p:555"])

        group = result["p:555"]
        assert group.total_gauss == Decimal("70.00")
        assert group.costo_mercaderia == Decimal("40.00")
        assert group.gauss_status == "ok"
        assert set(group.member_order_ids) == {1, 2}

    def test_one_member_pending_no_row_makes_group_unresolved(self, db):
        _order(db, 1, pack_id=556)
        _order(db, 2, pack_id=556)
        db.flush()
        _stored(db, 1, total_gauss=Decimal("50.00"), costo_mercaderia=Decimal("30.00"))
        # order 2 has NO ml_order_metrics row at all -- pending
        db.commit()

        result = recompute_group_metrics(db, ["p:556"])

        group = result["p:556"]
        assert group.total_gauss is None
        assert group.costo_mercaderia is None
        assert group.markup_pct is None
        assert group.gauss_status == "unresolved"
        assert set(group.member_order_ids) == {1, 2}

    def test_one_member_dirty_recalculating_makes_group_unresolved(self, db):
        _order(db, 1, pack_id=557)
        _order(db, 2, pack_id=557)
        db.flush()
        _stored(db, 1, total_gauss=Decimal("50.00"), costo_mercaderia=Decimal("30.00"))
        _stored(db, 2, total_gauss=Decimal("20.00"), costo_mercaderia=Decimal("10.00"))
        db.add(MlOrderMetricsDirty(order_id=2, version=2, reason="input_write"))
        db.commit()

        result = recompute_group_metrics(db, ["p:557"])

        group = result["p:557"]
        assert group.total_gauss is None
        assert group.gauss_status == "unresolved"

    def test_single_order_pack_no_special_case(self, db):
        _order(db, 10, pack_id=558)
        db.flush()
        _stored(db, 10, total_gauss=Decimal("50.00"), costo_mercaderia=Decimal("30.00"))
        db.commit()

        result = recompute_group_metrics(db, ["p:558"])

        group = result["p:558"]
        assert group.total_gauss == Decimal("50.00")
        assert group.costo_mercaderia == Decimal("30.00")
        assert group.member_order_ids == [10]


class TestRecomputeGroupMetricsStandalone:
    def test_standalone_order_group_key(self, db):
        _order(db, 99, pack_id=None)
        db.flush()
        _stored(db, 99, total_gauss=Decimal("15.00"), costo_mercaderia=Decimal("5.00"))
        db.commit()

        result = recompute_group_metrics(db, ["o:99"])

        group = result["o:99"]
        assert group.total_gauss == Decimal("15.00")
        assert group.member_order_ids == [99]
