"""ventas-ml-rediseno PR20.T9 — `store_group_metrics(db, group_metrics_by_key)`
upserts `ml_group_metrics`, NEVER commits -- caller controls the
transaction, same contract as `store_order_metrics`.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from app.models.ml_group_metrics import MlGroupMetrics
from app.services.ml_group_metrics.compute import GroupMetrics
from app.services.ml_group_metrics.store import store_group_metrics


class TestStoreGroupMetrics:
    def test_inserts_a_new_row(self, db):
        metrics = GroupMetrics(
            group_key="p:1",
            neto=Decimal("100.00"),
            neto_sin_iva=Decimal("82.64"),
            costo_mercaderia=Decimal("40.00"),
            total_gauss=Decimal("60.00"),
            markup_pct=Decimal("150.00"),
            gauss_status="ok",
            member_order_ids=[1, 2],
            group_date=datetime(2026, 9, 20, tzinfo=timezone.utc),
        )

        store_group_metrics(db, {"p:1": metrics})
        db.commit()

        row = db.query(MlGroupMetrics).filter_by(group_key="p:1").one()
        assert row.total_gauss == Decimal("60.00")
        assert row.member_order_ids == [1, 2]

    def test_does_not_commit(self, db):
        metrics = GroupMetrics(
            group_key="p:2",
            neto=None,
            neto_sin_iva=None,
            costo_mercaderia=None,
            total_gauss=None,
            markup_pct=None,
            gauss_status="unresolved",
            member_order_ids=[3],
        )

        store_group_metrics(db, {"p:2": metrics})
        # No commit here -- rollback must wipe it out if the function
        # committed on its own.
        db.rollback()

        assert db.query(MlGroupMetrics).filter_by(group_key="p:2").first() is None

    def test_second_call_updates_the_same_row_instead_of_duplicating(self, db):
        first = GroupMetrics(
            group_key="p:3",
            neto=Decimal("10.00"),
            neto_sin_iva=Decimal("8.26"),
            costo_mercaderia=Decimal("5.00"),
            total_gauss=Decimal("5.00"),
            markup_pct=Decimal("100.00"),
            gauss_status="ok",
            member_order_ids=[10],
        )
        store_group_metrics(db, {"p:3": first})
        db.commit()

        second = GroupMetrics(
            group_key="p:3",
            neto=Decimal("20.00"),
            neto_sin_iva=Decimal("16.53"),
            costo_mercaderia=Decimal("10.00"),
            total_gauss=Decimal("10.00"),
            markup_pct=Decimal("100.00"),
            gauss_status="ok",
            member_order_ids=[10, 11],
        )
        store_group_metrics(db, {"p:3": second})
        db.commit()

        rows = db.query(MlGroupMetrics).filter_by(group_key="p:3").all()
        assert len(rows) == 1
        assert rows[0].total_gauss == Decimal("10.00")
        assert rows[0].member_order_ids == [10, 11]

    def test_empty_input_is_a_noop(self, db):
        store_group_metrics(db, {})
        db.commit()
        assert db.query(MlGroupMetrics).count() == 0
