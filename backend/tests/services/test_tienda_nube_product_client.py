"""Unit tests for `TiendaNubeProductClient` (Slice 2 — write client).

No `@pytest.mark.asyncio` (not installed / silently skipped in CI) — every
coroutine is driven via `asyncio.run()`, matching the house convention.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.tienda_nube_product_client import (
    CATEGORIES_MAX_PAGES,
    CATEGORIES_PAGE_SIZE,
    TiendaNubeProductClient,
    TnProductLookupError,
    TnRateLimited,
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

    def test_429_response_raises_rate_limited_not_classified_as_rejection(self):
        """Defect fix: a 429 must raise `TnRateLimited` here too, exactly
        like `create_product` — NOT fall through to `_classify_write_response`
        and be misclassified as a definitive 4xx rejection (which is what let
        `unpublish_product` report `rejected_by_proxy` for a 429 that never
        even attempted the write)."""
        client = TiendaNubeProductClient(store_id="123", access_token="tok")
        mock_client = AsyncMock()
        mock_client.put.return_value = _fake_response(429)
        mock_client.put.return_value.headers = {"Retry-After": "3"}
        with patch("httpx.AsyncClient") as MockAsyncClient:
            MockAsyncClient.return_value.__aenter__.return_value = mock_client
            with pytest.raises(TnRateLimited) as exc_info:
                asyncio.run(client.set_published(999, False))
        assert exc_info.value.retry_after == 3.0


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

    def test_429_response_raises_rate_limited_not_classified_as_rejection(self):
        """Defect fix: same uniform 429 handling as `set_published`/
        `create_product` — a rate-limited image POST must not be classified
        as a definitive rejection (which is what let `publish_product`
        silently drop the image and only log a warning)."""
        client = TiendaNubeProductClient(store_id="123", access_token="tok")
        mock_client = AsyncMock()
        mock_client.post.return_value = _fake_response(429)
        mock_client.post.return_value.headers = {"Retry-After": "5"}
        with patch("httpx.AsyncClient") as MockAsyncClient:
            MockAsyncClient.return_value.__aenter__.return_value = mock_client
            with pytest.raises(TnRateLimited) as exc_info:
                asyncio.run(client.add_product_image(42, "https://example.com/img.jpg"))
        assert exc_info.value.retry_after == 5.0


class TestClassifyWriteResponseUniform429:
    """Structural fix: the 429 check now lives INSIDE
    `_classify_write_response` — the single choke point every write method
    (including any added later) routes through — instead of being
    duplicated per-method (which is exactly what let `set_published`/
    `add_product_image` forget it)."""

    def test_classify_write_response_raises_rate_limited_on_429(self):
        response = _fake_response(429)
        response.headers = {"Retry-After": "7"}
        with pytest.raises(TnRateLimited) as exc_info:
            TiendaNubeProductClient._classify_write_response(response)
        assert exc_info.value.retry_after == 7.0

    def test_classify_write_response_raises_rate_limited_with_no_retry_after(self):
        response = _fake_response(429)
        response.headers = {}
        with pytest.raises(TnRateLimited) as exc_info:
            TiendaNubeProductClient._classify_write_response(response)
        assert exc_info.value.retry_after is None


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


class TestFetchCategoriesPagination:
    """`GET /categories` is paginated by TN (30/page by default). Fetching a
    single unparameterized page silently mirrored only the first slice of the
    tree into `tn_category_embedding` — the picker then had nothing else to
    offer, no matter how many rows the read endpoint was willing to return.
    """

    @staticmethod
    def _page(size, start_id):
        return [{"id": start_id + i, "name": {"es": f"Cat {start_id + i}"}, "parent": None} for i in range(size)]

    def test_follows_every_page_until_a_short_one(self):
        client = TiendaNubeProductClient(store_id="123", access_token="tok")
        full = self._page(CATEGORIES_PAGE_SIZE, 1)
        tail = self._page(3, 1000)
        mock_client = AsyncMock()
        mock_client.get.side_effect = [_fake_response(200, full), _fake_response(200, tail)]
        with patch("httpx.AsyncClient") as MockAsyncClient:
            MockAsyncClient.return_value.__aenter__.return_value = mock_client
            result = asyncio.run(client.fetch_categories())

        assert result == full + tail
        assert mock_client.get.call_count == 2
        assert mock_client.get.call_args_list[0].kwargs["params"] == {"page": 1, "per_page": CATEGORIES_PAGE_SIZE}
        assert mock_client.get.call_args_list[1].kwargs["params"] == {"page": 2, "per_page": CATEGORIES_PAGE_SIZE}

    def test_stops_on_an_empty_page(self):
        client = TiendaNubeProductClient(store_id="123", access_token="tok")
        full = self._page(CATEGORIES_PAGE_SIZE, 1)
        mock_client = AsyncMock()
        mock_client.get.side_effect = [_fake_response(200, full), _fake_response(200, [])]
        with patch("httpx.AsyncClient") as MockAsyncClient:
            MockAsyncClient.return_value.__aenter__.return_value = mock_client
            result = asyncio.run(client.fetch_categories())

        assert result == full
        assert mock_client.get.call_count == 2

    def test_a_failed_later_page_returns_none_never_a_partial_catalog(self):
        # The sync REPLACES the mirror wholesale: handing it a partial list
        # would truncate the catalog exactly like the single-page bug did.
        # Fail closed — the sync skips and the previous good mirror stands.
        client = TiendaNubeProductClient(store_id="123", access_token="tok")
        full = self._page(CATEGORIES_PAGE_SIZE, 1)
        mock_client = AsyncMock()
        mock_client.get.side_effect = [_fake_response(200, full), _fake_response(503)]
        with patch("httpx.AsyncClient") as MockAsyncClient:
            MockAsyncClient.return_value.__aenter__.return_value = mock_client
            result = asyncio.run(client.fetch_categories())

        assert result is None

    def test_a_connection_error_on_a_later_page_returns_none(self):
        client = TiendaNubeProductClient(store_id="123", access_token="tok")
        full = self._page(CATEGORIES_PAGE_SIZE, 1)
        mock_client = AsyncMock()
        mock_client.get.side_effect = [_fake_response(200, full), Exception("connection reset")]
        with patch("httpx.AsyncClient") as MockAsyncClient:
            MockAsyncClient.return_value.__aenter__.return_value = mock_client
            result = asyncio.run(client.fetch_categories())

        assert result is None

    def test_page_cap_stops_the_loop_and_returns_none(self):
        # A catalog that never returns a short page (or a TN that ignores
        # `page`) must not loop forever — and must not hand back a silently
        # truncated tree either.
        client = TiendaNubeProductClient(store_id="123", access_token="tok")
        mock_client = AsyncMock()
        mock_client.get.return_value = _fake_response(200, self._page(CATEGORIES_PAGE_SIZE, 1))
        with patch("httpx.AsyncClient") as MockAsyncClient:
            MockAsyncClient.return_value.__aenter__.return_value = mock_client
            result = asyncio.run(client.fetch_categories())

        assert result is None
        assert mock_client.get.call_count == CATEGORIES_MAX_PAGES


_LIST_IMAGES_SAMPLE = [
    {
        "id": 1259483639,
        "product_id": 363340520,
        "src": "https://acdn-us.mitiendanube.com/stores/006/084/082/products/probe.jpg",
        "position": 1,
        "alt": [],
        "height": 200,
        "width": 200,
        "thumbnails_generated": 1,
        "created_at": "2026-08-26T12:35:16+0000",
        "updated_at": "2026-08-26T12:35:16+0000",
        "store_media_uuid": None,
    }
]


class TestListProductImages:
    def test_without_credentials_is_ambiguous_no_request(self):
        client = TiendaNubeProductClient(store_id=None, access_token=None)
        outcome = asyncio.run(client.list_product_images(42))
        assert outcome["ok"] is False
        assert outcome["ambiguous"] is True
        assert outcome["images"] is None

    def test_happy_path_returns_parsed_array(self):
        client = TiendaNubeProductClient(store_id="123", access_token="tok")
        mock_client = AsyncMock()
        mock_client.get.return_value = _fake_response(200, _LIST_IMAGES_SAMPLE)
        with patch("httpx.AsyncClient") as MockAsyncClient:
            MockAsyncClient.return_value.__aenter__.return_value = mock_client
            outcome = asyncio.run(client.list_product_images(363340520))
        assert outcome["ok"] is True
        assert outcome["ambiguous"] is False
        assert outcome["images"] == _LIST_IMAGES_SAMPLE
        call_args = mock_client.get.call_args
        assert call_args.args[0] == "https://api.tiendanube.com/v1/123/products/363340520/images"

    def test_empty_product_returns_empty_list_distinguishable_from_failure(self):
        client = TiendaNubeProductClient(store_id="123", access_token="tok")
        mock_client = AsyncMock()
        mock_client.get.return_value = _fake_response(200, [])
        with patch("httpx.AsyncClient") as MockAsyncClient:
            MockAsyncClient.return_value.__aenter__.return_value = mock_client
            outcome = asyncio.run(client.list_product_images(42))
        assert outcome["ok"] is True
        assert outcome["images"] == []

        # Contrast: a failed list must NOT look like the empty-list case.
        mock_client_fail = AsyncMock()
        mock_client_fail.get.return_value = _fake_response(503)
        with patch("httpx.AsyncClient") as MockAsyncClient:
            MockAsyncClient.return_value.__aenter__.return_value = mock_client_fail
            failed_outcome = asyncio.run(client.list_product_images(42))
        assert failed_outcome["ok"] is False
        assert failed_outcome["images"] is None

    def test_429_raises_rate_limited(self):
        client = TiendaNubeProductClient(store_id="123", access_token="tok")
        mock_client = AsyncMock()
        mock_client.get.return_value = _fake_response(429)
        mock_client.get.return_value.headers = {"Retry-After": "3"}
        with patch("httpx.AsyncClient") as MockAsyncClient:
            MockAsyncClient.return_value.__aenter__.return_value = mock_client
            with pytest.raises(TnRateLimited) as exc_info:
                asyncio.run(client.list_product_images(42))
        assert exc_info.value.retry_after == 3.0

    def test_connection_error_is_ambiguous_never_raises(self):
        client = TiendaNubeProductClient(store_id="123", access_token="tok")
        mock_client = AsyncMock()
        mock_client.get.side_effect = Exception("connection reset")
        with patch("httpx.AsyncClient") as MockAsyncClient:
            MockAsyncClient.return_value.__aenter__.return_value = mock_client
            outcome = asyncio.run(client.list_product_images(42))
        assert outcome["ok"] is False
        assert outcome["ambiguous"] is True
        assert outcome["images"] is None


class TestDeleteProductImage:
    def test_without_credentials_is_ambiguous_no_request(self):
        client = TiendaNubeProductClient(store_id=None, access_token=None)
        outcome = asyncio.run(client.delete_product_image(42, 1259483639))
        assert outcome == {"ok": False, "status_code": None, "ambiguous": True, "body": None}

    def test_200_is_success(self):
        """TN's DELETE returns 200 with body {} — not 204."""
        client = TiendaNubeProductClient(store_id="123", access_token="tok")
        mock_client = AsyncMock()
        mock_client.delete.return_value = _fake_response(200, {})
        with patch("httpx.AsyncClient") as MockAsyncClient:
            MockAsyncClient.return_value.__aenter__.return_value = mock_client
            outcome = asyncio.run(client.delete_product_image(42, 1259483639))
        assert outcome["ok"] is True
        assert outcome["status_code"] == 200
        call_args = mock_client.delete.call_args
        assert call_args.args[0] == "https://api.tiendanube.com/v1/123/products/42/images/1259483639"

    def test_4xx_is_definitive_rejection(self):
        client = TiendaNubeProductClient(store_id="123", access_token="tok")
        mock_client = AsyncMock()
        mock_client.delete.return_value = _fake_response(404, {"error": "not_found"})
        with patch("httpx.AsyncClient") as MockAsyncClient:
            MockAsyncClient.return_value.__aenter__.return_value = mock_client
            outcome = asyncio.run(client.delete_product_image(42, 1259483639))
        assert outcome["ok"] is False
        assert outcome["ambiguous"] is False
        assert outcome["status_code"] == 404

    def test_429_raises_rate_limited(self):
        client = TiendaNubeProductClient(store_id="123", access_token="tok")
        mock_client = AsyncMock()
        mock_client.delete.return_value = _fake_response(429)
        mock_client.delete.return_value.headers = {"Retry-After": "9"}
        with patch("httpx.AsyncClient") as MockAsyncClient:
            MockAsyncClient.return_value.__aenter__.return_value = mock_client
            with pytest.raises(TnRateLimited) as exc_info:
                asyncio.run(client.delete_product_image(42, 1259483639))
        assert exc_info.value.retry_after == 9.0


