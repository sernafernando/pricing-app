"""Unit tests for `TiendaNubeProductClient` (Slice 2 — write client).

No `@pytest.mark.asyncio` (not installed / silently skipped in CI) — every
coroutine is driven via `asyncio.run()`, matching the house convention.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from app.services.tienda_nube_product_client import TiendaNubeProductClient


def _fake_response(status_code, body=None):
    response = MagicMock()
    response.status_code = status_code
    response.json.return_value = body if body is not None else {}
    return response


class TestMissingCredentials:
    def test_missing_store_id_disables_base_url(self):
        client = TiendaNubeProductClient(store_id=None, access_token="tok")
        assert client.base_url is None

    def test_missing_access_token_disables_base_url(self):
        client = TiendaNubeProductClient(store_id="123", access_token=None)
        assert client.base_url is None

    def test_set_published_without_credentials_is_ambiguous_no_request(self):
        client = TiendaNubeProductClient(store_id=None, access_token=None)
        outcome = asyncio.run(client.set_published(999, False))
        assert outcome == {"ok": False, "status_code": None, "ambiguous": True, "body": None}


class TestAuthHeader:
    def test_header_uses_authentication_bearer_scheme(self):
        client = TiendaNubeProductClient(store_id="123", access_token="secret-token")
        assert client.headers["Authentication"] == "bearer secret-token"
        assert client.base_url == "https://api.tiendanube.com/v1/123"


class TestSetPublished:
    def test_2xx_response_is_ok(self):
        client = TiendaNubeProductClient(store_id="123", access_token="tok")
        mock_client = AsyncMock()
        mock_client.put.return_value = _fake_response(200, {"id": 999, "published": False})
        with patch("httpx.AsyncClient") as MockAsyncClient:
            MockAsyncClient.return_value.__aenter__.return_value = mock_client
            outcome = asyncio.run(client.set_published(999, False))
        assert outcome == {"ok": True, "status_code": 200, "ambiguous": False, "body": {"id": 999, "published": False}}
        mock_client.put.assert_called_once()
        call_args = mock_client.put.call_args
        assert call_args.args[0] == "https://api.tiendanube.com/v1/123/products/999"
        assert call_args.kwargs["json"] == {"published": False}

    def test_4xx_response_is_definitive_rejection(self):
        client = TiendaNubeProductClient(store_id="123", access_token="tok")
        mock_client = AsyncMock()
        mock_client.put.return_value = _fake_response(404, {"error": "not_found"})
        with patch("httpx.AsyncClient") as MockAsyncClient:
            MockAsyncClient.return_value.__aenter__.return_value = mock_client
            outcome = asyncio.run(client.set_published(999, False))
        assert outcome["ok"] is False
        assert outcome["ambiguous"] is False
        assert outcome["status_code"] == 404

    def test_5xx_response_is_ambiguous(self):
        client = TiendaNubeProductClient(store_id="123", access_token="tok")
        mock_client = AsyncMock()
        mock_client.put.return_value = _fake_response(503)
        with patch("httpx.AsyncClient") as MockAsyncClient:
            MockAsyncClient.return_value.__aenter__.return_value = mock_client
            outcome = asyncio.run(client.set_published(999, False))
        assert outcome["ok"] is False
        assert outcome["ambiguous"] is True
        assert outcome["status_code"] == 503

    def test_connection_error_is_ambiguous_never_raises(self):
        client = TiendaNubeProductClient(store_id="123", access_token="tok")
        mock_client = AsyncMock()
        mock_client.put.side_effect = Exception("connection reset")
        with patch("httpx.AsyncClient") as MockAsyncClient:
            MockAsyncClient.return_value.__aenter__.return_value = mock_client
            outcome = asyncio.run(client.set_published(999, False))
        assert outcome == {"ok": False, "status_code": None, "ambiguous": True, "body": None}
