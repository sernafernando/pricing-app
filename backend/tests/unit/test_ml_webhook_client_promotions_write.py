"""
Unit tests for the ML Seller Promotions WRITE methods added to
`MLWebhookClient` (ml_webhook_client.py) in PR2.

`enroll_item` / `remove_item` MUST return a STRUCTURED result
`{ok, status_code, ambiguous, body}` — never collapse to None on error,
unlike the read methods. No retry on any of these (single-shot).

Spec coverage:
  REQ-1 — enroll_item 201 -> ok=True, ambiguous=False
  REQ-2 — enroll_item 400 -> ok=False, ambiguous=False (validation, not ambiguous)
  REQ-3 — enroll_item timeout -> ok=False, ambiguous=True
  REQ-4 — enroll_item 5xx -> ok=False, ambiguous=True
  REQ-5 — remove_item 200 -> ok=True
  REQ-6 — remove_item timeout/5xx -> ambiguous=True
"""

from __future__ import annotations

import asyncio

import httpx
import pytest

from app.services.ml_webhook_client import MLWebhookClient


def _mock_transport(handler):
    return httpx.MockTransport(handler)


def _patch_client(monkeypatch: pytest.MonkeyPatch, transport: httpx.MockTransport) -> None:
    original_init = httpx.AsyncClient.__init__

    def patched_init(self, *args, **kwargs):
        kwargs["transport"] = transport
        original_init(self, *args, **kwargs)

    monkeypatch.setattr(httpx.AsyncClient, "__init__", patched_init)


