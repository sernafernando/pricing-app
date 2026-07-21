"""
RED/GREEN — revived `get_item_full` (productos-catalog-family-tree PR1b).

`get_item_full` was previously dead: it fetched `/api/ml/render` but
discarded the response and re-fetched `/api/ml/preview` instead (which
lacks the link fields this feature needs: `family_id`, `item_relations`,
`user_product_id`, `inventory_id`, `catalog_listing`, `catalog_product_id`).

Spec coverage:
  REQ-1 — success returns the FULL `/render` payload (not the preview),
          including link fields.
  REQ-2 — 404 -> None.
  REQ-3 — any other error/timeout -> None (never raises, mirrors the
          existing error-swallow shape of every other read method).
"""

from __future__ import annotations

import asyncio

import httpx
import pytest

from app.services.ml_webhook_client import MLWebhookClient


def _patch_client(monkeypatch: pytest.MonkeyPatch, transport: httpx.MockTransport) -> None:
    original_init = httpx.AsyncClient.__init__

    def patched_init(self, *args, **kwargs):
        kwargs["transport"] = transport
        original_init(self, *args, **kwargs)

    monkeypatch.setattr(httpx.AsyncClient, "__init__", patched_init)


FULL_ITEM_PAYLOAD = {
    "id": "MLA2361127120",
    "family_id": "MLA12345",
    "user_product_id": "UP123",
    "inventory_id": "INV456",
    "catalog_listing": True,
    "catalog_product_id": "CATPROD789",
    "item_relations": [{"id": "MLA999", "stock_relation": 1}],
}


class TestGetItemFull:
    def test_success_returns_full_render_payload_not_preview(self, monkeypatch: pytest.MonkeyPatch) -> None:
        calls: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(request.url.path)
            assert request.url.path == "/api/ml/render"
            assert request.url.params["resource"] == "/items/MLA2361127120"
            assert request.url.params["format"] == "json"
            return httpx.Response(200, json=FULL_ITEM_PAYLOAD)

        _patch_client(monkeypatch, httpx.MockTransport(handler))
        client = MLWebhookClient()

        result = asyncio.run(client.get_item_full("MLA2361127120"))

        assert result == FULL_ITEM_PAYLOAD
        assert result["family_id"] == "MLA12345"
        assert result["item_relations"] == [{"id": "MLA999", "stock_relation": 1}]
        # Only one call — the /preview fallback fetch must be gone.
        assert calls == ["/api/ml/render"]

    def test_404_returns_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(404, json={"message": "not found"})

        _patch_client(monkeypatch, httpx.MockTransport(handler))
        client = MLWebhookClient()

        assert asyncio.run(client.get_item_full("MLA_MISSING")) is None

    def test_timeout_returns_none_never_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.TimeoutException("boom", request=request)

        _patch_client(monkeypatch, httpx.MockTransport(handler))
        client = MLWebhookClient()

        assert asyncio.run(client.get_item_full("MLA_TIMEOUT")) is None

    def test_5xx_returns_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(500, json={"message": "boom"})

        _patch_client(monkeypatch, httpx.MockTransport(handler))
        client = MLWebhookClient()

        assert asyncio.run(client.get_item_full("MLA_5XX")) is None
