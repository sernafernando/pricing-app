"""
RED/GREEN — `MLWebhookClient.get_order` / `get_shipment` / `search_orders`
(ml-ventas-fuente-de-verdad, slice 2).

Spec coverage:
  REQ-1 — `get_order`/`get_shipment` fetch via the existing
          `/api/ml/preview?resource=` proxy convention, mirroring every
          other read method in this client.
  REQ-2 — 404 -> None (never raises).
  REQ-3 — any other error/timeout -> None (never raises).
  REQ-4 — `search_orders` fetches via `/api/ml/preview?resource=/orders/search`
          with seller id, ISO date-range params and an `offset`.
  REQ-5 (Threat Matrix, SSRF row) — `order_id`/`shipment_id` are coerced to
          `int` BEFORE any HTTP call is made. A non-numeric id raises
          `ValueError` synchronously, never reaching the network, so no
          caller-supplied string can ever reach the proxy `resource=` path.
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


ORDER_PAYLOAD = {"id": 2000003508498841, "status": "paid"}
SHIPMENT_PAYLOAD = {"id": 40000012345, "status": "delivered"}
SEARCH_PAYLOAD = {"results": [ORDER_PAYLOAD], "paging": {"total": 1, "offset": 0, "limit": 50}}


class TestGetOrder:
    def test_success_returns_payload(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.path == "/api/ml/preview"
            assert request.url.params["resource"] == "/orders/2000003508498841"
            return httpx.Response(200, json=ORDER_PAYLOAD)

        _patch_client(monkeypatch, httpx.MockTransport(handler))
        client = MLWebhookClient()

        result = asyncio.run(client.get_order(2000003508498841))

        assert result == ORDER_PAYLOAD

    def test_404_returns_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(404, json={"message": "not found"})

        _patch_client(monkeypatch, httpx.MockTransport(handler))
        client = MLWebhookClient()

        assert asyncio.run(client.get_order(999)) is None

    def test_error_returns_none_never_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("boom", request=request)

        _patch_client(monkeypatch, httpx.MockTransport(handler))
        client = MLWebhookClient()

        assert asyncio.run(client.get_order(123)) is None

    def test_timeout_returns_none_never_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.TimeoutException("timeout", request=request)

        _patch_client(monkeypatch, httpx.MockTransport(handler))
        client = MLWebhookClient()

        assert asyncio.run(client.get_order(123)) is None

    def test_non_numeric_id_raises_before_any_http_call(self, monkeypatch: pytest.MonkeyPatch) -> None:
        calls: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(request.url.path)
            return httpx.Response(200, json=ORDER_PAYLOAD)

        _patch_client(monkeypatch, httpx.MockTransport(handler))
        client = MLWebhookClient()

        with pytest.raises(ValueError):
            asyncio.run(client.get_order("123; DROP TABLE"))  # type: ignore[arg-type]

        assert calls == []

    def test_accepts_numeric_string_id(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.params["resource"] == "/orders/123"
            return httpx.Response(200, json=ORDER_PAYLOAD)

        _patch_client(monkeypatch, httpx.MockTransport(handler))
        client = MLWebhookClient()

        result = asyncio.run(client.get_order("123"))  # type: ignore[arg-type]

        assert result == ORDER_PAYLOAD


class TestGetShipment:
    def test_success_returns_payload(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.path == "/api/ml/preview"
            assert request.url.params["resource"] == "/shipments/40000012345"
            return httpx.Response(200, json=SHIPMENT_PAYLOAD)

        _patch_client(monkeypatch, httpx.MockTransport(handler))
        client = MLWebhookClient()

        result = asyncio.run(client.get_shipment(40000012345))

        assert result == SHIPMENT_PAYLOAD

    def test_404_returns_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(404, json={"message": "not found"})

        _patch_client(monkeypatch, httpx.MockTransport(handler))
        client = MLWebhookClient()

        assert asyncio.run(client.get_shipment(999)) is None

    def test_error_returns_none_never_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("boom", request=request)

        _patch_client(monkeypatch, httpx.MockTransport(handler))
        client = MLWebhookClient()

        assert asyncio.run(client.get_shipment(123)) is None

    def test_non_numeric_id_raises_before_any_http_call(self, monkeypatch: pytest.MonkeyPatch) -> None:
        calls: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(request.url.path)
            return httpx.Response(200, json=SHIPMENT_PAYLOAD)

        _patch_client(monkeypatch, httpx.MockTransport(handler))
        client = MLWebhookClient()

        with pytest.raises(ValueError):
            asyncio.run(client.get_shipment("not-an-id"))  # type: ignore[arg-type]

        assert calls == []


class TestSearchOrders:
    def test_success_returns_payload(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from datetime import datetime, timezone

        def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.path == "/api/ml/preview"
            assert request.url.params["resource"].startswith("/orders/search")
            assert "seller=456" in request.url.params["resource"]
            assert "order.date_last_updated.from=2026-08-01T00" in request.url.params["resource"]
            assert "order.date_last_updated.to=2026-08-02T00" in request.url.params["resource"]
            return httpx.Response(200, json=SEARCH_PAYLOAD)

        _patch_client(monkeypatch, httpx.MockTransport(handler))
        client = MLWebhookClient()

        result = asyncio.run(
            client.search_orders(
                seller_id=456,
                date_from=datetime(2026, 8, 1, tzinfo=timezone.utc),
                date_to=datetime(2026, 8, 2, tzinfo=timezone.utc),
            )
        )

        assert result == SEARCH_PAYLOAD

    def test_offset_is_forwarded(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from datetime import datetime, timezone

        def handler(request: httpx.Request) -> httpx.Response:
            assert "offset=50" in request.url.params["resource"]
            return httpx.Response(200, json=SEARCH_PAYLOAD)

        _patch_client(monkeypatch, httpx.MockTransport(handler))
        client = MLWebhookClient()

        result = asyncio.run(
            client.search_orders(
                seller_id=456,
                date_from=datetime(2026, 8, 1, tzinfo=timezone.utc),
                date_to=datetime(2026, 8, 2, tzinfo=timezone.utc),
                offset=50,
            )
        )

        assert result == SEARCH_PAYLOAD

    def test_error_returns_none_never_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from datetime import datetime, timezone

        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("boom", request=request)

        _patch_client(monkeypatch, httpx.MockTransport(handler))
        client = MLWebhookClient()

        result = asyncio.run(
            client.search_orders(
                seller_id=456,
                date_from=datetime(2026, 8, 1, tzinfo=timezone.utc),
                date_to=datetime(2026, 8, 2, tzinfo=timezone.utc),
            )
        )

        assert result is None

    def test_naive_datetime_raises_before_any_http_call(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from datetime import datetime

        calls: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(request.url.path)
            return httpx.Response(200, json=SEARCH_PAYLOAD)

        _patch_client(monkeypatch, httpx.MockTransport(handler))
        client = MLWebhookClient()

        with pytest.raises(ValueError):
            asyncio.run(
                client.search_orders(
                    seller_id=456,
                    date_from=datetime(2026, 8, 1),
                    date_to=datetime(2026, 8, 2),
                )
            )

        assert calls == []


class TestCoercionRaisesValueError:
    """The docstrings promise `ValueError` on an uncoercible id. `int(None)`
    natively raises `TypeError`, so a caller following the docstring would
    miss it. These pin the documented contract."""

    def test_get_order_with_none_raises_value_error(self) -> None:
        client = MLWebhookClient()

        with pytest.raises(ValueError):
            asyncio.run(client.get_order(None))  # type: ignore[arg-type]

    def test_get_shipment_with_none_raises_value_error(self) -> None:
        client = MLWebhookClient()

        with pytest.raises(ValueError):
            asyncio.run(client.get_shipment(None))  # type: ignore[arg-type]

    def test_search_orders_with_none_seller_raises_value_error(self) -> None:
        from datetime import datetime, timezone

        client = MLWebhookClient()

        with pytest.raises(ValueError):
            asyncio.run(
                client.search_orders(
                    None,  # type: ignore[arg-type]
                    datetime(2026, 1, 1, tzinfo=timezone.utc),
                    datetime(2026, 1, 2, tzinfo=timezone.utc),
                )
            )


class TestSearchOrdersDateContract:
    """`search_orders` documents ValueError for naive dates; a missing
    date used to surface as AttributeError instead."""

    def test_none_date_from_raises_value_error(self) -> None:
        from datetime import datetime, timezone

        client = MLWebhookClient()

        with pytest.raises(ValueError):
            asyncio.run(client.search_orders(123, None, datetime(2026, 1, 2, tzinfo=timezone.utc)))  # type: ignore[arg-type]

    def test_none_date_to_raises_value_error(self) -> None:
        from datetime import datetime, timezone

        client = MLWebhookClient()

        with pytest.raises(ValueError):
            asyncio.run(client.search_orders(123, datetime(2026, 1, 1, tzinfo=timezone.utc), None))  # type: ignore[arg-type]