class TestAddProductImageByBytes:
    def test_posts_base64_of_exact_bytes_and_parses_id(self):
        import base64

        client = TiendaNubeProductClient(store_id="123", access_token="tok")
        raw = b"\xff\xd8\xff\xe0fakejpegbytes"
        mock_client = AsyncMock()
        mock_client.post.return_value = _fake_response(
            201,
            {"id": 1259483639, "product_id": 363340520, "src": "https://acdn-us.mitiendanube.com/x.jpg"},
        )
        with patch("httpx.AsyncClient") as MockAsyncClient:
            MockAsyncClient.return_value.__aenter__.return_value = mock_client
            outcome = asyncio.run(client.add_product_image(42, attachment=raw, filename="probe.jpg"))
        assert outcome["ok"] is True
        assert outcome["body"]["id"] == 1259483639
        call_args = mock_client.post.call_args
        sent = call_args.kwargs["json"]
        assert sent["filename"] == "probe.jpg"
        assert base64.b64decode(sent["attachment"]) == raw

    def test_2xx_without_parseable_id_does_not_claim_success_as_created(self):
        client = TiendaNubeProductClient(store_id="123", access_token="tok")
        mock_client = AsyncMock()
        # 2xx but body has no "id" — inconclusive, not a confirmed creation.
        mock_client.post.return_value = _fake_response(201, {"unexpected": "shape"})
        with patch("httpx.AsyncClient") as MockAsyncClient:
            MockAsyncClient.return_value.__aenter__.return_value = mock_client
            outcome = asyncio.run(client.add_product_image(42, attachment=b"bytes", filename="x.jpg"))
        assert outcome["ok"] is True
        assert outcome.get("created_image_id") is None

    def test_without_credentials_is_ambiguous_no_request(self):
        client = TiendaNubeProductClient(store_id=None, access_token=None)
        outcome = asyncio.run(client.add_product_image(42, attachment=b"bytes", filename="x.jpg"))
        assert outcome == {"ok": False, "status_code": None, "ambiguous": True, "body": None}

    def test_429_raises_rate_limited(self):
        client = TiendaNubeProductClient(store_id="123", access_token="tok")
        mock_client = AsyncMock()
        mock_client.post.return_value = _fake_response(429)
        mock_client.post.return_value.headers = {"Retry-After": "2"}
        with patch("httpx.AsyncClient") as MockAsyncClient:
            MockAsyncClient.return_value.__aenter__.return_value = mock_client
            with pytest.raises(TnRateLimited) as exc_info:
                asyncio.run(client.add_product_image(42, attachment=b"bytes", filename="x.jpg"))
        assert exc_info.value.retry_after == 2.0

    def test_existing_src_behaviour_unchanged(self):
        client = TiendaNubeProductClient(store_id="123", access_token="tok")
        mock_client = AsyncMock()
        mock_client.post.return_value = _fake_response(201, {"id": 1, "src": "https://example.com/img.jpg"})
        with patch("httpx.AsyncClient") as MockAsyncClient:
            MockAsyncClient.return_value.__aenter__.return_value = mock_client
            outcome = asyncio.run(client.add_product_image(42, src="https://example.com/img.jpg"))
        assert outcome["ok"] is True
        call_args = mock_client.post.call_args
        assert call_args.kwargs["json"] == {"src": "https://example.com/img.jpg"}
