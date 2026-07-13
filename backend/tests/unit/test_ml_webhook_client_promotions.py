"""
Unit tests for the ML Seller Promotions READ methods added to
`MLWebhookClient` (ml_webhook_client.py).

PR1 scope — read-only: `get_promotions`, `get_promotion_items`,
`get_item_promotions`. Write methods (enroll/remove) are PR2.

Mirrors the MockTransport pattern used elsewhere for httpx clients
(test_ml_api_client_get_message.py), adapted to MLWebhookClient's
per-call `httpx.AsyncClient` (no token/auth wrapper).

Spec coverage:
  REQ-1 — get_promotions() success returns parsed JSON list/dict
  REQ-2 — get_promotions() timeout/error returns None (read convention: no retry)
  REQ-3 — get_promotion_items(promotion_id, promotion_type) requires
          promotion_type before calling the proxy
  REQ-4 — get_promotion_items first page (no search_after) success
  REQ-5 — get_promotion_items subsequent page (search_after passed through)
  REQ-6 — get_promotion_items timeout/error returns None
  REQ-7 — get_item_promotions(mla_id) success + timeout/error returns None
"""

from __future__ import annotations

import asyncio

import httpx
import pytest

from app.services.ml_webhook_client import MLWebhookClient


def _mock_transport(handler):
    return httpx.MockTransport(handler)


def _patch_client(monkeypatch: pytest.MonkeyPatch, transport: httpx.MockTransport) -> None:
    original_init = httpx.AsyncClient.__init__

    def patched_init(self, *args, **kwargs):
        kwargs["transport"] = transport
        original_init(self, *args, **kwargs)

    monkeypatch.setattr(httpx.AsyncClient, "__init__", patched_init)


class TestGetPromotions:
    def test_success_returns_json(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.path == "/api/promociones"
            return httpx.Response(200, json=[{"promotion_id": "SELLER_CAMPAIGN"}])

        _patch_client(monkeypatch, _mock_transport(handler))
        client = MLWebhookClient()

        result = asyncio.run(client.get_promotions())
        assert result == [{"promotion_id": "SELLER_CAMPAIGN"}]

    def test_timeout_returns_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.TimeoutException("boom", request=request)

        _patch_client(monkeypatch, _mock_transport(handler))
        client = MLWebhookClient()

        assert asyncio.run(client.get_promotions()) is None

    def test_5xx_returns_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(500, json={"message": "boom"})

        _patch_client(monkeypatch, _mock_transport(handler))
        client = MLWebhookClient()

        assert asyncio.run(client.get_promotions()) is None


class TestGetPromotionItems:
    def test_missing_promotion_type_raises_before_call(self) -> None:
        client = MLWebhookClient()

        async def _call():
            return await client.get_promotion_items("DEAL-1", promotion_type=None)

        with pytest.raises(ValueError):
            asyncio.run(_call())

    def test_first_page_no_search_after(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.path == "/api/promociones/DEAL-1/items"
            assert request.url.params.get("promotion_type") == "DEAL"
            assert request.url.params.get("searchAfter") is None
            return httpx.Response(
                200,
                json={"items": [{"mla": "MLA111"}], "paging": {"searchAfter": "cursor-1"}},
            )

        _patch_client(monkeypatch, _mock_transport(handler))
        client = MLWebhookClient()

        result = asyncio.run(client.get_promotion_items("DEAL-1", promotion_type="DEAL"))
        assert result == {"items": [{"mla": "MLA111"}], "paging": {"searchAfter": "cursor-1"}}

    def test_subsequent_page_passes_search_after(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.params.get("searchAfter") == "cursor-1"
            return httpx.Response(
                200,
                json={"items": [{"mla": "MLA222"}], "paging": {"searchAfter": None}},
            )

        _patch_client(monkeypatch, _mock_transport(handler))
        client = MLWebhookClient()

        result = asyncio.run(
            client.get_promotion_items("DEAL-1", promotion_type="DEAL", search_after="cursor-1")
        )
        assert result["items"] == [{"mla": "MLA222"}]
        assert result["paging"]["searchAfter"] is None

    def test_timeout_returns_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.TimeoutException("boom", request=request)

        _patch_client(monkeypatch, _mock_transport(handler))
        client = MLWebhookClient()

        result = asyncio.run(client.get_promotion_items("DEAL-1", promotion_type="DEAL"))
        assert result is None


class TestGetItemPromotions:
    def test_success_returns_json(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.path == "/api/promociones/item/MLA123456789"
            return httpx.Response(200, json={"mla": "MLA123456789", "promotions": []})

        _patch_client(monkeypatch, _mock_transport(handler))
        client = MLWebhookClient()

        result = asyncio.run(client.get_item_promotions("MLA123456789"))
        assert result == {"mla": "MLA123456789", "promotions": []}

    def test_timeout_returns_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.TimeoutException("boom", request=request)

        _patch_client(monkeypatch, _mock_transport(handler))
        client = MLWebhookClient()

        assert asyncio.run(client.get_item_promotions("MLA123456789")) is None

    def test_404_returns_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(404, json={"message": "not found"})

        _patch_client(monkeypatch, _mock_transport(handler))
        client = MLWebhookClient()

        assert asyncio.run(client.get_item_promotions("MLA000000000")) is None
