"""
RED/GREEN -- `MLWebhookClient.get_activity` (ml-activity-receiver slice 2).

Spec coverage:
  REQ-1 -- fetches `GET /api/ml/activity?since=<cursor>&topics=...&limit=<n>`
           and returns the exact live-verified shape: `events`, `has_more`,
           `next_cursor` (no `paging` object, see obs #2008).
  REQ-2 -- HTTP 400 (invalid cursor) RAISES `ActivityCursorRejected` --
           this is the one client method that breaks the file's uniform
           "swallow errors, return None" convention on purpose (design
           D5, precedent at ml_webhook_client.py:448-459). A `None` return
           here would make an unrecoverable 400 indistinguishable from a
           retryable timeout and bring back silent retry-from-zero.
  REQ-3 -- any other transport failure (timeout, connect error, 5xx) still
           returns `None`, matching every other read method in this file.
  REQ-4 -- `limit` is forwarded to the bridge as-is; the client does not
           re-implement the server's documented 500 clamp locally (the
           bridge already clamps server-side per obs #2008, and a second,
           possibly-drifting clamp here would just be another place to
           get it wrong).
"""

from __future__ import annotations

import asyncio

import httpx
import pytest

from app.services.ml_webhook_client import ActivityCursorRejected, MLWebhookClient

ACTIVITY_PAYLOAD = {
    "events": [
        {
            "topic": "orders_v2",
            "order_id": 2000018351015920,
            "pack_id": None,
            "resource": "/orders/2000018351015920",
            "sent": "2026-09-08T19:42:56.963Z",
            "occurred_at": "2026-09-08T19:42:57.070813+00:00",
        }
    ],
    "has_more": True,
    "next_cursor": "YTF8Mg==",
}


def _patch_client(monkeypatch: pytest.MonkeyPatch, transport: httpx.MockTransport) -> None:
    original_init = httpx.AsyncClient.__init__

    def patched_init(self, *args, **kwargs):
        kwargs["transport"] = transport
        original_init(self, *args, **kwargs)

    monkeypatch.setattr(httpx.AsyncClient, "__init__", patched_init)


class TestGetActivitySuccess:
    def test_parses_the_verified_shape(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.path == "/api/ml/activity"
            return httpx.Response(200, json=ACTIVITY_PAYLOAD)

        _patch_client(monkeypatch, httpx.MockTransport(handler))
        client = MLWebhookClient()

        result = asyncio.run(client.get_activity(since="a1|1"))

        assert result["events"] == ACTIVITY_PAYLOAD["events"]
        assert result["has_more"] is True
        assert result["next_cursor"] == "YTF8Mg=="
        assert "paging" not in result

    def test_since_and_limit_are_forwarded(self, monkeypatch: pytest.MonkeyPatch) -> None:
        seen = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen["since"] = request.url.params.get("since")
            seen["limit"] = request.url.params.get("limit")
            return httpx.Response(200, json=ACTIVITY_PAYLOAD)

        _patch_client(monkeypatch, httpx.MockTransport(handler))
        client = MLWebhookClient()

        asyncio.run(client.get_activity(since="a1|1", limit=750))

        assert seen["since"] == "a1|1"
        # Not re-clamped locally -- forwarded exactly as given, the bridge
        # is documented (obs #2008) to clamp server-side at 500.
        assert seen["limit"] == "750"

    def test_topics_are_forwarded(self, monkeypatch: pytest.MonkeyPatch) -> None:
        seen = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen["topics"] = request.url.params.get("topics")
            return httpx.Response(200, json=ACTIVITY_PAYLOAD)

        _patch_client(monkeypatch, httpx.MockTransport(handler))
        client = MLWebhookClient()

        asyncio.run(client.get_activity(since="a1|1", topics=["orders_v2", "shipments"]))

        assert seen["topics"] == "orders_v2,shipments"


class TestGetActivityInvalidCursor:
    def test_http_400_raises_activity_cursor_rejected(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(400, json={"error": "cursor invalido"})

        _patch_client(monkeypatch, httpx.MockTransport(handler))
        client = MLWebhookClient()

        with pytest.raises(ActivityCursorRejected):
            asyncio.run(client.get_activity(since="garbage"))

    def test_activity_cursor_rejected_is_never_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Mutation-guard companion: pins that the exception path is taken,
        not a None return, on the exact 400 status the bridge documents."""

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(400, json={"error": "cursor invalido"})

        _patch_client(monkeypatch, httpx.MockTransport(handler))
        client = MLWebhookClient()

        raised = False
        try:
            asyncio.run(client.get_activity(since="garbage"))
        except ActivityCursorRejected:
            raised = True

        assert raised is True


class TestGetActivityTransportFailure:
    def test_timeout_returns_none_never_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.TimeoutException("timeout", request=request)

        _patch_client(monkeypatch, httpx.MockTransport(handler))
        client = MLWebhookClient()

        assert asyncio.run(client.get_activity(since="a1|1")) is None

    def test_connect_error_returns_none_never_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("boom", request=request)

        _patch_client(monkeypatch, httpx.MockTransport(handler))
        client = MLWebhookClient()

        assert asyncio.run(client.get_activity(since="a1|1")) is None

    def test_500_returns_none_never_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(500, json={"error": "boom"})

        _patch_client(monkeypatch, httpx.MockTransport(handler))
        client = MLWebhookClient()

        assert asyncio.run(client.get_activity(since="a1|1")) is None
