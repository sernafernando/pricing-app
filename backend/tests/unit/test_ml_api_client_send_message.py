"""
ml-bot-messages-reply Phase A, PR2 — unit tests for
`MercadoLibreAPIClient.send_message`.

Mirrors `test_ml_api_client_post_answer.py`'s `MockTransport` pattern. No
live ML access — every test hits `httpx.MockTransport`.
"""

from __future__ import annotations

import asyncio

import httpx
import pytest

from app.services.ml_api_client import (
    MercadoLibreAPIClient,
    MessageSendPermanentError,
)


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


class TestSendMessage:
    def test_builds_correct_url_body_and_returns_success_body(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.path == "/messages/packs/PACK123/sellers/413658225"
            assert request.url.params.get("tag") == "post_sale"
            assert request.headers.get("Authorization") == "Bearer fake-token"
            import json

            body = json.loads(request.content)
            assert body == {
                "from": {"user_id": 413658225},
                "to": {"user_id": 999},
                "text": "hola!",
            }
            return httpx.Response(201, json={"id": "msg-1"})

        _patch_client(monkeypatch, _mock_transport(handler))
        client = _client(monkeypatch)

        result = asyncio.run(client.send_message("PACK123", 999, "hola!"))
        assert result == {"id": "msg-1"}

    def test_custom_seller_id_is_used_as_from_and_in_url(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.path == "/messages/packs/PACK1/sellers/555"
            import json

            body = json.loads(request.content)
            assert body["from"] == {"user_id": 555}
            return httpx.Response(200, json={"id": "msg-2"})

        _patch_client(monkeypatch, _mock_transport(handler))
        client = _client(monkeypatch)

        result = asyncio.run(client.send_message("PACK1", 1, "hi", seller_id=555))
        assert result == {"id": "msg-2"}

    def test_transient_5xx_returns_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(500, json={"message": "boom"})

        _patch_client(monkeypatch, _mock_transport(handler))
        client = _client(monkeypatch)
        assert asyncio.run(client.send_message("PACK1", 1, "hi")) is None

    def test_transient_429_returns_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(429, json={"message": "rate limited"})

        _patch_client(monkeypatch, _mock_transport(handler))
        client = _client(monkeypatch)
        assert asyncio.run(client.send_message("PACK1", 1, "hi")) is None

    def test_network_error_returns_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("boom", request=request)

        _patch_client(monkeypatch, _mock_transport(handler))
        client = _client(monkeypatch)
        assert asyncio.run(client.send_message("PACK1", 1, "hi")) is None

    def test_permanent_4xx_raises_message_send_permanent_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(422, json={"message": "invalid buyer"})

        _patch_client(monkeypatch, _mock_transport(handler))
        client = _client(monkeypatch)
        with pytest.raises(MessageSendPermanentError) as exc_info:
            asyncio.run(client.send_message("PACK1", 1, "hi"))
        assert exc_info.value.status_code == 422
        assert exc_info.value.pack_id == "PACK1"

    def test_non_json_400_body_raises_permanent_error_with_contract_drift_warning(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(400, content=b"not json")

        _patch_client(monkeypatch, _mock_transport(handler))
        client = _client(monkeypatch)
        with pytest.raises(MessageSendPermanentError):
            asyncio.run(client.send_message("PACK1", 1, "hi"))

    @pytest.mark.parametrize("status_code", [401, 403, 404])
    def test_401_403_404_raise_permanent_error(self, monkeypatch: pytest.MonkeyPatch, status_code: int) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(status_code, json={"message": "rejected"})

        _patch_client(monkeypatch, _mock_transport(handler))
        client = _client(monkeypatch)
        with pytest.raises(MessageSendPermanentError) as exc_info:
            asyncio.run(client.send_message("PACK1", 1, "hi"))
        assert exc_info.value.status_code == status_code
