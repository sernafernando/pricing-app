"""
context-enrichment: unit tests for `MercadoLibreAPIClient.get_item_description`.

Mirrors `get_item`'s error conventions (non-fatal, no exception leaks — 404
and any other failure both return `None`), the same MockTransport pattern
used in `test_ml_api_client_post_answer.py`.
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


class TestGetItemDescription:
    def test_returns_plain_text_on_success(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.path == "/items/MLA123/description"
            return httpx.Response(200, json={"plain_text": "Notebook con Windows 11 preinstalado."})

        _patch_client(monkeypatch, _mock_transport(handler))
        client = _client(monkeypatch)

        result = asyncio.run(client.get_item_description("MLA123"))
        assert result == "Notebook con Windows 11 preinstalado."

    def test_none_on_404(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(404, json={"message": "not found"})

        _patch_client(monkeypatch, _mock_transport(handler))
        client = _client(monkeypatch)

        assert asyncio.run(client.get_item_description("MLA404")) is None

    def test_none_on_5xx(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(500, json={"message": "boom"})

        _patch_client(monkeypatch, _mock_transport(handler))
        client = _client(monkeypatch)

        assert asyncio.run(client.get_item_description("MLA500")) is None

    def test_none_on_network_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("boom", request=request)

        _patch_client(monkeypatch, _mock_transport(handler))
        client = _client(monkeypatch)

        assert asyncio.run(client.get_item_description("MLA999")) is None

    def test_none_when_plain_text_missing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"text": "sin plain_text"})

        _patch_client(monkeypatch, _mock_transport(handler))
        client = _client(monkeypatch)

        assert asyncio.run(client.get_item_description("MLA1")) is None

    def test_none_when_plain_text_not_string(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"plain_text": None})

        _patch_client(monkeypatch, _mock_transport(handler))
        client = _client(monkeypatch)

        assert asyncio.run(client.get_item_description("MLA2")) is None
