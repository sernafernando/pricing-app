"""ventas-ml-rediseno PR20.T11 — `store_order_metrics`'s caller ALSO
enqueues/recomputes the affected order's CURRENT group in the SAME
transaction (SM R11, R7 unchanged): no new queue, no new worker, no
`BackgroundTask`.

Saving one member of a two-order pack, in the same DB transaction,
produces/updates that pack's `ml_group_metrics` row too (or leaves it
`unresolved` if the sibling is not yet resolved) -- never a second commit,
never a deferred write.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from app.models.ml_group_metrics import MlGroupMetrics
from app.models.ml_orders_ops import MlOrdersOps
from app.services.order_metrics.store import store_order_metrics
from app.services.order_metrics.types import GaussStatus, OrderMetrics


def _order(db, order_id: int, pack_id=None) -> None:
    db.add(
        MlOrdersOps(
            order_id=order_id,
            pack_id=pack_id,
            status="paid",
            ml_last_updated=datetime(2026, 9, 20, tzinfo=timezone.utc),
            date_created=datetime(2026, 9, 15, tzinfo=timezone.utc),
            seller_id=999,
        )
    )


def _metrics(order_id: int, total_gauss=Decimal("50.00"), costo_mercaderia=Decimal("30.00")) -> OrderMetrics:
    return OrderMetrics(
        order_id=order_id,
        neto=Decimal("100.00"),
        neto_sin_iva=Decimal("82.64"),
        iva_reconcilia=True,
        costo_mercaderia=costo_mercaderia,
        total_gauss=total_gauss,
        markup_pct=(total_gauss / costo_mercaderia) * Decimal("100"),
        gauss_status=GaussStatus.OK,
        provisional_falta=None,
        unresolved_reason=None,
        formula_version=2,
        computed_at=datetime.now(timezone.utc),
    )


class TestStoreOrderMetricsUpdatesGroup:
    def test_saving_one_member_of_a_resolved_pack_updates_the_group_row(self, db):
        _order(db, 1, pack_id=777)
        _order(db, 2, pack_id=777)
        db.flush()

        # Sibling already has a stored row (resolved).
        store_order_metrics(db, {2: _metrics(2, total_gauss=Decimal("20.00"), costo_mercaderia=Decimal("10.00"))})
        db.commit()

        # Now save the OTHER member -- this call alone must produce/update
        # the pack's group row in the SAME transaction, no second commit.
        store_order_metrics(db, {1: _metrics(1, total_gauss=Decimal("50.00"), costo_mercaderia=Decimal("30.00"))})
        db.commit()

        group = db.query(MlGroupMetrics).filter_by(group_key="p:777").one()
        assert group.total_gauss == Decimal("70.00")
        assert group.gauss_status == "ok"
        assert set(group.member_order_ids) == {1, 2}

    def test_saving_one_member_of_an_unresolved_pack_leaves_group_unresolved(self, db):
        _order(db, 3, pack_id=778)
        _order(db, 4, pack_id=778)
        db.flush()

        # Only order 3 gets a stored row -- order 4 stays pending (no row).
        store_order_metrics(db, {3: _metrics(3)})
        db.commit()

        group = db.query(MlGroupMetrics).filter_by(group_key="p:778").one()
        assert group.total_gauss is None
        assert group.gauss_status == "unresolved"
        assert set(group.member_order_ids) == {3, 4}

    def test_standalone_order_gets_its_own_group_row(self, db):
        _order(db, 5, pack_id=None)
        db.flush()

        store_order_metrics(db, {5: _metrics(5)})
        db.commit()

        group = db.query(MlGroupMetrics).filter_by(group_key="o:5").one()
        assert group.total_gauss == Decimal("50.00")
        assert group.member_order_ids == [5]

    def test_never_commits_the_group_row_either(self, db):
        _order(db, 6, pack_id=None)
        db.flush()

        store_order_metrics(db, {6: _metrics(6)})
        db.rollback()

        assert db.query(MlGroupMetrics).filter_by(group_key="o:6").first() is None
