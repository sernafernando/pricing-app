"""
Failing-first unit tests for the shared upsert-payload/upsert helpers in
`app.scripts._tplink_metricas_core`, slice 2 of tplink-metricas-dual-key-dedup.

Covers:
  - `build_upsert_payload()` maps a folded per-order dict to the exact
    `TplinkVentaMetrica` column payload (types, rounding, fecha_calculo).
  - `upsert_metrica()` inserts when no existing row, updates when found,
    keyed by `id_operacion` (mlo_id) — never touches commit/rollback.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

import pytest


def _get_core_module():
    import app.scripts._tplink_metricas_core as core

    return core


def _folded_row(**overrides) -> dict:
    base = {
        "id_operacion": 100,
        "ml_order_id": "ML100",
        "mla_id": "111",
        "pack_id": "PACK-A",
        "item_id": 1,
        "codigo": "SKU-A",
        "descripcion": "PRODUCTO 1",
        "marca": "TP-LINK",
        "categoria": "REDES",
        "subcategoria": "ROUTERS",
        "fecha_venta": datetime(2026, 7, 1, 10, 0, 0),
        "cantidad": 2.0,
        "monto_unitario": 1000.0,
        "monto_total": 2000.0,
        "costo_unitario_sin_iva": 350.123456,
        "costo_total_sin_iva": 700.0,
        "comision_ml": 120.5,
        "costo_envio_ml": 50.25,
        "tipo_logistica": "self_service",
        "monto_limpio": 1500.0,
        "ganancia": 800.0,
        "markup_porcentaje": 114.28,
        "offset_flex": 500.0,
        "mlp_official_store_id": 2645,
        "cotizacion_dolar": 1234.5,
        "moneda_costo": "USD",
        "tipo_lista": "gold_special",
        "porcentaje_comision_ml": 12.0,
        "prli_id": 4,
        "costo_total": 750.25,
    }
    base.update(overrides)
    return base


class TestBuildUpsertPayload:
    def test_maps_keys_types_and_rounding(self) -> None:
        core = _get_core_module()

        payload = core.build_upsert_payload(_folded_row())

        assert payload["id_operacion"] == 100
        assert payload["ml_order_id"] == "ML100"
        assert payload["mla_id"] == "111"
        assert payload["cantidad"] == 2
        assert isinstance(payload["cantidad"], int)
        assert payload["monto_total"] == Decimal("2000.00")
        assert isinstance(payload["monto_total"], Decimal)
        # costo_unitario_sin_iva keeps 6 decimals (model column is Numeric(18, 6))
        assert payload["costo_unitario_sin_iva"] == Decimal("350.123456")
        assert payload["comision_ml"] == Decimal("120.50")
        assert payload["offset_flex"] == Decimal("500.00")
        assert payload["fecha_calculo"] == date.today()
        assert payload["mlp_official_store_id"] == 2645

    def test_none_numeric_fields_default_to_zero(self) -> None:
        core = _get_core_module()

        payload = core.build_upsert_payload(
            _folded_row(comision_ml=None, offset_flex=None, costo_envio_ml=None)
        )

        assert payload["comision_ml"] == Decimal("0")
        assert payload["offset_flex"] == Decimal("0")
        assert payload["costo_envio_ml"] == Decimal("0")


class _FakeQuery:
    def __init__(self, existing) -> None:
        self._existing = existing

    def filter(self, *args, **kwargs) -> "_FakeQuery":
        return self

    def first(self):
        return self._existing


class _FakeDbSession:
    def __init__(self, existing=None) -> None:
        self._existing = existing
        self.added: list = []

    def query(self, *args, **kwargs) -> _FakeQuery:
        return _FakeQuery(self._existing)

    def add(self, obj) -> None:
        self.added.append(obj)


class _FakeExistente:
    def __init__(self, id_operacion) -> None:
        self.id_operacion = id_operacion


class TestUpsertMetrica:
    def test_inserts_when_no_existing_row(self) -> None:
        core = _get_core_module()
        db = _FakeDbSession(existing=None)
        payload = core.build_upsert_payload(_folded_row())

        result = core.upsert_metrica(db, payload)

        assert result == "insertado"
        assert len(db.added) == 1
        assert db.added[0].id_operacion == 100

    def test_updates_when_existing_row_found(self) -> None:
        core = _get_core_module()
        existente = _FakeExistente(id_operacion=100)
        db = _FakeDbSession(existing=existente)
        payload = core.build_upsert_payload(_folded_row(monto_total=9999.0))

        result = core.upsert_metrica(db, payload)

        assert result == "actualizado"
        assert len(db.added) == 0
        assert existente.monto_total == Decimal("9999.00")
        # id_operacion itself must never be overwritten by the loop.
        assert existente.id_operacion == 100
