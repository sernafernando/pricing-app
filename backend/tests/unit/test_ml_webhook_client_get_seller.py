"""RED/GREEN — `get_seller` for catalog-competition reputation enrich."""

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


SELLER_PAYLOAD = {
    "id": 111,
    "nickname": "SELLER_A",
    "seller_reputation": {
        "level_id": "5_green",
        "power_seller_status": "platinum",
    },
}


class TestGetSeller:
    def test_success_returns_user_payload(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.path == "/api/ml/render"
            assert request.url.params["resource"] == "/users/111"
            assert request.url.params["format"] == "json"
            return httpx.Response(200, json=SELLER_PAYLOAD)

        _patch_client(monkeypatch, httpx.MockTransport(handler))
        client = MLWebhookClient()

        result = asyncio.run(client.get_seller(111))
        assert result == SELLER_PAYLOAD

    def test_empty_seller_id_returns_none_without_http(self, monkeypatch: pytest.MonkeyPatch) -> None:
        calls = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(str(request.url))
            return httpx.Response(200, json=SELLER_PAYLOAD)

        _patch_client(monkeypatch, httpx.MockTransport(handler))
        client = MLWebhookClient()

        assert asyncio.run(client.get_seller(None)) is None
        assert asyncio.run(client.get_seller("")) is None
        assert calls == []

    def test_404_and_timeout_return_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def handler_404(request: httpx.Request) -> httpx.Response:
            return httpx.Response(404, json={"message": "not found"})

        _patch_client(monkeypatch, httpx.MockTransport(handler_404))
        assert asyncio.run(MLWebhookClient().get_seller(999)) is None

        def handler_timeout(request: httpx.Request) -> httpx.Response:
            raise httpx.TimeoutException("boom", request=request)

        _patch_client(monkeypatch, httpx.MockTransport(handler_timeout))
        assert asyncio.run(MLWebhookClient().get_seller(999)) is None
