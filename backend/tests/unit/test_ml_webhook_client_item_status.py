"""`MLWebhookClient.put_item_status`: pause or activate a publication through the ml-webhook proxy
(`PUT /api/items/{mla}/status`), single-shot, classified like the PxQ write with the proxy's `status_write` field:

  2xx                   -> written
  "not_attempted"       -> not written (proxy validation, kill switch)
  "ambiguous"           -> maybe written (timeout or exception at the proxy)
  4xx without the field -> ML refused it: not written
  5xx without the field -> unknown: ambiguous
  no response at all    -> ambiguous
"""

from __future__ import annotations

import asyncio

import httpx
import pytest

from app.services.ml_webhook_client import MLWebhookClient


def _put(monkeypatch: pytest.MonkeyPatch, respond) -> tuple[dict, list[httpx.Request]]:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return respond(request)

    original_init = httpx.AsyncClient.__init__

    def patched_init(self, *args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        original_init(self, *args, **kwargs)

    monkeypatch.setattr(httpx.AsyncClient, "__init__", patched_init)
    return asyncio.run(MLWebhookClient().put_item_status("MLA123", "paused")), seen


def test_puts_the_status_to_the_proxy_once(monkeypatch: pytest.MonkeyPatch) -> None:
    result, seen = _put(monkeypatch, lambda request: httpx.Response(200, json={"id": "MLA123", "status": "paused"}))
    assert result == {"ok": True, "status_code": 200, "ambiguous": False, "body": {"id": "MLA123", "status": "paused"}}
    assert [(r.method, r.url.path, r.read()) for r in seen] == [
        ("PUT", "/api/items/MLA123/status", b'{"status":"paused"}')
    ]


@pytest.mark.parametrize("code", [400, 503])
def test_not_attempted_is_not_ambiguous(monkeypatch: pytest.MonkeyPatch, code: int) -> None:
    result, _ = _put(monkeypatch, lambda request: httpx.Response(code, json={"status_write": "not_attempted"}))
    assert (result["ok"], result["ambiguous"], result["status_code"]) == (False, False, code)


@pytest.mark.parametrize("code", [500, 504])
def test_ambiguous_is_ambiguous(monkeypatch: pytest.MonkeyPatch, code: int) -> None:
    result, _ = _put(monkeypatch, lambda request: httpx.Response(code, json={"status_write": "ambiguous"}))
    assert (result["ok"], result["ambiguous"]) == (False, True)


def test_an_ml_rejection_relayed_is_definite(monkeypatch: pytest.MonkeyPatch) -> None:
    result, _ = _put(monkeypatch, lambda request: httpx.Response(400, json={"message": "item under review"}))
    assert (result["ok"], result["ambiguous"], result["body"]) == (False, False, {"message": "item under review"})


def test_an_ml_5xx_relayed_is_ambiguous(monkeypatch: pytest.MonkeyPatch) -> None:
    result, _ = _put(monkeypatch, lambda request: httpx.Response(502, json={"message": "bad gateway"}))
    assert (result["ok"], result["ambiguous"]) == (False, True)


def test_no_response_is_ambiguous(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow", request=request)

    result, seen = _put(monkeypatch, fail)
    assert result == {"ok": False, "status_code": None, "ambiguous": True, "body": None}
    assert len(seen) == 1  # no retry
