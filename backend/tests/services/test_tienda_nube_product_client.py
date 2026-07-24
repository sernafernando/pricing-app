"""Unit tests for `TiendaNubeProductClient` (Slice 2 — write client).

No `@pytest.mark.asyncio` (not installed / silently skipped in CI) — every
coroutine is driven via `asyncio.run()`, matching the house convention.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from app.services.tienda_nube_product_client import (
    TiendaNubeProductClient,
    TnProductLookupError,
    is_publicly_reachable_url,
)


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


class TestCreateProduct:
    def test_without_credentials_is_ambiguous_no_request(self):
        client = TiendaNubeProductClient(store_id=None, access_token=None)
        outcome = asyncio.run(client.create_product({"name": {"es": "Test"}}))
        assert outcome == {"ok": False, "status_code": None, "ambiguous": True, "body": None}

    def test_2xx_response_is_ok_and_posts_to_products(self):
        client = TiendaNubeProductClient(store_id="123", access_token="tok")
        mock_client = AsyncMock()
        mock_client.post.return_value = _fake_response(201, {"id": 42})
        payload = {"name": {"es": "Test"}}
        with patch("httpx.AsyncClient") as MockAsyncClient:
            MockAsyncClient.return_value.__aenter__.return_value = mock_client
            outcome = asyncio.run(client.create_product(payload))
        assert outcome == {"ok": True, "status_code": 201, "ambiguous": False, "body": {"id": 42}}
        call_args = mock_client.post.call_args
        assert call_args.args[0] == "https://api.tiendanube.com/v1/123/products"
        assert call_args.kwargs["json"] == payload

    def test_4xx_response_is_definitive_rejection(self):
        client = TiendaNubeProductClient(store_id="123", access_token="tok")
        mock_client = AsyncMock()
        mock_client.post.return_value = _fake_response(422, {"error": "invalid"})
        with patch("httpx.AsyncClient") as MockAsyncClient:
            MockAsyncClient.return_value.__aenter__.return_value = mock_client
            outcome = asyncio.run(client.create_product({"name": {"es": "Test"}}))
        assert outcome["ok"] is False
        assert outcome["ambiguous"] is False
        assert outcome["status_code"] == 422

    def test_5xx_response_is_ambiguous(self):
        client = TiendaNubeProductClient(store_id="123", access_token="tok")
        mock_client = AsyncMock()
        mock_client.post.return_value = _fake_response(500)
        with patch("httpx.AsyncClient") as MockAsyncClient:
            MockAsyncClient.return_value.__aenter__.return_value = mock_client
            outcome = asyncio.run(client.create_product({"name": {"es": "Test"}}))
        assert outcome["ok"] is False
        assert outcome["ambiguous"] is True
        assert outcome["status_code"] == 500

    def test_connection_error_is_ambiguous_never_raises(self):
        client = TiendaNubeProductClient(store_id="123", access_token="tok")
        mock_client = AsyncMock()
        mock_client.post.side_effect = Exception("connection reset")
        with patch("httpx.AsyncClient") as MockAsyncClient:
            MockAsyncClient.return_value.__aenter__.return_value = mock_client
            outcome = asyncio.run(client.create_product({"name": {"es": "Test"}}))
        assert outcome == {"ok": False, "status_code": None, "ambiguous": True, "body": None}


class TestAddProductImage:
    def test_without_credentials_is_ambiguous_no_request(self):
        client = TiendaNubeProductClient(store_id=None, access_token=None)
        outcome = asyncio.run(client.add_product_image(42, "https://example.com/img.jpg"))
        assert outcome == {"ok": False, "status_code": None, "ambiguous": True, "body": None}

    def test_2xx_response_is_ok_and_posts_to_images_by_src(self):
        client = TiendaNubeProductClient(store_id="123", access_token="tok")
        mock_client = AsyncMock()
        mock_client.post.return_value = _fake_response(201, {"id": 1, "src": "https://example.com/img.jpg"})
        with patch("httpx.AsyncClient") as MockAsyncClient:
            MockAsyncClient.return_value.__aenter__.return_value = mock_client
            outcome = asyncio.run(client.add_product_image(42, "https://example.com/img.jpg"))
        assert outcome["ok"] is True
        assert outcome["status_code"] == 201
        call_args = mock_client.post.call_args
        assert call_args.args[0] == "https://api.tiendanube.com/v1/123/products/42/images"
        assert call_args.kwargs["json"] == {"src": "https://example.com/img.jpg"}

    def test_4xx_response_is_definitive_rejection(self):
        client = TiendaNubeProductClient(store_id="123", access_token="tok")
        mock_client = AsyncMock()
        mock_client.post.return_value = _fake_response(404, {"error": "not_found"})
        with patch("httpx.AsyncClient") as MockAsyncClient:
            MockAsyncClient.return_value.__aenter__.return_value = mock_client
            outcome = asyncio.run(client.add_product_image(42, "https://example.com/img.jpg"))
        assert outcome["ok"] is False
        assert outcome["ambiguous"] is False
        assert outcome["status_code"] == 404

    def test_5xx_response_is_ambiguous(self):
        client = TiendaNubeProductClient(store_id="123", access_token="tok")
        mock_client = AsyncMock()
        mock_client.post.return_value = _fake_response(503)
        with patch("httpx.AsyncClient") as MockAsyncClient:
            MockAsyncClient.return_value.__aenter__.return_value = mock_client
            outcome = asyncio.run(client.add_product_image(42, "https://example.com/img.jpg"))
        assert outcome["ok"] is False
        assert outcome["ambiguous"] is True
        assert outcome["status_code"] == 503

    def test_connection_error_is_ambiguous_never_raises(self):
        client = TiendaNubeProductClient(store_id="123", access_token="tok")
        mock_client = AsyncMock()
        mock_client.post.side_effect = Exception("connection reset")
        with patch("httpx.AsyncClient") as MockAsyncClient:
            MockAsyncClient.return_value.__aenter__.return_value = mock_client
            outcome = asyncio.run(client.add_product_image(42, "https://example.com/img.jpg"))
        assert outcome == {"ok": False, "status_code": None, "ambiguous": True, "body": None}


class TestIsPubliclyReachableUrl:
    """Well-formed-URL guard only — no live network call. See the module
    docstring for why a private/loopback literal IP is rejected without a
    DNS lookup or HTTP request."""

    def test_public_https_hostname_is_accepted(self):
        assert is_publicly_reachable_url("https://cdn.example.com/img1.jpg") is True

    def test_public_http_hostname_is_accepted(self):
        assert is_publicly_reachable_url("http://cdn.example.com/img1.jpg") is True

    def test_none_is_rejected(self):
        assert is_publicly_reachable_url(None) is False

    def test_empty_string_is_rejected(self):
        assert is_publicly_reachable_url("") is False

    def test_malformed_url_is_rejected(self):
        assert is_publicly_reachable_url("not-a-url") is False

    def test_ftp_scheme_is_rejected(self):
        assert is_publicly_reachable_url("ftp://example.com/img.jpg") is False

    def test_localhost_hostname_is_rejected(self):
        assert is_publicly_reachable_url("http://localhost/img.jpg") is False

    def test_loopback_literal_ip_is_rejected(self):
        assert is_publicly_reachable_url("http://127.0.0.1/img.jpg") is False

    def test_private_range_literal_ip_is_rejected(self):
        assert is_publicly_reachable_url("http://192.168.1.5/img.jpg") is False

    def test_link_local_literal_ip_is_rejected(self):
        assert is_publicly_reachable_url("http://169.254.169.254/latest/meta-data") is False

    def test_scheme_only_no_host_is_rejected(self):
        assert is_publicly_reachable_url("https://") is False


class TestGetProductBySku:
    """`get_product_by_sku` is the LIVE reconcile-via-read primitive that
    restores the reconciliation Slice 2 couldn't do (it had no live TN GET).
    Unlike the write methods, this one RAISES `TnProductLookupError` on any
    transport failure/5xx instead of swallowing it into an `ambiguous` dict
    — the orchestrator needs to distinguish "confirmed absent" (`None`) from
    "couldn't check" (an exception), and a dict return risks that
    distinction getting silently collapsed by a careless caller."""

    def test_without_credentials_raises_lookup_error(self):
        client = TiendaNubeProductClient(store_id=None, access_token=None)
        try:
            asyncio.run(client.get_product_by_sku("EAN-1"))
            assert False, "expected TnProductLookupError"
        except TnProductLookupError:
            pass

    def test_200_with_matching_product_returns_dict(self):
        client = TiendaNubeProductClient(store_id="123", access_token="tok")
        mock_client = AsyncMock()
        mock_client.get.return_value = _fake_response(200, [{"id": 999, "name": {"es": "Test"}}])
        with patch("httpx.AsyncClient") as MockAsyncClient:
            MockAsyncClient.return_value.__aenter__.return_value = mock_client
            result = asyncio.run(client.get_product_by_sku("EAN-1"))
        assert result == {"id": 999, "name": {"es": "Test"}}
        call_args = mock_client.get.call_args
        assert call_args.args[0] == "https://api.tiendanube.com/v1/123/products/sku/EAN-1"

    def test_200_with_empty_list_returns_none(self):
        client = TiendaNubeProductClient(store_id="123", access_token="tok")
        mock_client = AsyncMock()
        mock_client.get.return_value = _fake_response(200, [])
        with patch("httpx.AsyncClient") as MockAsyncClient:
            MockAsyncClient.return_value.__aenter__.return_value = mock_client
            result = asyncio.run(client.get_product_by_sku("EAN-1"))
        assert result is None

    def test_404_returns_none_confirmed_absent(self):
        client = TiendaNubeProductClient(store_id="123", access_token="tok")
        mock_client = AsyncMock()
        mock_client.get.return_value = _fake_response(404)
        with patch("httpx.AsyncClient") as MockAsyncClient:
            MockAsyncClient.return_value.__aenter__.return_value = mock_client
            result = asyncio.run(client.get_product_by_sku("EAN-1"))
        assert result is None

    def test_5xx_raises_lookup_error(self):
        client = TiendaNubeProductClient(store_id="123", access_token="tok")
        mock_client = AsyncMock()
        mock_client.get.return_value = _fake_response(503)
        with patch("httpx.AsyncClient") as MockAsyncClient:
            MockAsyncClient.return_value.__aenter__.return_value = mock_client
            try:
                asyncio.run(client.get_product_by_sku("EAN-1"))
                assert False, "expected TnProductLookupError"
            except TnProductLookupError:
                pass

    def test_connection_error_raises_lookup_error(self):
        client = TiendaNubeProductClient(store_id="123", access_token="tok")
        mock_client = AsyncMock()
        mock_client.get.side_effect = Exception("connection reset")
        with patch("httpx.AsyncClient") as MockAsyncClient:
            MockAsyncClient.return_value.__aenter__.return_value = mock_client
            try:
                asyncio.run(client.get_product_by_sku("EAN-1"))
                assert False, "expected TnProductLookupError"
            except TnProductLookupError:
                pass


class TestFetchCategories:
    """Read-only `GET /categories` (sub-slice 3b — feeds the embedding sync)."""

    def test_missing_credentials_returns_none_no_request(self):
        client = TiendaNubeProductClient(store_id=None, access_token=None)
        result = asyncio.run(client.fetch_categories())
        assert result is None

    def test_2xx_response_returns_parsed_list(self):
        client = TiendaNubeProductClient(store_id="123", access_token="tok")
        categories = [
            {"id": 1, "name": {"es": "Electrónica"}, "parent": None},
            {"id": 2, "name": {"es": "Celulares"}, "parent": 1},
        ]
        mock_client = AsyncMock()
        mock_client.get.return_value = _fake_response(200, categories)
        with patch("httpx.AsyncClient") as MockAsyncClient:
            MockAsyncClient.return_value.__aenter__.return_value = mock_client
            result = asyncio.run(client.fetch_categories())
        assert result == categories
        mock_client.get.assert_called_once()
        call_args = mock_client.get.call_args
        assert call_args.args[0] == "https://api.tiendanube.com/v1/123/categories"

    def test_4xx_response_returns_none(self):
        client = TiendaNubeProductClient(store_id="123", access_token="tok")
        mock_client = AsyncMock()
        mock_client.get.return_value = _fake_response(404, {"error": "not_found"})
        with patch("httpx.AsyncClient") as MockAsyncClient:
            MockAsyncClient.return_value.__aenter__.return_value = mock_client
            result = asyncio.run(client.fetch_categories())
        assert result is None

    def test_5xx_response_returns_none(self):
        client = TiendaNubeProductClient(store_id="123", access_token="tok")
        mock_client = AsyncMock()
        mock_client.get.return_value = _fake_response(503)
        with patch("httpx.AsyncClient") as MockAsyncClient:
            MockAsyncClient.return_value.__aenter__.return_value = mock_client
            result = asyncio.run(client.fetch_categories())
        assert result is None

    def test_connection_error_returns_none_never_raises(self):
        client = TiendaNubeProductClient(store_id="123", access_token="tok")
        mock_client = AsyncMock()
        mock_client.get.side_effect = Exception("connection reset")
        with patch("httpx.AsyncClient") as MockAsyncClient:
            MockAsyncClient.return_value.__aenter__.return_value = mock_client
            result = asyncio.run(client.fetch_categories())
        assert result is None

    def test_non_list_body_returns_none(self):
        client = TiendaNubeProductClient(store_id="123", access_token="tok")
        mock_client = AsyncMock()
        mock_client.get.return_value = _fake_response(200, {"unexpected": "shape"})
        with patch("httpx.AsyncClient") as MockAsyncClient:
            MockAsyncClient.return_value.__aenter__.return_value = mock_client
            result = asyncio.run(client.fetch_categories())
        assert result is None
