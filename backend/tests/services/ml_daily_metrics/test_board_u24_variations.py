"""Review finding: the rolling-24h units joined frozen costs on (order, MLA)
only, while the rollup also matches `variation_id`. One order with two
variations of one MLA, each frozen against a different product, double
counted the quantity and credited it to both products -- so 24h disagreed
with 3d/7d. Both now share ONE join condition."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.core.config import settings
from app.models.ml_daily_metrics import MlProductDailyMetrics
from app.models.ml_group_metrics import MlGroupMetrics
from app.models.ml_order_item_costo import MlOrderItemCosto
from app.models.ml_order_metrics import MlOrderMetrics
from app.models.ml_orders_ops import MlOrderItemOps, MlOrdersOps
from app.services.ml_daily_metrics import board
from app.services.ml_daily_metrics.rollup import business_day, refresh_rollup

NOW = datetime(2026, 9, 30, 18, 0, tzinfo=timezone.utc)
ORDER = 2000077000000001
MLA = "MLA7700000001"


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setattr(settings, "ML_USER_ID", 999)
    monkeypatch.setattr(board, "now_utc", lambda: NOW)


def _seed(db) -> datetime:
    accredited = NOW - timedelta(hours=2)
    db.add(
        MlOrdersOps(
            order_id=ORDER,
            status="paid",
            ml_last_updated=accredited,
            date_created=accredited,
            seller_id=999,
            currency_id="ARS",
        )
    )
    db.flush()
    for variation, qty, product in ((1, 2, 11), (2, 3, 12)):
        db.add(MlOrderItemOps(order_id=ORDER, item_id=MLA, variation_id=variation, quantity=qty, unit_price=100))
        db.add(
            MlOrderItemCosto(
                order_id=ORDER,
                item_id=MLA,
                variation_id=variation,
                costo_origen=10,
                moneda="ARS",
                costo_unitario_ars=10,
                iva_pct=21,
                precio_unitario=100,
                fuente="t",
                producto_item_id=product,
            )
        )
    db.add(
        MlOrderMetrics(
            order_id=ORDER,
            costo_mercaderia=Decimal("50"),
            total_gauss=Decimal("10"),
            gauss_status="ok",
            formula_version=2,
            computed_at=NOW,
        )
    )
    db.add(
        MlGroupMetrics(
            group_key=f"o:{ORDER}",
            gauss_status="ok",
            member_order_ids=[ORDER],
            group_date=accredited,
            formula_version=2,
            computed_at=NOW,
        )
    )
    db.flush()
    return accredited


def test_24h_units_per_product_match_the_rollup(db) -> None:
    accredited = _seed(db)
    f = board.BoardFilter(date_from=date(2026, 9, 1), date_to=date(2026, 9, 30))

    u24 = board.Board(db, f)._u24()
    last_24h = {(r.product, r.mla): int(r.units) for r in db.execute(select(u24.c.product, u24.c.mla, u24.c.units))}

    refresh_rollup(db, {(MLA, business_day(accredited))})
    rollup = {(r.product_item_id, r.mla): r.units for r in db.query(MlProductDailyMetrics).filter_by(mla=MLA)}

    assert last_24h == {(11, MLA): 2, (12, MLA): 3}
    assert last_24h == rollup
