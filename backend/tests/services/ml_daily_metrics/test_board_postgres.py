"""ODD `metricas-ml-tablero` T3 on real Postgres: the rolling-24h window reads
`ml_group_metrics.member_order_ids` (a real `ARRAY(BigInteger)` here, JSON
under SQLite) with 16-digit order ids, and leaves out a cancellation ML did
not cover."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import text

from app.models.ml_order_item_costo import MlOrderItemCosto
from app.models.ml_orders_ops import MlOrderItemOps, MlOrdersOps
from app.services.ml_daily_metrics import board

NOW = datetime(2026, 9, 30, 18, 0, tzinfo=timezone.utc)
PAID = 2000012345678911
CANCELLED = 2000012345678912
OLD = 2000012345678913


def _sale(db, order_id: int, *, status: str, accredited: datetime, qty: int) -> None:
    db.add(
        MlOrdersOps(
            order_id=order_id,
            status=status,
            ml_last_updated=NOW,
            date_created=NOW,
            seller_id=999,
            currency_id="ARS",
        )
    )
    db.flush()
    db.add(MlOrderItemOps(order_id=order_id, item_id="MLA8000000001", quantity=qty, unit_price=Decimal("10")))
    db.add(
        MlOrderItemCosto(
            order_id=order_id,
            item_id="MLA8000000001",
            costo_origen=1,
            moneda="ARS",
            costo_unitario_ars=1,
            iva_pct=21,
            precio_unitario=10,
            fuente="t",
            producto_item_id=777,
        )
    )
    # Raw SQL: the shared metadata's ARRAY column may be patched to JSON by
    # the SQLite fixtures (see `ml_group_metrics/store.py`), so the ORM
    # insert would send a JSON string Postgres rejects as an array.
    db.execute(
        text(
            "INSERT INTO ml_group_metrics "
            "(group_key, gauss_status, member_order_ids, group_date, formula_version, computed_at) "
            "VALUES (:gk, 'ok', ARRAY[CAST(:oid AS BIGINT)], :gd, 1, now())"
        ),
        {"gk": f"o:{order_id}", "oid": order_id, "gd": accredited},
    )


@pytest.mark.postgres
def test_units_last_24h_on_postgres(pg_order_metrics_db, monkeypatch) -> None:
    monkeypatch.setattr(board, "now_utc", lambda: NOW)
    db = pg_order_metrics_db
    _sale(db, PAID, status="paid", accredited=NOW - timedelta(hours=3), qty=2)
    _sale(db, CANCELLED, status="cancelled", accredited=NOW - timedelta(hours=1), qty=5)
    _sale(db, OLD, status="paid", accredited=NOW - timedelta(hours=30), qty=7)

    assert board._units_last_24h(db) == {(777, "MLA8000000001"): 2}
