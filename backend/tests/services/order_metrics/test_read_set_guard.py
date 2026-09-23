"""RED/GREEN -- read-set guard (ventas-ml-rediseno PR4.T10/T11, design D3
"Structural guard"). SQLite-safe: runs in normal CI, no `@pytest.mark.postgres`.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy import text

from app.models.ml_order_item_costo import MlOrderItemCosto
from app.models.ml_orders_ops import MlOrderItemOps, MlOrdersOps
from app.models.varios_venta_pct import VariosVentaPct
from app.services.order_metrics.compute import compute_order_metrics
from app.services.order_metrics.read_set_guard import (
    KNOWN_INPUT_TABLES,
    UntriggeredReadError,
    assert_read_set_is_triggered,
)
from app.services.order_metrics.triggers import TRIGGERED_TABLES


def _order(db, order_id: int) -> None:
    db.add(
        MlOrdersOps(
            order_id=order_id,
            status="paid",
            ml_last_updated=datetime(2026, 8, 20, tzinfo=timezone.utc),
            date_created=datetime(2026, 8, 15, tzinfo=timezone.utc),
            seller_id=999,
        )
    )
    db.add(MlOrderItemOps(order_id=order_id, item_id="MLA1", seller_sku="SKU-1", quantity=1))
    db.add(
        MlOrderItemCosto(
            order_id=order_id,
            item_id="MLA1",
            costo_origen=Decimal("10.00"),
            moneda="ARS",
            costo_unitario_ars=Decimal("10.00"),
            iva_pct=Decimal("21.00"),
            precio_unitario=Decimal("100.00"),
            fuente="sku",
            producto_item_id=1,
        )
    )
    db.add(VariosVentaPct(porcentaje=Decimal("0.00"), fecha_desde=date(2020, 1, 1), fecha_hasta=None))


class TestReadSetGuardCoversCurrentTables:
    def test_compute_order_metrics_read_set_is_fully_triggered(self, db) -> None:
        """`compute_order_metrics`'s ACTUAL reads today must be a subset of
        `TRIGGERED_TABLES` -- this is the guard's normal-operation GREEN
        path, run against the real production code path (PR1's producer),
        not a stub."""
        order_id = 9101
        _order(db, order_id)
        db.commit()

        engine = db.get_bind()
        with assert_read_set_is_triggered(engine) as seen:
            compute_order_metrics(db, [order_id])

        # The guard only asserts about KNOWN_INPUT_TABLES; sanity-check it
        # actually observed at least one real input table, or the test
        # would pass vacuously.
        assert seen & KNOWN_INPUT_TABLES


class TestReadSetGuardCatchesAWideningReadSet:
    def test_missing_table_in_triggered_tables_raises(self, db, monkeypatch) -> None:
        """Simulates the exact hazard the guard exists for: a table in the
        real read set that is NOT (yet) in `TRIGGERED_TABLES`. Removing one
        real table `compute_order_metrics` reads from the covered set must
        fail the guard."""
        order_id = 9102
        _order(db, order_id)
        db.commit()

        narrowed = TRIGGERED_TABLES - {"ml_order_item_costos"}
        monkeypatch.setattr("app.services.order_metrics.read_set_guard.TRIGGERED_TABLES", narrowed)

        engine = db.get_bind()
        try:
            with assert_read_set_is_triggered(engine):
                compute_order_metrics(db, [order_id])
        except UntriggeredReadError as exc:
            assert "ml_order_item_costos" in str(exc)
        else:
            raise AssertionError("expected UntriggeredReadError for a read-set table missing from TRIGGERED_TABLES")


class TestReadSetGuardCannotBeANoOp:
    """PR5 review G1: `KNOWN_INPUT_TABLES` was once assigned `TRIGGERED_TABLES`
    directly (the SAME object), which makes `seen & KNOWN_INPUT_TABLES` blind
    to any table absent from BOTH sets -- exactly what a brand-new,
    completely unlisted table looks like. Unlike
    `TestReadSetGuardCatchesAWideningReadSet` above (which narrows
    `TRIGGERED_TABLES` but leaves `KNOWN_INPUT_TABLES` referencing the
    original, unnarrowed frozenset -- a divergence that can never happen in
    production, where the two names are always assigned together), this test
    uses the REAL, UNPATCHED production `TRIGGERED_TABLES` /
    `KNOWN_INPUT_TABLES` and simply reads a table neither one lists. That is
    the actual production configuration; a guard that cannot fail here is
    the guard PR5 review G1 found."""

    def test_a_genuinely_unlisted_table_read_raises(self, db) -> None:
        assert "ml_order_metrics" not in KNOWN_INPUT_TABLES
        assert "ml_order_metrics" not in TRIGGERED_TABLES

        engine = db.get_bind()
        with pytest.raises(UntriggeredReadError, match="ml_order_metrics"):
            with assert_read_set_is_triggered(engine):
                db.execute(text("SELECT * FROM ml_order_metrics"))
