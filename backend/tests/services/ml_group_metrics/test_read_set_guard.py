"""ventas-ml-rediseno PR20.T13/T14 — read-set guard over
`recompute_group_metrics`.

`recompute_group_metrics` reads `ml_orders_ops` (already `TRIGGERED_TABLES`)
plus `ml_order_metrics` / `ml_order_metrics_dirty` (per-member rows, via
`read_stored_metrics`/`metrics_state_for_orders`). This asserts the guard
passes with NO new table added to `TRIGGERED_TABLES` -- `ml_order_metrics`
is itself a derived/output table, not a raw metrics input; its own upstream
inputs are already covered by `TRIGGERED_TABLES`. If a bare run trips the
guard, this test's failure IS the finding: the table it names must be added
to `NON_INPUT_READ_TABLES` with the reason inline (T14).
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from app.models.ml_order_metrics import MlOrderMetrics
from app.models.ml_orders_ops import MlOrdersOps
from app.services.ml_group_metrics.compute import recompute_group_metrics
from app.services.order_metrics.read_set_guard import assert_read_set_is_triggered


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


def _stored(db, order_id: int) -> None:
    db.add(
        MlOrderMetrics(
            order_id=order_id,
            neto=Decimal("100.00"),
            neto_sin_iva=Decimal("82.64"),
            iva_reconcilia=True,
            costo_mercaderia=Decimal("30.00"),
            total_gauss=Decimal("50.00"),
            markup_pct=Decimal("166.67"),
            gauss_status="ok",
            formula_version=2,
            computed_at=datetime.now(timezone.utc),
        )
    )


class TestReadSetGuardCoversRecomputeGroupMetrics:
    def test_recompute_group_metrics_read_set_is_fully_triggered(self, db) -> None:
        _order(db, 1, pack_id=999)
        _order(db, 2, pack_id=999)
        db.flush()
        _stored(db, 1)
        _stored(db, 2)
        db.commit()

        with assert_read_set_is_triggered(db.get_bind()):
            recompute_group_metrics(db, ["p:999"])
