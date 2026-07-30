"""
RED/GREEN — `get_catalog_competition` (promos-catalog-prices-and-official-store,
slice C1a).

UNLIKE every other read method on this client, this one does NOT collapse
errors to `None`. It must let a caller distinguish "MLA is not a catalog
publication" (400) from a transport/parse failure, because both look
identical from a `None` and the caller needs an honest `fetch_status`.

The proxy answers errors as HTML even when `format=processed` was
requested, so status code AND content-type must both be checked before
`.json()` is ever called.

Spec coverage (design #1210 section 3.2, spec #1209 C1.1):
  - 200 + application/json + valid body -> {"status": "ok", "payload": ...}
  - 400                                 -> {"status": "not_catalog", ...}
  - 200 + text/html (error rendered as HTML) -> {"status": "error", ...},
    no JSON-decode exception
  - 200 + application/json but unparseable body -> {"status": "error", ...}
  - 500                                 -> {"status": "error", ...}
  - httpx.TimeoutException              -> {"status": "error", ...}
  - Never raises.
"""

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


PROCESSED_PAYLOAD = {
    "catalog_product_id": "MLA123456789",
    "product": {
        "id": "MLA123456789",
        "name": "Producto de prueba",
        "thumbnail": "https://example.com/thumb.jpg",
        "buy_box_winner_item_id": "MLA987654321",
    },
    "competitors": [
        {
            "item_id": "MLA987654321",
            "seller_id": 111,
            "nickname": "SELLER_A",
            "is_winner": True,
            "price": 1000.0,
            "original_price": None,
            "currency_id": "ARS",
            "listing_type_id": "gold_special",
            "listing_label": "Clásica",
            "installments": None,
            "shipping_badges": ["FULL"],
            "tags": [],
            "permalink": "https://articulo.mercadolibre.com.ar/MLA-987654321",
        }
    ],
}


class TestGetCatalogCompetition:
    def test_200_json_returns_ok_status_with_payload(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.path == "/catalogCompetition"
            assert request.url.params["input"] == "MLA123456789"
            assert request.url.params["format"] == "processed"
            return httpx.Response(
                200,
                json=PROCESSED_PAYLOAD,
                headers={"content-type": "application/json"},
            )

        _patch_client(monkeypatch, httpx.MockTransport(handler))
        client = MLWebhookClient()

        result = asyncio.run(client.get_catalog_competition("MLA123456789"))

        assert result == {"status": "ok", "payload": PROCESSED_PAYLOAD}

    def test_400_returns_not_catalog_without_parsing_json(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                400,
                content=b"<div class='alert alert-warning m-4'>no es catalogo</div>",
                headers={"content-type": "text/html; charset=utf-8"},
            )

        _patch_client(monkeypatch, httpx.MockTransport(handler))
        client = MLWebhookClient()

        result = asyncio.run(client.get_catalog_competition("MLA_NOT_CATALOG"))

        assert result["status"] == "not_catalog"
        assert "detail" in result

    def test_200_html_error_body_returns_error_not_json_decode_exception(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The proxy can answer 200 with an HTML error body in edge cases
        (upstream degraded rendering); the content-type guard must catch
        this BEFORE `.json()` is attempted, regardless of status code."""

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                content=b"<html><body>unexpected error page</body></html>",
                headers={"content-type": "text/html; charset=utf-8"},
            )

        _patch_client(monkeypatch, httpx.MockTransport(handler))
        client = MLWebhookClient()

        result = asyncio.run(client.get_catalog_competition("MLA_HTML_ERROR"))

        assert result["status"] == "error"
        assert "detail" in result

    def test_200_json_content_type_but_unparseable_body_returns_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                content=b"{not valid json",
                headers={"content-type": "application/json"},
            )

        _patch_client(monkeypatch, httpx.MockTransport(handler))
        client = MLWebhookClient()

        result = asyncio.run(client.get_catalog_competition("MLA_BAD_JSON"))

        assert result["status"] == "error"
        assert "detail" in result

    def test_5xx_returns_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(500, content=b"internal error", headers={"content-type": "text/html"})

        _patch_client(monkeypatch, httpx.MockTransport(handler))
        client = MLWebhookClient()

        result = asyncio.run(client.get_catalog_competition("MLA_5XX"))

        assert result["status"] == "error"
        assert "500" in result["detail"]

    def test_other_4xx_returns_error_not_not_catalog(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Only 400 means 'not a catalog publication'. Any other 4xx
        (e.g. a proxy-auth 401 or a routing 404) is a genuine error, not
        the business fact 'no aplica'."""

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(404, content=b"not found", headers={"content-type": "text/html"})

        _patch_client(monkeypatch, httpx.MockTransport(handler))
        client = MLWebhookClient()

        result = asyncio.run(client.get_catalog_competition("MLA_404"))

        assert result["status"] == "error"

    def test_timeout_returns_error_never_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.TimeoutException("boom", request=request)

        _patch_client(monkeypatch, httpx.MockTransport(handler))
        client = MLWebhookClient()

        result = asyncio.run(client.get_catalog_competition("MLA_TIMEOUT"))

        assert result["status"] == "error"

    def test_connection_error_returns_error_never_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("connection refused", request=request)

        _patch_client(monkeypatch, httpx.MockTransport(handler))
        client = MLWebhookClient()

        result = asyncio.run(client.get_catalog_competition("MLA_CONN_ERROR"))

        assert result["status"] == "error"
