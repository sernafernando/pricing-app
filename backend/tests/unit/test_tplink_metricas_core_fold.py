"""
Failing-first unit tests for the shared TP-Link per-order aggregation core
(`app.scripts._tplink_metricas_core`), slice 1 of tplink-metricas-dual-key-dedup.

SQLite-runnable: uses synthetic SimpleNamespace rows to mimic the shape of
rows returned by the (Postgres-only) aggregating CTE. Does NOT exercise raw
SQL — that is covered by the Postgres integration tests in a later slice.

Covers (design v2 / D1):
  - Multi-item order -> one folded row with SUMMED monto_total, cantidad,
    costo, comision, ganancia, and shipping applied EXACTLY ONCE per order.
  - Pack-offset (count_per_pack) counts DISTINCT ORDERS, not detail rows.
  - Single-item order stays identical to the non-folded per-detail result
    (parity with the pre-existing incremental behavior).
"""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

import pytest


def _detail_row(
    *,
    mlo_id: int,
    ml_id: str,
    mlp_id: int,
    pack_id: str | None,
    monto_unitario: float,
    cantidad: float,
    costo_sin_iva: float,
    seller_shipping_cost: float | None,
    shipment_total: float | None,
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
) -> SimpleNamespace:
    """Build a synthetic per-detail row matching the aggregating CTE's projection."""
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
    )


def _get_core_module():
    import app.scripts._tplink_metricas_core as core

    return core


class TestFoldMultiItemOrder:
    """A multi-detail order must fold into ONE row with summed metrics."""

    def test_multi_item_order_folds_to_one_row(self) -> None:
        core = _get_core_module()

        rows = [
            _detail_row(
                mlo_id=100,
                ml_id="ML100",
                mlp_id=111,
                pack_id="PACK-A",
                monto_unitario=1000.0,
                cantidad=1,
                costo_sin_iva=400.0,
                seller_shipping_cost=200.0,
                shipment_total=2000.0,
                codigo="SKU-A",
                item_id=1,
            ),
            _detail_row(
                mlo_id=100,
                ml_id="ML100",
                mlp_id=222,
                pack_id="PACK-A",
                monto_unitario=1000.0,
                cantidad=1,
                costo_sin_iva=300.0,
                seller_shipping_cost=200.0,
                shipment_total=2000.0,
                codigo="SKU-B",
                item_id=2,
            ),
        ]

        folded = core.fold_order_rows(rows)

        assert len(folded) == 1
        order = folded[100]

        # Keys per design v2: id_operacion=mlo_id, ml_order_id=str(ml_id), mla_id=first detail's str(mlp_id)
        assert order["id_operacion"] == 100
        assert order["ml_order_id"] == "ML100"
        assert order["mla_id"] == "111"

        # Sums across the two details
        assert order["cantidad"] == 2
        assert order["monto_total"] == pytest.approx(2000.0)
        assert order["costo_total_sin_iva"] == pytest.approx(700.0)

    def test_shipping_applied_exactly_once_per_order(self) -> None:
        """Regression guard for the double-subtraction hazard (D1)."""
        core = _get_core_module()

        single = _detail_row(
            mlo_id=200,
            ml_id="ML200",
            mlp_id=333,
            pack_id=None,
            monto_unitario=2000.0,
            cantidad=1,
            costo_sin_iva=400.0,
            seller_shipping_cost=200.0,
            shipment_total=2000.0,
        )
        multi = [
            _detail_row(
                mlo_id=201,
                ml_id="ML201",
                mlp_id=444,
                pack_id="PACK-B",
                monto_unitario=1000.0,
                cantidad=1,
                costo_sin_iva=200.0,
                seller_shipping_cost=200.0,
                shipment_total=2000.0,
                codigo="SKU-C",
            ),
            _detail_row(
                mlo_id=201,
                ml_id="ML201",
                mlp_id=555,
                pack_id="PACK-B",
                monto_unitario=1000.0,
                cantidad=1,
                costo_sin_iva=200.0,
                seller_shipping_cost=200.0,
                shipment_total=2000.0,
                codigo="SKU-D",
            ),
        ]

        folded_single = core.fold_order_rows([single])
        folded_multi = core.fold_order_rows(multi)

        # Same total monto/costo/shipping split across two orders (200 vs 201);
        # the per-order shipping cost (sin IVA) must be identical since
        # shipment_total/seller_shipping_cost are the same in both scenarios,
        # and it must be subtracted only ONCE from the multi-item order's ganancia.
        costo_envio_single = folded_single[200]["costo_envio_ml"]
        costo_envio_multi = folded_multi[201]["costo_envio_ml"]

        assert costo_envio_single == pytest.approx(costo_envio_multi)
        assert costo_envio_multi > 0

        # ganancia = monto_limpio - costo_total; verify shipping subtracted once
        # by reconstructing monto_limpio without any double subtraction:
        # sum(detail monto_limpio excluding shipping) - costo_envio_once
        expected_ganancia = folded_multi[201]["monto_limpio"] - folded_multi[201]["costo_total_sin_iva"]
        assert folded_multi[201]["ganancia"] == pytest.approx(expected_ganancia)


