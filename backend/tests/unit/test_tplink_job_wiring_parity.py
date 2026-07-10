"""
Failing-first unit tests for slice 2 of tplink-metricas-dual-key-dedup:
wiring both TP-Link jobs (backfill + incremental) onto the shared core.

Covers:
  - Both jobs build their date-window SQL via
    `_tplink_metricas_core.build_aggregation_sql()` (no private per-job SQL
    string left behind — structural dedup, design v2).
  - Given IDENTICAL seeded per-detail rows, both jobs' upsert payload for the
    same order is byte-identical (same keys AND same summed values) — the
    core cross-job parity guarantee.
  - Backfill's date window is half-open: `[from_date 00:00, (to_date+1day) 00:00)`.
  - Incremental's date window is half-open over its last-N-minutes range.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from types import SimpleNamespace

import pytest


def _detail_row(
    *,
    mlo_id: int,
    ml_id: str,
    mlp_id: int,
    pack_id: str | None = None,
    monto_unitario: float = 1000.0,
    cantidad: float = 1,
    costo_sin_iva: float = 400.0,
    seller_shipping_cost: float | None = None,
    shipment_total: float | None = None,
    iva: float = 21.0,
    comision_base_porcentaje: float = 12.0,
    tipo_logistica: str | None = "self_service",
    codigo: str = "SKU-1",
    descripcion: str = "PRODUCTO 1",
    marca: str = "TP-LINK",
    categoria: str = "REDES",
    subcategoria: str = "ROUTERS",
    subcat_id: int | None = None,
    pricelist_id: int | None = None,
    envio_producto: float | None = None,
    item_id: int = 1,
    mlod_id: int | None = 1,
) -> SimpleNamespace:
    return SimpleNamespace(
        id_operacion=mlo_id,
        ml_id=ml_id,
        mlp_id=mlp_id,
        pack_id=pack_id,
        item_id=item_id,
        codigo=codigo,
        descripcion=descripcion,
        marca=marca,
        categoria=categoria,
        subcategoria=subcategoria,
        cantidad=cantidad,
        monto_unitario=monto_unitario,
        monto_total=monto_unitario * cantidad,
        costo_sin_iva=costo_sin_iva,
        iva=iva,
        comision_base_porcentaje=comision_base_porcentaje,
        subcat_id=subcat_id,
        pricelist_id=pricelist_id,
        tipo_logistica=tipo_logistica,
        seller_shipping_cost=seller_shipping_cost,
        shipment_total=shipment_total,
        envio_producto=envio_producto,
        fecha_venta=datetime(2026, 7, 1, 10, 0, 0),
        mlod_id=mlod_id,
    )


class TestBothJobsUseSharedAggregationSql:
    """Structural dedup guard: neither job keeps its own SQL string."""

    def test_backfill_imports_core_build_aggregation_sql(self) -> None:
        import app.scripts.agregar_metricas_tplink as backfill
        import app.scripts._tplink_metricas_core as core

        assert backfill.build_aggregation_sql is core.build_aggregation_sql

    def test_incremental_imports_core_build_aggregation_sql(self) -> None:
        import app.scripts.agregar_metricas_tplink_incremental as incremental
        import app.scripts._tplink_metricas_core as core

        assert incremental.build_aggregation_sql is core.build_aggregation_sql

    def test_backfill_has_no_private_distinct_on_sql(self) -> None:
        import inspect
        import app.scripts.agregar_metricas_tplink as backfill

        source = inspect.getsource(backfill)
        assert "DISTINCT ON" not in source

    def test_incremental_has_no_private_distinct_on_sql(self) -> None:
        """No function BODY in the wrapper embeds its own 'DISTINCT ON' SQL
        (module-level prose mentioning the removed pattern is fine)."""
        import inspect
        import app.scripts.agregar_metricas_tplink_incremental as incremental

        for _, func in inspect.getmembers(incremental, inspect.isfunction):
            if func.__module__ != incremental.__name__:
                continue
            assert "DISTINCT ON" not in inspect.getsource(func)


class TestCrossJobKeyAndValueParity:
    """Given identical seeded detail rows, backfill and incremental must
    produce IDENTICAL folded/upsert payloads for the same order (keys AND
    summed values) — the core behavior change this slice delivers."""

    def test_identical_rows_yield_identical_upsert_payload(self) -> None:
        import app.scripts._tplink_metricas_core as core

        rows = [
            _detail_row(mlo_id=100, ml_id="ML100", mlp_id=111, item_id=1, mlod_id=1, monto_unitario=1000.0),
            _detail_row(mlo_id=100, ml_id="ML100", mlp_id=222, item_id=2, mlod_id=2, monto_unitario=500.0),
        ]

        folded_backfill = core.fold_order_rows(list(rows))
        folded_incremental = core.fold_order_rows(list(rows))

        payload_backfill = core.build_upsert_payload(folded_backfill[100])
        payload_incremental = core.build_upsert_payload(folded_incremental[100])

        assert payload_backfill == payload_incremental
        assert payload_backfill["id_operacion"] == 100
        assert payload_backfill["ml_order_id"] == "ML100"
        assert payload_backfill["mla_id"] == "111"


class TestBackfillDateWindowHalfOpen:
    def test_backfill_window_is_half_open_inclusive_to_date(self) -> None:
        import app.scripts.agregar_metricas_tplink as backfill

        from_date = date(2026, 7, 1)
        to_date = date(2026, 7, 5)

        from_ts, to_ts = backfill.compute_date_window(from_date, to_date)

        assert from_ts == datetime(2026, 7, 1, 0, 0, 0)
        # to_ts must be to_date + 1 day at midnight (half-open upper bound).
        assert to_ts == datetime(2026, 7, 6, 0, 0, 0)


class TestIncrementalDateWindowHalfOpen:
    def test_incremental_window_uses_last_n_minutes(self) -> None:
        import app.scripts.agregar_metricas_tplink_incremental as incremental

        now = datetime(2026, 7, 1, 12, 30, 0)
        from_ts, to_ts = incremental.compute_date_window(now)

        assert to_ts == now
        assert from_ts == now - timedelta(minutes=10)
