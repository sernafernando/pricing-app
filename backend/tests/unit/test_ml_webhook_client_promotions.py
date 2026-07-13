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
  REQ-4 — get_promotion_items single page (no cursor) success
  REQ-5 — get_promotion_items auto-loops searchAfter across pages,
          aggregating all items, and terminates on empty/unchanged cursor
          (PR2/T3-adjunct fix — reliability finding R3-003)
  REQ-6 — get_promotion_items timeout/error returns None
  REQ-7 — get_item_promotions(mla_id) success + timeout/error returns None
"""

from __future__ import annotations

import asyncio
from typing import Optional

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
    """get_promotion_items now auto-loops on paging.searchAfter (PR2/T3-adjunct
    fix — reliability finding R3-003) and returns ALL items aggregated,
    instead of a single raw page. Guards against an infinite loop by
    stopping when the cursor is empty/None or does not change."""

    def test_missing_promotion_type_raises_before_call(self) -> None:
        client = MLWebhookClient()

        async def _call():
            return await client.get_promotion_items("DEAL-1", promotion_type=None)

        with pytest.raises(ValueError):
            asyncio.run(_call())

    def test_single_page_no_cursor(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.path == "/api/promociones/DEAL-1/items"
            assert request.url.params.get("promotion_type") == "DEAL"
            assert request.url.params.get("searchAfter") is None
            return httpx.Response(
                200,
                json={"items": [{"mla": "MLA111"}], "paging": {"searchAfter": None}},
            )

        _patch_client(monkeypatch, _mock_transport(handler))
        client = MLWebhookClient()

        result = asyncio.run(client.get_promotion_items("DEAL-1", promotion_type="DEAL"))
        assert result == {"items": [{"mla": "MLA111"}], "count": 1}

    def test_multi_page_aggregates_all_items(self, monkeypatch: pytest.MonkeyPatch) -> None:
        calls: list[Optional[str]] = []

        def handler(request: httpx.Request) -> httpx.Response:
            cursor = request.url.params.get("searchAfter")
            calls.append(cursor)
            if cursor is None:
                return httpx.Response(
                    200,
                    json={"items": [{"mla": "MLA111"}], "paging": {"searchAfter": "cursor-1"}},
                )
            if cursor == "cursor-1":
                return httpx.Response(
                    200,
                    json={"items": [{"mla": "MLA222"}], "paging": {"searchAfter": "cursor-2"}},
                )
            return httpx.Response(
                200,
                json={"items": [{"mla": "MLA333"}], "paging": {"searchAfter": None}},
            )

        _patch_client(monkeypatch, _mock_transport(handler))
        client = MLWebhookClient()

        result = asyncio.run(client.get_promotion_items("DEAL-1", promotion_type="DEAL"))
        assert result["count"] == 3
        assert [item["mla"] for item in result["items"]] == ["MLA111", "MLA222", "MLA333"]
        assert calls == [None, "cursor-1", "cursor-2"]

    def test_pagination_terminates_when_cursor_unchanged(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Guards against an infinite loop if the proxy misbehaves and repeats
        the same cursor instead of returning null/empty."""

        def handler(request: httpx.Request) -> httpx.Response:
            cursor = request.url.params.get("searchAfter")
            if cursor is None:
                return httpx.Response(
                    200,
                    json={"items": [{"mla": "MLA111"}], "paging": {"searchAfter": "cursor-1"}},
                )
            return httpx.Response(
                200,
                json={"items": [{"mla": "MLA222"}], "paging": {"searchAfter": "cursor-1"}},
            )

        _patch_client(monkeypatch, _mock_transport(handler))
        client = MLWebhookClient()

        result = asyncio.run(client.get_promotion_items("DEAL-1", promotion_type="DEAL"))
        assert result["count"] == 2

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
