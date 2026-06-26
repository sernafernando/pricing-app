"""
T-10: Unit tests — cancellation reconciliation extended to tplink_ventas_metricas.

Verifies (SQLite-runnable):
- reconciliar_cancelaciones flips is_cancelled=True on matching tplink_ventas_metricas rows.
- ML row with the same ml_order_id is also flipped (no regression).
- A TP-Link row absent from ml_cancelled_orders is NOT flipped.
- ml_ventas_metricas row NOT in cancelled list is NOT flipped.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from unittest.mock import patch, MagicMock
import pytest

from app.models.tplink_venta_metrica import TplinkVentaMetrica
from app.models.ml_venta_metrica import MLVentaMetrica


@pytest.fixture()
def cancelled_rows_fixture(db):
    """Seed ML and TP-Link metrics rows with matching ml_order_ids."""
    # ML row for order 10001 (will be cancelled)
    ml_row = MLVentaMetrica(
        id_operacion=10001,
        ml_order_id="10001",
        fecha_venta=datetime(2026, 3, 1, 10, 0),
        cantidad=1,
        monto_total=Decimal("5000.00"),
        is_cancelled=False,
    )
    # TP-Link row for same order 10001 (should also be cancelled)
    tplink_row = TplinkVentaMetrica(
        id_operacion=20001,
        ml_order_id="10001",
        fecha_venta=datetime(2026, 3, 1, 10, 0),
        cantidad=1,
        monto_total=Decimal("5000.00"),
        mlp_official_store_id=2645,
        is_cancelled=False,
    )
    # ML row for order 10002 (NOT in cancelled list — must not be flipped)
    ml_row2 = MLVentaMetrica(
        id_operacion=10002,
        ml_order_id="10002",
        fecha_venta=datetime(2026, 3, 2, 10, 0),
        cantidad=1,
        monto_total=Decimal("3000.00"),
        is_cancelled=False,
    )
    # TP-Link row for order 10003 (NOT in cancelled list — must not be flipped)
    tplink_row2 = TplinkVentaMetrica(
        id_operacion=20003,
        ml_order_id="10003",
        fecha_venta=datetime(2026, 3, 3, 10, 0),
        cantidad=1,
        monto_total=Decimal("2000.00"),
        mlp_official_store_id=2645,
        is_cancelled=False,
    )

    db.add_all([ml_row, tplink_row, ml_row2, tplink_row2])
    db.flush()
    return {"ml_row": ml_row, "tplink_row": tplink_row, "ml_row2": ml_row2, "tplink_row2": tplink_row2}


_FAKE_CANCELLED = [
    {
        "order_id": 10001,
        "cancelled_at": datetime(2026, 3, 15, 12, 0),
        "date_closed": datetime(2026, 3, 15, 12, 0),
    }
]


class TestTplinkCancelReconciliacion:
    """reconciliar_cancelaciones marks both ml and tplink rows as cancelled."""

    def test_tplink_row_is_marked_cancelled(self, db, cancelled_rows_fixture) -> None:
        """TP-Link row matching ml_order_id=10001 must be flipped to is_cancelled=True."""
        from app.services.ml_cancelacion_reconciliacion_service import reconciliar_cancelaciones

        with patch(
            "app.services.ml_cancelacion_reconciliacion_service.fetch_cancelled_since",
            return_value=_FAKE_CANCELLED,
        ):
            stats = reconciliar_cancelaciones(db, since=None, lookback_days=90)

        tplink_row = db.query(TplinkVentaMetrica).filter_by(id_operacion=20001).first()
        assert tplink_row is not None
        assert tplink_row.is_cancelled is True, "TP-Link row was not marked cancelled"
        assert tplink_row.fecha_cancelacion is not None

    def test_ml_row_is_also_marked_cancelled(self, db, cancelled_rows_fixture) -> None:
        """ML row matching ml_order_id=10001 must also be flipped (no regression)."""
        from app.services.ml_cancelacion_reconciliacion_service import reconciliar_cancelaciones

        with patch(
            "app.services.ml_cancelacion_reconciliacion_service.fetch_cancelled_since",
            return_value=_FAKE_CANCELLED,
        ):
            reconciliar_cancelaciones(db, since=None, lookback_days=90)

        ml_row = db.query(MLVentaMetrica).filter_by(id_operacion=10001).first()
        assert ml_row is not None
        assert ml_row.is_cancelled is True, "ML row was not marked cancelled (regression)"

    def test_tplink_row_not_in_cancelled_list_untouched(self, db, cancelled_rows_fixture) -> None:
        """TP-Link row for ml_order_id=10003 (not in cancelled list) must NOT be flipped."""
        from app.services.ml_cancelacion_reconciliacion_service import reconciliar_cancelaciones

        with patch(
            "app.services.ml_cancelacion_reconciliacion_service.fetch_cancelled_since",
            return_value=_FAKE_CANCELLED,
        ):
            reconciliar_cancelaciones(db, since=None, lookback_days=90)

        tplink_row2 = db.query(TplinkVentaMetrica).filter_by(id_operacion=20003).first()
        assert tplink_row2 is not None
        assert tplink_row2.is_cancelled is False, "TP-Link row was incorrectly marked cancelled"

    def test_ml_row_not_in_cancelled_list_untouched(self, db, cancelled_rows_fixture) -> None:
        """ML row for ml_order_id=10002 (not in cancelled list) must NOT be flipped."""
        from app.services.ml_cancelacion_reconciliacion_service import reconciliar_cancelaciones

        with patch(
            "app.services.ml_cancelacion_reconciliacion_service.fetch_cancelled_since",
            return_value=_FAKE_CANCELLED,
        ):
            reconciliar_cancelaciones(db, since=None, lookback_days=90)

        ml_row2 = db.query(MLVentaMetrica).filter_by(id_operacion=10002).first()
        assert ml_row2 is not None
        assert ml_row2.is_cancelled is False, "ML row was incorrectly marked cancelled"

    def test_stats_include_tplink_count(self, db, cancelled_rows_fixture) -> None:
        """Stats dict must reflect cancellations in both tables."""
        from app.services.ml_cancelacion_reconciliacion_service import reconciliar_cancelaciones

        with patch(
            "app.services.ml_cancelacion_reconciliacion_service.fetch_cancelled_since",
            return_value=_FAKE_CANCELLED,
        ):
            stats = reconciliar_cancelaciones(db, since=None, lookback_days=90)

        assert stats["leidas"] == 1
        # ml_ventas_metricas: 1 row flipped
        assert stats["metricas_marcadas"] >= 1
        # tplink_ventas_metricas: 1 row flipped (tracked separately)
        assert stats.get("tplink_metricas_marcadas", 0) >= 1
