"""
Failing-first unit tests for JD-001 BLOCKER (review ledger
sdd/tplink-metricas-dual-key-dedup/review-ledger-slice2):

`build_upsert_payload()` previously omitted 6 `TplinkVentaMetrica` columns
that the pre-slice-2 legacy backfill job populated: `cotizacion_dolar`,
`moneda_costo`, `tipo_lista`, `porcentaje_comision_ml`, `prli_id`,
`costo_total`. Because `upsert_metrica()` only writes payload keys, new
inserts NULLed these and existing rows kept permanently-stale values.

This test seeds a multi-detail order (via the aggregating CTE's per-detail
row shape) and asserts:
  - `fold_order_rows()`'s folded dict contains all 6 fields with
    correctly-derived, non-None values.
  - `build_upsert_payload()` maps them onto the payload with correct types.
  - `costo_total` = `costo_total_sin_iva` + `costo_envio_ml` (cost INCLUDING
    the once-per-order shipping — distinct from `costo_total_sin_iva`).
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from types import SimpleNamespace

import pytest


def _get_core_module():
    import app.scripts._tplink_metricas_core as core

    return core


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
    pricelist_id: int | None = 4,
    envio_producto: float | None = None,
    item_id: int = 1,
    mlod_id: int | None = 1,
    moneda_costo: str = "USD",
    cambio_momento: float = 1234.5,
    tipo_lista: str = "gold_special",
) -> SimpleNamespace:
    """Builds a synthetic per-detail row matching the aggregating CTE's
    projection, INCLUDING the new moneda_costo/cambio_momento/tipo_lista
    columns added for JD-001."""
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
        moneda_costo=moneda_costo,
        cambio_momento=cambio_momento,
        tipo_lista=tipo_lista,
    )


class TestQueryBuilderSelectsNewColumns:
    """SQL string guards (SQLite-safe) for the 3 new SELECT columns."""

    def test_query_selects_moneda_costo(self) -> None:
        core = _get_core_module()
        assert "moneda_costo" in str(core.build_aggregation_sql())

    def test_query_selects_cambio_momento(self) -> None:
        core = _get_core_module()
        assert "cambio_momento" in str(core.build_aggregation_sql())

    def test_query_selects_tipo_lista(self) -> None:
        core = _get_core_module()
        assert "mlp_listing_type_id" in str(core.build_aggregation_sql())


class TestFoldedRowIncludesPreviouslyMissingFields:
    def test_folded_row_has_all_six_fields_non_none(self) -> None:
        core = _get_core_module()

        rows = [
            _detail_row(
                mlo_id=100,
                ml_id="ML100",
                mlp_id=111,
                item_id=1,
                mlod_id=1,
                monto_unitario=1000.0,
                costo_sin_iva=400.0,
                seller_shipping_cost=200.0,
                shipment_total=2000.0,
            ),
            _detail_row(
                mlo_id=100,
                ml_id="ML100",
                mlp_id=222,
                item_id=2,
                mlod_id=2,
                monto_unitario=500.0,
                costo_sin_iva=300.0,
                seller_shipping_cost=200.0,
                shipment_total=2000.0,
            ),
        ]

        folded = core.fold_order_rows(rows)
        order = folded[100]

        for key in (
            "cotizacion_dolar",
            "moneda_costo",
            "tipo_lista",
            "porcentaje_comision_ml",
            "prli_id",
            "costo_total",
        ):
            assert key in order, f"folded row missing key: {key}"
            assert order[key] is not None, f"folded row key {key} is None"

        # Representative-detail values (mlod_id=1, the min).
        assert order["moneda_costo"] == "USD"
        assert order["cotizacion_dolar"] == pytest.approx(1234.5)
        assert order["tipo_lista"] == "gold_special"
        assert order["prli_id"] == 4

        # costo_total = costo_total_sin_iva + costo_envio_ml (INCLUDES shipping,
        # distinct from costo_total_sin_iva).
        assert order["costo_total"] == pytest.approx(order["costo_total_sin_iva"] + order["costo_envio_ml"])
        assert order["costo_total"] != pytest.approx(order["costo_total_sin_iva"])


class TestBuildUpsertPayloadMapsNewFields:
    def test_payload_contains_all_six_keys_with_correct_types(self) -> None:
        core = _get_core_module()

        rows = [
            _detail_row(mlo_id=200, ml_id="ML200", mlp_id=1, mlod_id=1),
        ]
        folded = core.fold_order_rows(rows)
        payload = core.build_upsert_payload(folded[200])

        assert payload["cotizacion_dolar"] == Decimal("1234.5000")
        assert payload["moneda_costo"] == "USD"
        assert payload["tipo_lista"] == "gold_special"
        assert isinstance(payload["porcentaje_comision_ml"], Decimal)
        assert isinstance(payload["prli_id"], int)
        assert payload["prli_id"] == 4
        assert isinstance(payload["costo_total"], Decimal)
        assert payload["costo_total"] == payload["costo_total_sin_iva"] + payload["costo_envio_ml"]

    def test_missing_publication_falls_back_to_prli_id_4_and_tipo_lista_unknown(self) -> None:
        core = _get_core_module()

        rows = [
            _detail_row(
                mlo_id=201,
                ml_id="ML201",
                mlp_id=None,
                mlod_id=1,
                pricelist_id=None,
                tipo_lista=None,
            ),
        ]
        folded = core.fold_order_rows(rows)
        payload = core.build_upsert_payload(folded[201])

        assert payload["prli_id"] == 4
        assert payload["tipo_lista"] == "unknown"
