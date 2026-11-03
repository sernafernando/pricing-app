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


def test_sku_separator_only_difference_is_mismatch() -> None:
    """Pin exact match after strip — links.normalize_sku must NOT be used here.

    Prod example: ML publishes PC-R5600G-A-8G while GBP codigo is PCR5600G-A-8G.
    Repair should treat that as drift and PUT the ERP value.
    """
    assert not sku_matches_erp("PC-R5600G-A-8G", "PCR5600G-A-8G")
    assert not sku_matches_erp("PC-R3200G-AS-16G-512", "PCR3200G-AS-16G-512")
    assert sku_matches_erp("PCR5600G-A-8G", "PCR5600G-A-8G")
