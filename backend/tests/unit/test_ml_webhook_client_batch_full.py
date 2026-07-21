"""
RED/GREEN — `get_items_full_batch` (productos-catalog-family-tree PR1b).

Mirrors `get_items_batch`'s parallel-fetch pattern but hits `get_item_full`
(the `/render` full item, not `/preview`) and extracts only the link
fields this feature persists: `family_id`, `user_product_id`,
`inventory_id`, `catalog_listing`, `catalog_product_id`, `item_relations`.

Spec coverage:
  REQ-1 — success returns {mla: extracted_link_fields} for every found item.
  REQ-2 — an MLA the proxy fails/404s for is simply ABSENT from the result
          dict — no crash, no partial entry (graceful degradation).
  REQ-3 — empty input -> empty dict, no HTTP calls.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from app.services.ml_webhook_client import MLWebhookClient


FULL_ITEM_A = {
    "id": "MLA_A",
    "family_id": "FAM1",
    "user_product_id": "UP1",
    "inventory_id": "INV1",
    "catalog_listing": True,
    "catalog_product_id": "CP1",
    "item_relations": [{"id": "MLA_B", "stock_relation": 1}],
}

FULL_ITEM_C = {
    "id": "MLA_C",
    "family_id": None,
    "user_product_id": None,
    "inventory_id": None,
    "catalog_listing": False,
    "catalog_product_id": None,
    "item_relations": [],
}


class TestGetItemsFullBatch:
    def test_empty_input_returns_empty_dict_no_calls(self) -> None:
        client = MLWebhookClient()
        with patch.object(client, "get_item_full", new_callable=AsyncMock) as mock_full:
            result = asyncio.run(client.get_items_full_batch([]))

        assert result == {}
        mock_full.assert_not_called()

    def test_success_extracts_link_fields_per_mla(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(asyncio, "sleep", AsyncMock())
        client = MLWebhookClient()

        async def fake_get_item_full(mla_id: str):
            return {"MLA_A": FULL_ITEM_A, "MLA_C": FULL_ITEM_C}.get(mla_id)

        with patch.object(client, "get_item_full", side_effect=fake_get_item_full):
            result = asyncio.run(client.get_items_full_batch(["MLA_A", "MLA_C"]))

        assert set(result.keys()) == {"MLA_A", "MLA_C"}
        assert result["MLA_A"]["family_id"] == "FAM1"
        assert result["MLA_A"]["item_relations"] == [{"id": "MLA_B", "stock_relation": 1}]
        assert result["MLA_C"]["catalog_listing"] is False

    def test_proxy_down_for_one_mla_is_skipped_not_crashed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(asyncio, "sleep", AsyncMock())
        client = MLWebhookClient()

        async def fake_get_item_full(mla_id: str):
            if mla_id == "MLA_DOWN":
                return None
            return FULL_ITEM_A

        with patch.object(client, "get_item_full", side_effect=fake_get_item_full):
            result = asyncio.run(client.get_items_full_batch(["MLA_A", "MLA_DOWN"]))

        assert "MLA_DOWN" not in result
        assert "MLA_A" in result

    def test_batches_of_50_with_pause_between_batches(self, monkeypatch: pytest.MonkeyPatch) -> None:
        sleep_mock = AsyncMock()
        monkeypatch.setattr(asyncio, "sleep", sleep_mock)
        client = MLWebhookClient()

        mlas = [f"MLA_{i}" for i in range(120)]

        async def fake_get_item_full(mla_id: str):
            return FULL_ITEM_C

        with patch.object(client, "get_item_full", side_effect=fake_get_item_full):
            result = asyncio.run(client.get_items_full_batch(mlas))

        assert len(result) == 120
        # 120 items in batches of 50 -> 3 batches -> pause after each.
        assert sleep_mock.await_count == 3
