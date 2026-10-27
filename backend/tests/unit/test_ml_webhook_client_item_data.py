"""`MLWebhookClient.put_item_data` / `put_item_description`: push a publication's override through the ml-webhook
proxy (`PUT /api/items/{mla}/data` and `PUT /api/items/{mla}/description`), single-shot, classified like the status
write with the proxy's `data_write` / `description_write` field:

  2xx                   -> written
  "not_attempted"       -> not written (proxy validation, kill switch)
  "ambiguous"           -> maybe written (timeout or exception at the proxy)
  4xx without the field -> ML refused it: not written
  no response at all    -> ambiguous, never retried
"""

from __future__ import annotations

import asyncio

import httpx
import pytest

from app.services.ml_webhook_client import MLWebhookClient

ITEM_BODY = {"title": "Router AX55", "pictures": [{"id": "P2"}, {"id": "P1"}]}


def _call(monkeypatch: pytest.MonkeyPatch, respond, method: str, *args) -> tuple[dict, list[httpx.Request]]:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return respond(request)

    original_init = httpx.AsyncClient.__init__

    def patched_init(self, *init_args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        original_init(self, *init_args, **kwargs)

    monkeypatch.setattr(httpx.AsyncClient, "__init__", patched_init)
    return asyncio.run(getattr(MLWebhookClient(), method)("MLA123", *args)), seen


def test_puts_the_item_body_to_the_proxy_once(monkeypatch: pytest.MonkeyPatch) -> None:
    result, seen = _call(
        monkeypatch, lambda request: httpx.Response(200, json={"id": "MLA123"}), "put_item_data", ITEM_BODY
    )
    assert result == {"ok": True, "status_code": 200, "ambiguous": False, "body": {"id": "MLA123"}}
    assert [(r.method, r.url.path, r.read()) for r in seen] == [
        ("PUT", "/api/items/MLA123/data", b'{"title":"Router AX55","pictures":[{"id":"P2"},{"id":"P1"}]}')
    ]


def test_puts_the_description_to_the_proxy_once(monkeypatch: pytest.MonkeyPatch) -> None:
    result, seen = _call(monkeypatch, lambda request: httpx.Response(200, json={}), "put_item_description", "WiFi 6")
    assert result["ok"] is True
    assert [(r.method, r.url.path, r.read()) for r in seen] == [
        ("PUT", "/api/items/MLA123/description", b'{"plain_text":"WiFi 6"}')
    ]


WRITES = [("put_item_data", "data_write", ITEM_BODY), ("put_item_description", "description_write", "x")]


@pytest.mark.parametrize(("method", "field", "arg"), WRITES)
@pytest.mark.parametrize(("code", "stamp", "ambiguous"), [(503, "not_attempted", False), (504, "ambiguous", True)])
def test_the_proxy_stamp_decides_a_failure(
    monkeypatch: pytest.MonkeyPatch, method: str, field: str, arg, code: int, stamp: str, ambiguous: bool
) -> None:
    result, _ = _call(monkeypatch, lambda request: httpx.Response(code, json={field: stamp}), method, arg)
    assert (result["ok"], result["ambiguous"]) == (False, ambiguous)


@pytest.mark.parametrize(("method", "field", "arg"), WRITES)
def test_an_ml_rejection_relayed_is_definite(monkeypatch: pytest.MonkeyPatch, method: str, field: str, arg) -> None:
    refused = {"message": "title not modifiable"}
    result, _ = _call(monkeypatch, lambda request: httpx.Response(400, json=refused), method, arg)
    assert (result["ok"], result["ambiguous"], result["body"]) == (False, False, refused)


@pytest.mark.parametrize(("method", "arg"), [("put_item_data", ITEM_BODY), ("put_item_description", "x")])
def test_no_response_is_ambiguous_and_not_retried(monkeypatch: pytest.MonkeyPatch, method: str, arg) -> None:
    def fail(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow", request=request)

    result, seen = _call(monkeypatch, fail, method, arg)
    assert result == {"ok": False, "status_code": None, "ambiguous": True, "body": None}
    assert len(seen) == 1
