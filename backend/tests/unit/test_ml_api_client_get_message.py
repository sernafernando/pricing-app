"""
PR1 — unit tests for `MercadoLibreAPIClient.get_message` (ml-bot postventa
messages MVP, design §Interfaces).

Mirrors `get_question`'s error conventions: raises `MessageNotFoundError` on
404 (terminal), returns None on any other failure (transient — network/5xx),
same `MockTransport` pattern as `test_ml_api_client_get_item_description.py`.
"""

from __future__ import annotations

import asyncio

import httpx
import pytest

from app.services.ml_api_client import MercadoLibreAPIClient, MessageNotFoundError


def _mock_transport(handler):
    return httpx.MockTransport(handler)


def _patch_client(monkeypatch: pytest.MonkeyPatch, transport: httpx.MockTransport) -> None:
    original_init = httpx.AsyncClient.__init__

    def patched_init(self, *args, **kwargs):
        kwargs["transport"] = transport
        original_init(self, *args, **kwargs)

    monkeypatch.setattr(httpx.AsyncClient, "__init__", patched_init)


def _client(monkeypatch: pytest.MonkeyPatch) -> MercadoLibreAPIClient:
    client = MercadoLibreAPIClient()
    monkeypatch.setattr(client, "get_access_token", lambda: _fake_token())
    return client


async def _fake_token() -> str:
    return "fake-token"


class TestGetMessage:
    def test_get_message_200_returns_json(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.path == "/messages/abc123"
            assert request.url.params.get("tag") == "post_sale"
            return httpx.Response(200, json={"id": "abc123", "text": "hola"})

        _patch_client(monkeypatch, _mock_transport(handler))
        client = _client(monkeypatch)

        result = asyncio.run(client.get_message("abc123"))
        assert result == {"id": "abc123", "text": "hola"}

    def test_get_message_404_raises_message_not_found_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(404, json={"message": "not found"})

        _patch_client(monkeypatch, _mock_transport(handler))
        client = _client(monkeypatch)

        with pytest.raises(MessageNotFoundError):
            asyncio.run(client.get_message("missing123"))

    def test_get_message_5xx_or_network_returns_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def handler_5xx(request: httpx.Request) -> httpx.Response:
            return httpx.Response(500, json={"message": "boom"})

        _patch_client(monkeypatch, _mock_transport(handler_5xx))
        client = _client(monkeypatch)
        assert asyncio.run(client.get_message("err500")) is None

        def handler_network(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("boom", request=request)

        _patch_client(monkeypatch, _mock_transport(handler_network))
        client2 = _client(monkeypatch)
        assert asyncio.run(client2.get_message("errnet")) is None
