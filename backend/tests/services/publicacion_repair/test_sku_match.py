"""Pure SKU vs ERP codigo matching for sku repair."""

from __future__ import annotations

from app.services.publicacion_repair.sku import normalize_sku, sku_matches_erp


def test_sku_matches_erp_exact() -> None:
    assert sku_matches_erp("840006603337", "840006603337")


def test_sku_matches_erp_strips_whitespace() -> None:
    assert sku_matches_erp(" 840006603337 ", "840006603337")


def test_sku_mismatch_or_null() -> None:
    assert not sku_matches_erp(None, "840006603337")
    assert not sku_matches_erp("840006603337", None)
    assert not sku_matches_erp("111", "840006603337")
    assert normalize_sku("  ") is None
