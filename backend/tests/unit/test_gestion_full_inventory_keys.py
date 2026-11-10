"""Unit tests for Gestión Full inventory / Código ML key helpers."""

from __future__ import annotations

from app.services.gestion_full.inventory_keys import (
    excel_codigo_ml,
    is_synthetic_inventory_id,
    package_inventory_id,
    synthetic_inventory_id,
    user_product_id_from_synthetic,
)


def test_synthetic_roundtrip() -> None:
    key = synthetic_inventory_id("MLAU4380845993")
    assert key == "NOINV:MLAU4380845993"
    assert is_synthetic_inventory_id(key) is True
    assert user_product_id_from_synthetic(key) == "MLAU4380845993"
    assert excel_codigo_ml(key) == ""


def test_package_inventory_id_prefers_real_codigo() -> None:
    assert package_inventory_id("ABC123", user_product_id="MLAU1") == "ABC123"
    assert package_inventory_id(None, user_product_id="MLAU1") == "NOINV:MLAU1"
    assert excel_codigo_ml("ABC123") == "ABC123"
    assert excel_codigo_ml(None) == ""
