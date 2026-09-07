"""
RED/GREEN — `MLWebhookClient.get_billing_periods` / `get_billing_details` /
`get_shipment_costs` (ml-ventas-desglose-costos, corte 2).

Spec coverage:
  REQ-1 — `get_billing_periods(group)` fetches via `/api/ml/billing?resource=
          /billing/integration/monthly/periods?group=<g>&document_type=BILL`
          and returns the parsed period list.
  REQ-2 — `get_billing_details(period_key, group, limit, offset)` fetches via
          `/api/ml/billing?resource=/billing/integration/periods/key/<key>/
          group/<g>/details?document_type=BILL&limit=<limit>&offset=<offset>`,
          advances `offset` between pages, and respects the response `total`.
  REQ-3 — `get_shipment_costs(shipment_id)` fetches via `/api/ml/orders?
          resource=/shipments/<id>/costs` and returns the raw payload. It
          NEVER derives the seller cost from `base_cost/2` — the seller cost
          is `senders[0].cost`, taken verbatim from the ML response.
  REQ-4 (Threat Matrix, SSRF row) — every id (`shipment_id`) is coerced to
          `int` BEFORE any HTTP call. A non-numeric id raises `ValueError`
          synchronously, never reaching the network.
"""

from __future__ import annotations

import asyncio

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.services.ml_webhook_client import MLWebhookClient


def _patch_client(monkeypatch: pytest.MonkeyPatch, transport: httpx.MockTransport) -> None:
    original_init = httpx.AsyncClient.__init__

    def patched_init(self, *args, **kwargs):
        kwargs["transport"] = transport
        original_init(self, *args, **kwargs)

    monkeypatch.setattr(httpx.AsyncClient, "__init__", patched_init)


PERIODS_PAYLOAD = {
    "periods": [
        {"key": "2026-09-01", "status": "OPEN"},
        {"key": "2026-08-01", "status": "CLOSED"},
    ]
}

DETAILS_PAYLOAD_PAGE_1 = {
    "results": [{"charge_info": {"detail_id": "1"}}] * 3,
    "paging": {"total": 5, "limit": 3, "offset": 0},
}
DETAILS_PAYLOAD_PAGE_2 = {
    "results": [{"charge_info": {"detail_id": "2"}}] * 2,
    "paging": {"total": 5, "limit": 3, "offset": 3},
}

SHIPMENT_COSTS_PAYLOAD = {
    "gross_amount": 730000,
    "receiver": {"cost": 30380, "save": 4490, "discounts": []},
    "senders": [{"cost": 15190, "save": 0, "charges": [], "discounts": [{"rate": 0.5, "type": "mandatory"}]}],
}


