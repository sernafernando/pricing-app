"""
T-8: Unit tests — backfill idempotency for tplink_ventas_metricas.

Verifies (SQLite-runnable):
- Running the upsert logic twice on the same fixture rows produces N rows, not 2N.
- No row with fecha_venta < 2026-01-01 is written when --from-date 2026-01-01.

Tests exercise the upsert-on-id_operacion pattern directly via the ORM model,
mirroring what the full job does (query existing by id_operacion, update or insert).
"""

from __future__ import annotations

from datetime import datetime, date
from decimal import Decimal
import pytest

from app.models.tplink_venta_metrica import TplinkVentaMetrica


def _upsert_row(db, id_operacion: int, monto_total: float, fecha_venta: datetime) -> str:
    """Helper that mirrors the full job's upsert logic (check existing, update or insert)."""
    existente = db.query(TplinkVentaMetrica).filter(TplinkVentaMetrica.id_operacion == id_operacion).first()

    if existente:
        existente.monto_total = Decimal(str(monto_total))
        return "actualizado"
    else:
        row = TplinkVentaMetrica(
            id_operacion=id_operacion,
            fecha_venta=fecha_venta,
            cantidad=1,
            monto_total=Decimal(str(monto_total)),
            mlp_official_store_id=2645,
            is_cancelled=False,
        )
        db.add(row)
        return "insertado"


class TestUpsertIdempotency:
    """Running the upsert twice over the same range does not duplicate rows."""

    def test_second_run_does_not_duplicate_rows(self, db) -> None:
        """After two upsert passes over 3 fixture rows, exactly 3 rows exist."""
        fixture_rows = [
            (70001, 1000.0, datetime(2026, 3, 1, 10, 0)),
            (70002, 2000.0, datetime(2026, 3, 2, 10, 0)),
            (70003, 3000.0, datetime(2026, 3, 3, 10, 0)),
        ]

        # First pass
        for id_op, monto, fecha in fixture_rows:
            _upsert_row(db, id_op, monto, fecha)
        db.flush()

        count_after_first = db.query(TplinkVentaMetrica).count()
        assert count_after_first == 3

        # Second pass (same rows)
        for id_op, monto, fecha in fixture_rows:
            _upsert_row(db, id_op, monto, fecha)
        db.flush()

        count_after_second = db.query(TplinkVentaMetrica).count()
        assert count_after_second == 3, (
            f"Expected 3 rows after second run, got {count_after_second}. Upsert is not idempotent."
        )

    def test_from_date_boundary_no_rows_before_cutoff(self, db) -> None:
        """Rows with fecha_venta < 2026-01-01 must NOT be written when from_date=2026-01-01."""
        # Simulate what the full job does: only process rows where fecha_venta >= from_date
        from_date = date(2026, 1, 1)

        rows_to_process = [
            # Before boundary — should NOT be inserted
            (80001, 500.0, datetime(2025, 12, 31, 10, 0)),
            # On boundary — should be inserted
            (80002, 1000.0, datetime(2026, 1, 1, 0, 0)),
            # After boundary — should be inserted
            (80003, 1500.0, datetime(2026, 6, 1, 10, 0)),
        ]

        for id_op, monto, fecha in rows_to_process:
            # Apply the same date filter the full job applies via --from-date
            if fecha.date() >= from_date:
                _upsert_row(db, id_op, monto, fecha)

        db.flush()

        # Only 2 rows should exist (on-boundary and after-boundary)
        all_rows = db.query(TplinkVentaMetrica).all()
        assert len(all_rows) == 2, f"Expected 2 rows (boundary + after), got {len(all_rows)}"

        id_ops = {r.id_operacion for r in all_rows}
        assert 80001 not in id_ops, "Row with fecha_venta < 2026-01-01 was written (boundary violation)"
        assert 80002 in id_ops
        assert 80003 in id_ops

    def test_ml_ventas_metricas_untouched_during_upsert(self, db) -> None:
        """TP-Link upsert writes only to tplink_ventas_metricas, not ml_ventas_metricas."""
        from app.models.ml_venta_metrica import MLVentaMetrica

        before_ml_count = db.query(MLVentaMetrica).count()

        _upsert_row(db, 90001, 999.0, datetime(2026, 5, 1, 10, 0))
        db.flush()

        after_ml_count = db.query(MLVentaMetrica).count()
        tplink_count = db.query(TplinkVentaMetrica).filter(TplinkVentaMetrica.id_operacion == 90001).count()

        assert after_ml_count == before_ml_count, "ml_ventas_metricas was modified by TP-Link upsert"
        assert tplink_count == 1, "tplink_ventas_metricas row was not written"