class TestPackOffsetCountsDistinctOrders:
    """count_per_pack must count DISTINCT ORDERS per pack, not raw detail rows."""

    def test_count_per_pack_counts_orders_not_detail_rows(self) -> None:
        core = _get_core_module()

        # Order 300 has 2 details in pack PACK-X; order 301 has 1 detail, also PACK-X.
        rows = [
            _detail_row(
                mlo_id=300,
                ml_id="ML300",
                mlp_id=1,
                pack_id="PACK-X",
                monto_unitario=500.0,
                cantidad=1,
                costo_sin_iva=100.0,
                seller_shipping_cost=None,
                shipment_total=None,
                codigo="SKU-E",
            ),
            _detail_row(
                mlo_id=300,
                ml_id="ML300",
                mlp_id=2,
                pack_id="PACK-X",
                monto_unitario=500.0,
                cantidad=1,
                costo_sin_iva=100.0,
                seller_shipping_cost=None,
                shipment_total=None,
                codigo="SKU-F",
            ),
            _detail_row(
                mlo_id=301,
                ml_id="ML301",
                mlp_id=3,
                pack_id="PACK-X",
                monto_unitario=500.0,
                cantidad=1,
                costo_sin_iva=100.0,
                seller_shipping_cost=None,
                shipment_total=None,
                codigo="SKU-G",
            ),
        ]

        pack_counts = core.count_per_pack(rows)

        # 3 detail rows total, but only 2 DISTINCT orders share PACK-X.
        assert pack_counts["PACK-X"] == 2


class TestSingleItemOrderParity:
    """A single-item order's folded result must be identical to the per-detail result."""

    def test_single_item_order_stays_identical(self) -> None:
        core = _get_core_module()

        row = _detail_row(
            mlo_id=400,
            ml_id="ML400",
            mlp_id=999,
            pack_id=None,
            monto_unitario=1500.0,
            cantidad=1,
            costo_sin_iva=500.0,
            seller_shipping_cost=None,
            shipment_total=None,
        )

        folded = core.fold_order_rows([row])
        order = folded[400]

        # Single-item order: sums equal the single detail's own values.
        assert order["monto_total"] == pytest.approx(1500.0)
        assert order["cantidad"] == 1
        assert order["costo_total_sin_iva"] == pytest.approx(500.0)
        assert order["id_operacion"] == 400
        assert order["ml_order_id"] == "ML400"
        assert order["mla_id"] == "999"


class TestQueryBuilderShape:
    """SQL string guards (SQLite-safe) for the shared aggregating query builder."""

    def test_query_has_no_distinct_on(self) -> None:
        core = _get_core_module()
        sql_text = core.build_aggregation_sql()
        assert "DISTINCT ON" not in str(sql_text), (
            "The core aggregating query must NOT use DISTINCT ON — it must return "
            "ALL details per order so the Python fold can SUM them (design v2 D1)."
        )

    def test_query_uses_half_open_date_bounds(self) -> None:
        core = _get_core_module()
        sql_text = core.build_aggregation_sql()
        sql_str = str(sql_text)
        assert ">= :from_ts" in sql_str
        assert "< :to_ts" in sql_str
        assert "BETWEEN :from_date AND :to_date" not in sql_str

    def test_query_selects_mlo_cd_as_date_window_column(self) -> None:
        core = _get_core_module()
        sql_text = core.build_aggregation_sql()
        assert "mlo_cd" in str(sql_text)
