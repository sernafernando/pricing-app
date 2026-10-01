"""ODD `metricas-ml-tablero` T2 against real Postgres: 16-digit BigInteger
order/pack ids, the real `ON CONFLICT` upsert on the (product, MLA, day) key,
row-value `IN` and the tz-aware day bounds (America/Argentina/Buenos_Aires)."""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal

import pytest

from app.core.config import settings
from app.models.ml_daily_metrics import MlProductDailyMetrics
from app.models.ml_order_item_costo import MlOrderItemCosto
from app.models.ml_orders_ops import MlOrderItemOps, MlOrdersOps
from app.models.ml_payments import MlPaymentOps
from app.services.ml_daily_metrics.rollup import refresh_rollup
from app.services.order_metrics.store import store_order_metrics
from tests.services.ml_daily_metrics.test_rollup import _metrics

ORDER_A = 2000012345678901
ORDER_B = 2000012345678902
PACK = 2000098765432101
LATE_EVENING_BA = datetime(2026, 9, 21, 2, 59, tzinfo=timezone.utc)  # 23:59 of the 20th in BA


@pytest.fixture(autouse=True)
def _seller(monkeypatch):
    monkeypatch.setattr(settings, "ML_USER_ID", 999)


def _seed(db, order_id: int, mla: str, qty: int, costo: str) -> None:
    db.add(
        MlOrdersOps(
            order_id=order_id,
            pack_id=PACK,
            status="paid",
            ml_last_updated=LATE_EVENING_BA,
            date_created=LATE_EVENING_BA,
            seller_id=999,
            currency_id="ARS",
        )
    )
    db.flush()
    db.add(MlPaymentOps(payment_id=order_id + 7, order_id=order_id, status="approved", date_approved=LATE_EVENING_BA))
    db.add(MlOrderItemOps(order_id=order_id, item_id=mla, quantity=qty, unit_price=Decimal("1000.00")))
    db.add(
        MlOrderItemCosto(
            order_id=order_id,
            item_id=mla,
            variation_id=None,
            costo_origen=Decimal(costo),
            moneda="ARS",
            costo_unitario_ars=Decimal(costo),
            iva_pct=21,
            precio_unitario=Decimal("1000.00"),
            fuente="test",
            producto_item_id=4242,
        )
    )
    db.flush()


@pytest.mark.postgres
class TestRollupOnPostgres:
    def test_pack_with_real_size_ids_lands_on_the_business_day(self, pg_order_metrics_db) -> None:
        db = pg_order_metrics_db
        _seed(db, ORDER_A, "MLA7000000001", 2, "300")
        _seed(db, ORDER_B, "MLA7000000001", 1, "300")

        store_order_metrics(db, {ORDER_A: _metrics(ORDER_A), ORDER_B: _metrics(ORDER_B)})
        # The upsert path: a second store of the same bucket updates in place.
        store_order_metrics(db, {ORDER_A: _metrics(ORDER_A, total_gauss="70.00")})

        rows = db.query(MlProductDailyMetrics).all()
        assert [(r.product_item_id, r.mla, r.day) for r in rows] == [(4242, "MLA7000000001", date(2026, 9, 20))]
        assert rows[0].units == 3
        assert rows[0].orders == 2
        assert rows[0].total_gauss == Decimal("120.00")
        assert rows[0].costo == Decimal("400.00")

    def test_refresh_of_an_emptied_bucket_deletes_it(self, pg_order_metrics_db) -> None:
        db = pg_order_metrics_db
        _seed(db, ORDER_A, "MLA7000000002", 1, "300")
        store_order_metrics(db, {ORDER_A: _metrics(ORDER_A)})
        db.query(MlOrderItemOps).filter_by(order_id=ORDER_A).delete()
        db.flush()

        refresh_rollup(db, {("MLA7000000002", date(2026, 9, 20))})

        assert db.query(MlProductDailyMetrics).count() == 0
