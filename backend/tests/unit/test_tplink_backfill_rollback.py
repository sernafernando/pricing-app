"""
Failing-first unit test for JD-003 CRITICAL (review ledger
sdd/tplink-metricas-dual-key-dedup/review-ledger-slice2):

`agregar_metricas_tplink.agregar_metricas_rango()`'s per-order
`except Exception` block must call `db.rollback()`, matching the
incremental job's pattern (`agregar_metricas_tplink_incremental.py`).
Without it, one mid-batch failure leaves the SQLAlchemy session in a
failed-transaction state and cascades `PendingRollbackError` (or
equivalent) to every subsequent order in the batch.
"""

from __future__ import annotations

from datetime import date, datetime

import pytest


class _FakeDb:
    """Minimal stand-in for a SQLAlchemy `Session` that tracks whether
    `rollback()` was called and lets `commit()` succeed trivially."""

    def __init__(self) -> None:
        self.rollback_calls: int = 0
        self.commit_calls: int = 0
        self.closed: bool = False

    def commit(self) -> None:
        self.commit_calls += 1

    def rollback(self) -> None:
        self.rollback_calls += 1

    def close(self) -> None:
        self.closed = True

    def execute(self, *args, **kwargs):
        class _Result:
            def fetchall(self_inner):
                return []

        return _Result()


def _folded_row(order_id: int) -> dict:
    return {
        "id_operacion": order_id,
        "ml_order_id": f"ML{order_id}",
        "mla_id": "1",
        "pack_id": None,
        "item_id": 1,
        "codigo": "SKU-1",
        "descripcion": "PRODUCTO",
        "marca": "TP-LINK",
        "categoria": "REDES",
        "subcategoria": "ROUTERS",
        "fecha_venta": datetime(2026, 7, 1, 10, 0, 0),
        "cantidad": 1.0,
        "monto_unitario": 100.0,
        "monto_total": 100.0,
        "costo_unitario_sin_iva": 50.0,
        "costo_total_sin_iva": 50.0,
        "comision_ml": 10.0,
        "costo_envio_ml": 0.0,
        "tipo_logistica": "self_service",
        "monto_limpio": 90.0,
        "ganancia": 40.0,
        "markup_porcentaje": 80.0,
        "offset_flex": 0.0,
        "mlp_official_store_id": 2645,
        "moneda_costo": "ARS",
        "cotizacion_dolar": 1000.0,
        "tipo_lista": "unknown",
        "porcentaje_comision_ml": 12.0,
        "prli_id": 4,
        "costo_total": 50.0,
    }


class TestBackfillRollsBackOnPerOrderFailure:
    """A failure processing order K must not cascade to orders after K."""

    def test_remaining_orders_processed_after_mid_batch_failure(self, monkeypatch) -> None:
        import app.scripts.agregar_metricas_tplink as backfill

        fake_db = _FakeDb()
        monkeypatch.setattr(backfill, "SessionLocal", lambda: fake_db)

        folded = {100: _folded_row(100), 101: _folded_row(101), 102: _folded_row(102)}
        monkeypatch.setattr(backfill, "fold_order_rows", lambda rows, db_session=None: folded)

        processed_orders: list[int] = []

        def _fake_upsert(db_session, payload):
            order_id = payload["id_operacion"]
            if order_id == 101:
                raise RuntimeError("simulated failure for order 101")
            processed_orders.append(order_id)
            return "insertado"

        monkeypatch.setattr(backfill, "upsert_metrica", _fake_upsert)

        backfill.agregar_metricas_rango(date(2026, 7, 1), date(2026, 7, 1), batch_size=100)

        # Orders 100 and 102 must have been processed despite order 101 failing.
        assert 100 in processed_orders
        assert 102 in processed_orders
        assert 101 not in processed_orders

        # rollback() must be called for the failed order (JD-003 fix).
        assert fake_db.rollback_calls >= 1
