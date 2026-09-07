"""
RED/GREEN — `MLWebhookClient.get_payment` (ml-ventas-desglose-costos,
corte 5).

Spec coverage:
  REQ-1 — fetches via `GET /api/ml/payment?payment_id=<id>` -- a
          DIFFERENT proxy endpoint than `get_order`/`get_shipment`
          (`/api/ml/orders`), and does NOT use `resource=`.
  REQ-2 — 404/error/timeout -> None (never raises), same as every other
          read method on this client.
  REQ-3 (Threat Matrix, SSRF row) — `payment_id` is coerced to `int`
          BEFORE any HTTP call. A non-numeric id raises `ValueError`
          synchronously, never reaching the network.
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


PAYMENT_PAYLOAD = {
    "payment_id": 21000018322969636,
    "order_id": 2000018322969636,
    "status": "approved",
    "currency_id": "ARS",
    "date_approved": "2026-08-01T10:00:00.000-04:00",
    "net_received_amount": 7371.11,
    "total_paid_amount": 7371.11,
    "transaction_amount": 7371.11,
    "shipping_amount": 0,
    "coupon_amount": 0,
    "taxes_amount": 0,
    "transaction_amount_refunded": 0,
    "charges_details": [],
}


class TestGetPayment:
    def test_success_returns_payload(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.path == "/api/ml/payment"
            assert request.url.params["payment_id"] == "21000018322969636"
            assert "resource" not in request.url.params
            return httpx.Response(200, json=PAYMENT_PAYLOAD)

        _patch_client(monkeypatch, httpx.MockTransport(handler))
        client = MLWebhookClient()

        result = asyncio.run(client.get_payment(21000018322969636))

        assert result == PAYMENT_PAYLOAD

    def test_404_returns_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(404)

        _patch_client(monkeypatch, httpx.MockTransport(handler))
        client = MLWebhookClient()

        result = asyncio.run(client.get_payment(999))

        assert result is None

    def test_timeout_returns_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ReadTimeout("timed out")

        _patch_client(monkeypatch, httpx.MockTransport(handler))
        client = MLWebhookClient()

        result = asyncio.run(client.get_payment(999))

        assert result is None

    def test_non_coercible_id_raises_before_any_http_call(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            raise AssertionError("must not reach the network")

        _patch_client(monkeypatch, httpx.MockTransport(handler))
        client = MLWebhookClient()

        with pytest.raises(ValueError):
            asyncio.run(client.get_payment("not-a-number"))

    def test_string_id_accepted(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.params["payment_id"] == "21000018322969636"
            return httpx.Response(200, json=PAYMENT_PAYLOAD)

        _patch_client(monkeypatch, httpx.MockTransport(handler))
        client = MLWebhookClient()

        result = asyncio.run(client.get_payment("21000018322969636"))

        assert result == PAYMENT_PAYLOAD
