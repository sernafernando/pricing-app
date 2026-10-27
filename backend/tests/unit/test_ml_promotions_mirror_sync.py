"""Unit tests for local promo-mirror upsert from the ml-webhook proxy GET."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from app.services.ml_promotions_mirror_sync import _promotion_id, upsert_item_promotions_from_proxy


def test_promotion_id_falls_back_to_type_for_price_discount() -> None:
    assert _promotion_id({"type": "PRICE_DISCOUNT"}) == "PRICE_DISCOUNT"
    assert _promotion_id({"id": "P-1", "type": "DEAL"}) == "P-1"
    assert _promotion_id({}) is None


def test_upsert_returns_false_when_live_unavailable() -> None:
    with patch(
        "app.services.ml_promotions_mirror_sync.resolve_maybe_async",
        return_value=None,
    ):
        assert upsert_item_promotions_from_proxy("MLA1") is False


def test_upsert_writes_live_rows_and_finishes_missing() -> None:
    live = [
        {
            "id": "P-1",
            "type": "DEAL",
            "status": "candidate",
            "name": "OFERTA",
            "original_price": 100,
            "price": 90,
        }
    ]
    conn = MagicMock()
    begin_cm = MagicMock()
    begin_cm.__enter__.return_value = conn
    begin_cm.__exit__.return_value = False
    engine = MagicMock()
    engine.begin.return_value = begin_cm

    with (
        patch("app.services.ml_promotions_mirror_sync.resolve_maybe_async", return_value=live),
        patch("app.services.ml_promotions_mirror_sync.get_mlwebhook_engine", return_value=engine),
    ):
        assert upsert_item_promotions_from_proxy("MLA1") is True

    assert conn.execute.call_count == 3  # catalog + item + finish-stale