class TestGetBillingPeriods:
    def test_success_returns_periods(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.path == "/api/ml/billing"
            resource = request.url.params["resource"]
            assert resource.startswith("/billing/integration/monthly/periods")
            assert "group=ML" in resource
            assert "document_type=BILL" in resource
            return httpx.Response(200, json=PERIODS_PAYLOAD)

        _patch_client(monkeypatch, httpx.MockTransport(handler))
        client = MLWebhookClient()

        result = asyncio.run(client.get_billing_periods("ML"))

        assert result == PERIODS_PAYLOAD

    def test_error_returns_none_never_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("boom", request=request)

        _patch_client(monkeypatch, httpx.MockTransport(handler))
        client = MLWebhookClient()

        assert asyncio.run(client.get_billing_periods("ML")) is None


class TestGetBillingDetails:
    def test_success_returns_first_page(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.path == "/api/ml/billing"
            resource = request.url.params["resource"]
            assert resource.startswith("/billing/integration/periods/key/2026-09-01/group/ML/details")
            assert "document_type=BILL" in resource
            assert "limit=1000" in resource
            assert "offset=0" in resource
            return httpx.Response(200, json=DETAILS_PAYLOAD_PAGE_1)

        _patch_client(monkeypatch, httpx.MockTransport(handler))
        client = MLWebhookClient()

        result = asyncio.run(client.get_billing_details("2026-09-01", "ML"))

        assert result == DETAILS_PAYLOAD_PAGE_1

    def test_offset_and_limit_are_forwarded(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            resource = request.url.params["resource"]
            assert "offset=3" in resource
            assert "limit=3" in resource
            return httpx.Response(200, json=DETAILS_PAYLOAD_PAGE_2)

        _patch_client(monkeypatch, httpx.MockTransport(handler))
        client = MLWebhookClient()

        result = asyncio.run(client.get_billing_details("2026-09-01", "ML", limit=3, offset=3))

        assert result == DETAILS_PAYLOAD_PAGE_2
        assert result["paging"]["total"] == 5

    def test_error_returns_none_never_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.TimeoutException("timeout", request=request)

        _patch_client(monkeypatch, httpx.MockTransport(handler))
        client = MLWebhookClient()

        assert asyncio.run(client.get_billing_details("2026-09-01", "ML")) is None


class TestGetShipmentCosts:
    def test_success_returns_payload(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.path == "/api/ml/orders"
            assert request.url.params["resource"] == "/shipments/40000012345/costs"
            return httpx.Response(200, json=SHIPMENT_COSTS_PAYLOAD)

        _patch_client(monkeypatch, httpx.MockTransport(handler))
        client = MLWebhookClient()

        result = asyncio.run(client.get_shipment_costs(40000012345))

        assert result == SHIPMENT_COSTS_PAYLOAD
        seller_cost = result["senders"][0]["cost"]
        assert seller_cost == 15190
        # NEVER derived from base_cost/2 — there is no base_cost key at all
        # in this payload, and the seller cost must come verbatim from
        # `senders[0].cost`, not a computed half of anything.
        assert "base_cost" not in result
        assert seller_cost != result["gross_amount"] / 2

    def test_404_returns_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(404, json={"message": "not found"})

        _patch_client(monkeypatch, httpx.MockTransport(handler))
        client = MLWebhookClient()

        assert asyncio.run(client.get_shipment_costs(999)) is None

    def test_error_returns_none_never_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("boom", request=request)

        _patch_client(monkeypatch, httpx.MockTransport(handler))
        client = MLWebhookClient()

        assert asyncio.run(client.get_shipment_costs(123)) is None

    def test_non_numeric_id_raises_before_any_http_call(self, monkeypatch: pytest.MonkeyPatch) -> None:
        calls: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(request.url.path)
            return httpx.Response(200, json=SHIPMENT_COSTS_PAYLOAD)

        _patch_client(monkeypatch, httpx.MockTransport(handler))
        client = MLWebhookClient()

        with pytest.raises(ValueError):
            asyncio.run(client.get_shipment_costs("123; DROP TABLE"))  # type: ignore[arg-type]

        assert calls == []

    def test_none_id_raises_value_error(self) -> None:
        client = MLWebhookClient()

        with pytest.raises(ValueError):
            asyncio.run(client.get_shipment_costs(None))  # type: ignore[arg-type]


class TestBillingResourceValidation:
    """`group` y `period_key` van en el PATH del resource, no en un query
    param. `params=` los url-encodea hacia el proxy, pero el proxy los
    decodifica y los usa como path: el encoding es transporte, no
    validación. El sweep del corte 3 los deriva, así que el chequeo va acá.
    """

    # `asyncio.run(...)` y no `@pytest.mark.asyncio`, igual que el resto de
    # este archivo: `pytest-asyncio` está en el `.venv` local pero NO en
    # `requirements.txt`, y el CI instala solo `pytest httpx`. Con el marker,
    # allá el cuerpo de la corrutina no se ejecuta y el test pasa en verde
    # sin correr un solo assert -- justo sobre la fila SSRF.

    def test_group_invalido_levanta_antes_de_cualquier_http(self):
        client = MLWebhookClient()
        with patch("httpx.AsyncClient") as fake:
            with pytest.raises(ValueError, match="group de facturación inválido"):
                asyncio.run(client.get_billing_periods("ML/details?document_type=BILL&"))
            fake.assert_not_called()

    def test_period_key_con_traversal_levanta_antes_de_cualquier_http(self):
        client = MLWebhookClient()
        with patch("httpx.AsyncClient") as fake:
            with pytest.raises(ValueError, match="period_key inválido"):
                asyncio.run(client.get_billing_details("../../users/me", "ML"))
            fake.assert_not_called()

    def test_group_valido_no_levanta(self):
        client = MLWebhookClient()
        with patch("httpx.AsyncClient") as fake:
            fake.return_value.__aenter__.return_value.get = AsyncMock(
                return_value=MagicMock(json=MagicMock(return_value={"results": []}), raise_for_status=MagicMock())
            )
            assert asyncio.run(client.get_billing_details("2026-09-01", "MP")) == {"results": []}
