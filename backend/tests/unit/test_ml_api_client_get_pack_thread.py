"""
Phase A (PR1) — unit tests for `MercadoLibreAPIClient.get_pack_thread`
(sdd/ml-bot-messages-reply design "Gotchas": live pack-thread fetch, since
outgoing seller messages are never persisted in `ml_bot_messages`).

Mirrors `test_ml_api_client_get_message.py`'s `MockTransport` pattern.
"""

from __future__ import annotations

import asyncio

import httpx
import pytest

from app.services.ml_api_client import MercadoLibreAPIClient


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


class TestGetPackThread:
    def test_200_returns_full_response_incl_conversation_status(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.path == "/messages/packs/1234567890123456/sellers/413658225"
            assert request.url.params.get("tag") == "post_sale"
            return httpx.Response(
                200,
                json={
                    "messages": [{"id": "m1", "text": "hola", "from": {"user_id": 999}}],
                    "conversation_status": {"claim_ids": [], "shipping_id": 123},
                    "paging": {},
                },
            )

        _patch_client(monkeypatch, _mock_transport(handler))
        client = _client(monkeypatch)

        result = asyncio.run(client.get_pack_thread("1234567890123456", 413658225))
        assert result == {
            "messages": [{"id": "m1", "text": "hola", "from": {"user_id": 999}}],
            "conversation_status": {"claim_ids": [], "shipping_id": 123},
            "paging": {},
        }

    def test_404_returns_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(404, json={"message": "not found"})

        _patch_client(monkeypatch, _mock_transport(handler))
        client = _client(monkeypatch)
        assert asyncio.run(client.get_pack_thread("missing", 413658225)) is None

    def test_5xx_or_network_error_returns_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def handler_5xx(request: httpx.Request) -> httpx.Response:
            return httpx.Response(500, json={"message": "boom"})

        _patch_client(monkeypatch, _mock_transport(handler_5xx))
        client = _client(monkeypatch)
        assert asyncio.run(client.get_pack_thread("err500", 413658225)) is None

        def handler_network(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("boom", request=request)

        _patch_client(monkeypatch, _mock_transport(handler_network))
        client2 = _client(monkeypatch)
        assert asyncio.run(client2.get_pack_thread("errnet", 413658225)) is None

    def test_malformed_payload_missing_messages_key_returns_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"paging": {}})

        _patch_client(monkeypatch, _mock_transport(handler))
        client = _client(monkeypatch)
        assert asyncio.run(client.get_pack_thread("weird", 413658225)) is None
