"""
T-1 / T-2: Unit tests — TplinkVentaMetrica ORM model.

Verifies:
- Model maps to tplink_ventas_metricas table.
- Insert + read round-trip succeeds.
- id_operacion unique constraint raises IntegrityError on duplicate.

SQLite-runnable (all column types are SQLite-compatible via conftest patches).
"""

from __future__ import annotations

import pytest
from sqlalchemy.exc import IntegrityError

from app.models.tplink_venta_metrica import TplinkVentaMetrica
from datetime import datetime, date
from decimal import Decimal


class TestTplinkVentaMetricaModel:
    """ORM maps to tplink_ventas_metricas; basic CRUD + constraints."""

    def test_tablename(self) -> None:
        assert TplinkVentaMetrica.__tablename__ == "tplink_ventas_metricas"

    def test_insert_and_read_round_trip(self, db) -> None:
        """Insert a row and read it back; all supplied fields are preserved."""
        row = TplinkVentaMetrica(
            id_operacion=99001,
            ml_order_id="ORDER-001",
            item_id=101,
            codigo="TPL-001",
            descripcion="TP-Link Switch",
            marca="TP-Link",
            categoria="Networking",
            fecha_venta=datetime(2026, 3, 15, 10, 0, 0),
            fecha_calculo=date(2026, 3, 15),
            cantidad=2,
            monto_unitario=Decimal("5000.00"),
            monto_total=Decimal("10000.00"),
            mlp_official_store_id=2645,
            is_cancelled=False,
        )
        db.add(row)
        db.flush()

        retrieved = db.query(TplinkVentaMetrica).filter_by(id_operacion=99001).first()
        assert retrieved is not None
        assert retrieved.codigo == "TPL-001"
        assert retrieved.mlp_official_store_id == 2645
        assert retrieved.is_cancelled is False
        assert int(retrieved.monto_total) == 10000

    def test_id_operacion_unique_constraint(self, db) -> None:
        """Inserting the same id_operacion twice raises IntegrityError."""
        row1 = TplinkVentaMetrica(
            id_operacion=99002,
            fecha_venta=datetime(2026, 3, 15, 10, 0, 0),
            cantidad=1,
            monto_total=Decimal("1000.00"),
            is_cancelled=False,
        )
        db.add(row1)
        db.flush()

        row2 = TplinkVentaMetrica(
            id_operacion=99002,  # duplicate
            fecha_venta=datetime(2026, 3, 15, 11, 0, 0),
            cantidad=1,
            monto_total=Decimal("2000.00"),
            is_cancelled=False,
        )
        db.add(row2)
        with pytest.raises(IntegrityError):
            db.flush()

    def test_ml_venta_metrica_untouched(self, db) -> None:
        """MLVentaMetrica (ml_ventas_metricas) is a separate table."""
        from app.models.ml_venta_metrica import MLVentaMetrica

        assert MLVentaMetrica.__tablename__ == "ml_ventas_metricas"
        assert TplinkVentaMetrica.__tablename__ != MLVentaMetrica.__tablename__
