"""
Unit tests for the ML Seller Promotions WRITE methods added to
`MLWebhookClient` (ml_webhook_client.py) in PR2.

`enroll_item` / `remove_item` MUST return a STRUCTURED result
`{ok, status_code, ambiguous, body}` — never collapse to None on error,
unlike the read methods. No retry on any of these (single-shot).

Spec coverage:
  REQ-1 — enroll_item 201 -> ok=True, ambiguous=False
  REQ-2 — enroll_item 400 -> ok=False, ambiguous=False (validation, not ambiguous)
  REQ-3 — enroll_item timeout -> ok=False, ambiguous=True
  REQ-4 — enroll_item 5xx -> ok=False, ambiguous=True
  REQ-5 — remove_item 200 -> ok=True
  REQ-6 — remove_item timeout/5xx -> ambiguous=True
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


class TestEnrollItem:
    def test_201_returns_ok_not_ambiguous(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            assert request.method == "POST"
            assert request.url.path == "/api/promociones/item/MLA123456789"
            import json

            body = json.loads(request.content)
            assert body == {"promotion_id": "DEAL-1", "promotion_type": "DEAL", "deal_price": 900.0}
            return httpx.Response(201, json={"status": "candidate"})

        _patch_client(monkeypatch, _mock_transport(handler))
        client = MLWebhookClient()

        result = asyncio.run(
            client.enroll_item("MLA123456789", "DEAL-1", "DEAL", 900.0)
        )
        assert result == {"ok": True, "status_code": 201, "ambiguous": False, "body": {"status": "candidate"}}

    def test_201_with_top_deal_price_in_body(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            import json

            body = json.loads(request.content)
            assert body["top_deal_price"] == 850.0
            return httpx.Response(201, json={})

        _patch_client(monkeypatch, _mock_transport(handler))
        client = MLWebhookClient()

        result = asyncio.run(
            client.enroll_item("MLA123456789", "DEAL-1", "DEAL", 900.0, top_deal_price=850.0)
        )
        assert result["ok"] is True

    def test_400_is_ok_false_not_ambiguous(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(400, json={"message": "invalid price"})

        _patch_client(monkeypatch, _mock_transport(handler))
        client = MLWebhookClient()

        result = asyncio.run(client.enroll_item("MLA123456789", "DEAL-1", "DEAL", 900.0))
        assert result["ok"] is False
        assert result["ambiguous"] is False
        assert result["status_code"] == 400

    def test_timeout_is_ambiguous(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.TimeoutException("boom", request=request)

        _patch_client(monkeypatch, _mock_transport(handler))
        client = MLWebhookClient()

        result = asyncio.run(client.enroll_item("MLA123456789", "DEAL-1", "DEAL", 900.0))
        assert result["ok"] is False
        assert result["ambiguous"] is True
        assert result["status_code"] is None

    def test_5xx_is_ambiguous(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(500, json={"message": "boom"})

        _patch_client(monkeypatch, _mock_transport(handler))
        client = MLWebhookClient()

        result = asyncio.run(client.enroll_item("MLA123456789", "DEAL-1", "DEAL", 900.0))
        assert result["ok"] is False
        assert result["ambiguous"] is True
        assert result["status_code"] == 500

    def test_no_retry_single_call(self, monkeypatch: pytest.MonkeyPatch) -> None:
        call_count = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            call_count["n"] += 1
            raise httpx.TimeoutException("boom", request=request)

        _patch_client(monkeypatch, _mock_transport(handler))
        client = MLWebhookClient()

        asyncio.run(client.enroll_item("MLA123456789", "DEAL-1", "DEAL", 900.0))
        assert call_count["n"] == 1


class TestRemoveItem:
    def test_200_returns_ok(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            assert request.method == "DELETE"
            assert request.url.path == "/api/promociones/item/MLA123456789"
            assert request.url.params.get("promotion_type") == "DEAL"
            assert request.url.params.get("promotion_id") == "DEAL-1"
            return httpx.Response(200, json={"ok": True})

        _patch_client(monkeypatch, _mock_transport(handler))
        client = MLWebhookClient()

        result = asyncio.run(client.remove_item("MLA123456789", "DEAL", "DEAL-1"))
        assert result["ok"] is True
        assert result["ambiguous"] is False

    def test_timeout_is_ambiguous(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.TimeoutException("boom", request=request)

        _patch_client(monkeypatch, _mock_transport(handler))
        client = MLWebhookClient()

        result = asyncio.run(client.remove_item("MLA123456789", "DEAL", "DEAL-1"))
        assert result["ok"] is False
        assert result["ambiguous"] is True

    def test_5xx_is_ambiguous(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(503, json={"message": "unavailable"})

        _patch_client(monkeypatch, _mock_transport(handler))
        client = MLWebhookClient()

        result = asyncio.run(client.remove_item("MLA123456789", "DEAL", "DEAL-1"))
        assert result["ok"] is False
        assert result["ambiguous"] is True

    def test_no_retry_single_call(self, monkeypatch: pytest.MonkeyPatch) -> None:
        call_count = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            call_count["n"] += 1
            raise httpx.TimeoutException("boom", request=request)

        _patch_client(monkeypatch, _mock_transport(handler))
        client = MLWebhookClient()

        asyncio.run(client.remove_item("MLA123456789", "DEAL", "DEAL-1"))
        assert call_count["n"] == 1