class TestEnrollItem:
    def test_201_returns_ok_not_ambiguous(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            assert request.method == "POST"
            assert request.url.path == "/api/promociones/item/MLA123456789"
            import json

            body = json.loads(request.content)
            assert body == {"promotion_id": "DEAL-1", "promotion_type": "DEAL", "deal_price": 900.0}
            return httpx.Response(201, json={"status": "candidate"})

        _patch_client(monkeypatch, _mock_transport(handler))
        client = MLWebhookClient()

        result = asyncio.run(client.enroll_item("MLA123456789", "DEAL-1", "DEAL", 900.0))
        assert result == {"ok": True, "status_code": 201, "ambiguous": False, "body": {"status": "candidate"}}

    def test_201_with_top_deal_price_in_body(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            import json

            body = json.loads(request.content)
            assert body["top_deal_price"] == 850.0
            return httpx.Response(201, json={})

        _patch_client(monkeypatch, _mock_transport(handler))
        client = MLWebhookClient()

        result = asyncio.run(client.enroll_item("MLA123456789", "DEAL-1", "DEAL", 900.0, top_deal_price=850.0))
        assert result["ok"] is True

    def test_400_is_ok_false_not_ambiguous(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(400, json={"message": "invalid price"})

        _patch_client(monkeypatch, _mock_transport(handler))
        client = MLWebhookClient()

        result = asyncio.run(client.enroll_item("MLA123456789", "DEAL-1", "DEAL", 900.0))
        assert result["ok"] is False
        assert result["ambiguous"] is False
        assert result["status_code"] == 400

    def test_timeout_is_ambiguous(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.TimeoutException("boom", request=request)

        _patch_client(monkeypatch, _mock_transport(handler))
        client = MLWebhookClient()

        result = asyncio.run(client.enroll_item("MLA123456789", "DEAL-1", "DEAL", 900.0))
        assert result["ok"] is False
        assert result["ambiguous"] is True
        assert result["status_code"] is None

    def test_5xx_is_ambiguous(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(500, json={"message": "boom"})

        _patch_client(monkeypatch, _mock_transport(handler))
        client = MLWebhookClient()

        result = asyncio.run(client.enroll_item("MLA123456789", "DEAL-1", "DEAL", 900.0))
        assert result["ok"] is False
        assert result["ambiguous"] is True
        assert result["status_code"] == 500

    def test_no_retry_single_call(self, monkeypatch: pytest.MonkeyPatch) -> None:
        call_count = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            call_count["n"] += 1
            raise httpx.TimeoutException("boom", request=request)

        _patch_client(monkeypatch, _mock_transport(handler))
        client = MLWebhookClient()

        asyncio.run(client.enroll_item("MLA123456789", "DEAL-1", "DEAL", 900.0))
        assert call_count["n"] == 1


class TestEnrollItemOfferId:
    def test_offer_id_included_when_provided(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            import json

            body = json.loads(request.content)
            assert body["offer_id"] == "CANDIDATE-MLA1859172999-1"
            return httpx.Response(201, json={"offer_id": "OFFER-MLA1859172999-1"})

        _patch_client(monkeypatch, _mock_transport(handler))
        client = MLWebhookClient()

        result = asyncio.run(
            client.enroll_item(
                "MLA1859172999",
                "P-MLA1",
                "SMART",
                19585.27,
                offer_id="CANDIDATE-MLA1859172999-1",
            )
        )
        assert result["ok"] is True
        assert result["body"]["offer_id"] == "OFFER-MLA1859172999-1"

    def test_offer_id_omitted_from_body_when_not_provided(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            import json

            body = json.loads(request.content)
            assert "offer_id" not in body
            return httpx.Response(201, json={})

        _patch_client(monkeypatch, _mock_transport(handler))
        client = MLWebhookClient()

        result = asyncio.run(client.enroll_item("MLA123456789", "DEAL-1", "DEAL", 900.0))
        assert result["ok"] is True


class TestRemoveItem:
    def test_200_returns_ok(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            assert request.method == "DELETE"
            assert request.url.path == "/api/promociones/item/MLA123456789"
            assert request.url.params.get("promotion_type") == "DEAL"
            assert request.url.params.get("promotion_id") == "DEAL-1"
            return httpx.Response(200, json={"ok": True})

        _patch_client(monkeypatch, _mock_transport(handler))
        client = MLWebhookClient()

        result = asyncio.run(client.remove_item("MLA123456789", "DEAL", "DEAL-1"))
        assert result["ok"] is True
        assert result["ambiguous"] is False

    def test_timeout_is_ambiguous(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.TimeoutException("boom", request=request)

        _patch_client(monkeypatch, _mock_transport(handler))
        client = MLWebhookClient()

        result = asyncio.run(client.remove_item("MLA123456789", "DEAL", "DEAL-1"))
        assert result["ok"] is False
        assert result["ambiguous"] is True

    def test_5xx_is_ambiguous(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(503, json={"message": "unavailable"})

        _patch_client(monkeypatch, _mock_transport(handler))
        client = MLWebhookClient()

        result = asyncio.run(client.remove_item("MLA123456789", "DEAL", "DEAL-1"))
        assert result["ok"] is False
        assert result["ambiguous"] is True

    def test_no_retry_single_call(self, monkeypatch: pytest.MonkeyPatch) -> None:
        call_count = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            call_count["n"] += 1
            raise httpx.TimeoutException("boom", request=request)

        _patch_client(monkeypatch, _mock_transport(handler))
        client = MLWebhookClient()

        asyncio.run(client.remove_item("MLA123456789", "DEAL", "DEAL-1"))
        assert call_count["n"] == 1


class TestRefreshItemPromotions:
    """`refresh_item_promotions` triggers a server-side point-refresh of the
    ml-webhook mirror after our own enroll/remove. Mirrors the read
    methods' error-swallowing shape (never raises), but returns a bool
    since only did-it-work matters here (no payload to surface)."""

    def test_2xx_returns_true(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            assert request.method == "POST"
            assert request.url.path == "/api/promociones/item/MLA123456789/refresh"
            assert request.content == b""
            return httpx.Response(200, json={"status": "ok"})

        _patch_client(monkeypatch, _mock_transport(handler))
        client = MLWebhookClient()

        result = asyncio.run(client.refresh_item_promotions("MLA123456789"))
        assert result.ok is True
        assert result.motivo is None

    def test_a_4xx_carries_the_proxy_reason_and_is_NOT_retryable(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The real case, captured from production: ML answers 400 on a
        CLOSED item, ml-webhook relays it as 409 with the reason in the
        body. That body only arrives on a 4xx -- Cloudflare replaces the
        body of any 5xx from the origin with its own page, which is why
        this exact failure reached us as a bare "502" and cost an hour of
        eliminating healthy infrastructure.

        Not retryable: a closed item stays closed, and spending the drain's
        retry budget on it delays every row behind it."""

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                409,
                json={
                    "mla": "MLA123456789",
                    "refreshed": False,
                    "reason": "Item status is not allowed (closed)",
                    "ml_status": 400,
                },
            )

        _patch_client(monkeypatch, _mock_transport(handler))

        result = asyncio.run(MLWebhookClient().refresh_item_promotions("MLA123456789"))

        assert result.ok is False
        assert result.motivo == "La publicación está cerrada"
        assert result.reintentable is False

    def test_an_unrecognised_reason_is_shown_verbatim(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A reason we cannot name is still worth more on screen than the
        status code alone -- never swallowed into a generic message."""

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(409, json={"reason": "algo que ML no dijo nunca antes"})

        _patch_client(monkeypatch, _mock_transport(handler))

        result = asyncio.run(MLWebhookClient().refresh_item_promotions("MLA123456789"))

        assert result.motivo == "algo que ML no dijo nunca antes"

    def test_a_5xx_is_retryable_and_names_the_status(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A 5xx is the proxy or ML failing, not the item -- worth another
        go. Its body is unreliable behind Cloudflare, so the status is what
        we can honestly report."""

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(502, json={"message": "boom"})

        _patch_client(monkeypatch, _mock_transport(handler))

        result = asyncio.run(MLWebhookClient().refresh_item_promotions("MLA123456789"))

        assert result.ok is False
        assert result.motivo == "MercadoLibre respondió 502"
        assert result.reintentable is True

    def test_a_timeout_says_so_and_is_retryable(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ReadTimeout("boom", request=request)

        _patch_client(monkeypatch, _mock_transport(handler))

        result = asyncio.run(MLWebhookClient().refresh_item_promotions("MLA123456789"))

        assert result.ok is False
        assert result.motivo == "Se agotó el tiempo de espera"
        assert result.reintentable is True

    def test_an_unexpected_error_never_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            raise RuntimeError("unexpected")

        _patch_client(monkeypatch, _mock_transport(handler))

        result = asyncio.run(MLWebhookClient().refresh_item_promotions("MLA123456789"))

        assert result.ok is False
        assert result.motivo == "RuntimeError"


class TestRemoveItemOfferId:
    def test_offer_id_included_in_query_when_provided(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.params.get("offer_id") == "OFFER-MLA1859172999-1"
            return httpx.Response(200, json={"ok": True})

        _patch_client(monkeypatch, _mock_transport(handler))
        client = MLWebhookClient()

        result = asyncio.run(client.remove_item("MLA1859172999", "SMART", "P-MLA1", offer_id="OFFER-MLA1859172999-1"))
        assert result["ok"] is True

    def test_offer_id_omitted_from_query_when_not_provided(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            assert "offer_id" not in request.url.params
            return httpx.Response(200, json={"ok": True})

        _patch_client(monkeypatch, _mock_transport(handler))
        client = MLWebhookClient()

        result = asyncio.run(client.remove_item("MLA123456789", "DEAL", "DEAL-1"))
        assert result["ok"] is True
