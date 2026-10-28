"""Installments token / bucket synthesis for catalog competition."""

from __future__ import annotations

from app.services.ml_catalog_competition_service import (
    bucket_key_for_web_pricelist,
    competitor_bucket_key,
    normalize_installments_token,
)


def test_normalize_bare_int_installments() -> None:
    assert normalize_installments_token(6) == "6"
    assert normalize_installments_token("3") == "3"
    assert normalize_installments_token(None) == "0"
    assert normalize_installments_token({"quantity": 12, "rate": 0}) == "12"
    assert normalize_installments_token({"quantity": 6, "rate": 1.5}) == "6c"


def test_competitor_bucket_recomputes_from_bare_installments() -> None:
    key = competitor_bucket_key({"listing_type_id": "gold_pro", "installments": 6, "price_ars": 100.0})
    assert key == "gold_pro|6"


def test_bucket_key_for_web_pricelist_cuotas() -> None:
    assert bucket_key_for_web_pricelist(4) == "gold_special|0"
    assert bucket_key_for_web_pricelist(14) == "gold_pro|6"
    assert bucket_key_for_web_pricelist(17) == "gold_pro|3"
