"""Unit tests for the PxQ WRITE response classification in
`MLWebhookClient.post_pxq_prices` (ml_webhook_client.py).

The `ml-webhook` proxy now tags the responses IT generates with a
`pxq_write` field, so that a failure BEFORE the write and a failure OF the
write stop being indistinguishable by status code alone. Responses relayed
from ML carry no such field -- the absence IS the signal that the status
came from ML, not from the proxy.

Provider contract:
  2xx  / field absent            -> written (ML passthrough)
  400  / "not_attempted"         -> not written (payload rejected by proxy)
  502  / "not_attempted"         -> not written (pre-write read failed)
  504  / "ambiguous"             -> maybe written (POST to ML timed out)
  500  / "ambiguous"             -> maybe written (handler exception)
  non-2xx / field absent         -> ML error relayed as-is

Coverage here:
  502 + not_attempted  -> ambiguous=False   (THE bug: today it is True)
  400 + not_attempted  -> ambiguous=False
  504 + ambiguous      -> ambiguous=True
  500 + ambiguous      -> ambiguous=True
  502 without field    -> ambiguous=True    (ML passthrough, unknown)
  409 without field    -> ambiguous=False   (declared deviation, see below)
  non-JSON body        -> ambiguous=True    (falls to the safe side)
  non-dict JSON body   -> ambiguous=True    (no AttributeError)
  200                  -> ok=True, ambiguous=False

Plus a NO-REGRESSION guardrail: `enroll_item` / `remove_item` (promotions)
must keep classifying by status ALONE. `pxq_write` does not exist in their
responses, and moving this rule into the shared `_classify_write_response`
would turn every promotions non-2xx into an ambiguous write.
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


def _post_pxq(monkeypatch: pytest.MonkeyPatch, response: httpx.Response) -> dict:
    """Runs the real `post_pxq_prices` against a canned proxy response."""

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.url.path == "/api/pxq/item/MLA123456789"
        return response

    _patch_client(monkeypatch, _mock_transport(handler))
    client = MLWebhookClient()
    return asyncio.run(client.post_pxq_prices("MLA123456789", [{"quantity": 10, "amount": 500.0}]))


class TestPxqWriteNotAttempted:
    """`pxq_write == "not_attempted"` is the proxy stating, as a fact, that
    nothing reached ML. Retrying is safe and the mirror must NOT be marked
    `desconocido`."""

    def test_502_not_attempted_is_not_ambiguous(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # The case that motivates the whole change: a 502 raised by the
        # proxy because its own pre-write read failed. By status alone it
        # reads as "5xx, could have applied", so the service marked every
        # tier `desconocido` and sent an operator to reconcile a write that
        # provably never happened.
        result = _post_pxq(monkeypatch, httpx.Response(502, json={"pxq_write": "not_attempted"}))

        assert result["ok"] is False
        assert result["ambiguous"] is False
        assert result["status_code"] == 502
        assert result["body"] == {"pxq_write": "not_attempted"}

    def test_400_not_attempted_is_not_ambiguous(self, monkeypatch: pytest.MonkeyPatch) -> None:
        result = _post_pxq(
            monkeypatch,
            httpx.Response(400, json={"pxq_write": "not_attempted", "message": "invalid payload"}),
        )

        assert result["ok"] is False
        assert result["ambiguous"] is False
        assert result["status_code"] == 400


class TestPxqWriteAmbiguous:
    """`pxq_write == "ambiguous"` is the proxy stating it does not know."""

    def test_504_ambiguous_is_ambiguous(self, monkeypatch: pytest.MonkeyPatch) -> None:
        result = _post_pxq(monkeypatch, httpx.Response(504, json={"pxq_write": "ambiguous"}))

        assert result["ok"] is False
        assert result["ambiguous"] is True
        assert result["status_code"] == 504

    def test_500_ambiguous_is_ambiguous(self, monkeypatch: pytest.MonkeyPatch) -> None:
        result = _post_pxq(monkeypatch, httpx.Response(500, json={"pxq_write": "ambiguous"}))

        assert result["ok"] is False
        assert result["ambiguous"] is True
        assert result["status_code"] == 500


class TestPxqWriteFieldAbsent:
    """No field means the response was relayed from ML untouched."""

    def test_502_without_field_stays_ambiguous(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # A 5xx that ML itself produced. Nobody knows whether it applied,
        # so the conservative verdict stands.
        result = _post_pxq(monkeypatch, httpx.Response(502, json={"message": "bad gateway"}))

        assert result["ok"] is False
        assert result["ambiguous"] is True

    def test_409_without_field_is_a_definitive_rejection_not_ambiguous(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # DECLARED DEVIATION from the provider rule, which says "any non-2xx
        # that is not `not_attempted` is ambiguous".
        #
        # A 4xx relayed from ML (e.g. "You can just send a maximum of 5
        # prices per quantity") is a DEFINITIVE rejection: ML looked at the
        # payload and refused it. On our side `ambiguous=True` does not
        # merely gate a retry -- it makes `ml_pxq_write_service` write
        # `estado = desconocido` into the mirror and force a manual
        # reconciliation. Marking tiers `desconocido` for a write we know
        # was refused is not conservative, it records a falsehood.
        #
        # See `_classify_pxq_write_response` for the full rationale; the
        # deviation was declared to the proxy team so they can veto it.
        result = _post_pxq(monkeypatch, httpx.Response(409, json={"message": "max 5 prices per quantity"}))

        assert result["ok"] is False
        assert result["ambiguous"] is False
        assert result["status_code"] == 409


class TestPxqWriteMalformedBody:
    def test_non_json_body_falls_back_to_status_classification(self, monkeypatch: pytest.MonkeyPatch) -> None:
        result = _post_pxq(monkeypatch, httpx.Response(502, content=b"<html>gateway error</html>"))

        assert result["ok"] is False
        assert result["ambiguous"] is True
        assert result["body"] is None

    def test_json_body_that_is_not_a_dict_does_not_raise(self, monkeypatch: pytest.MonkeyPatch) -> None:
        result = _post_pxq(monkeypatch, httpx.Response(502, json=[{"pxq_write": "not_attempted"}]))

        assert result["ok"] is False
        assert result["ambiguous"] is True


class TestPxqWriteSuccess:
    def test_200_is_ok_and_not_ambiguous(self, monkeypatch: pytest.MonkeyPatch) -> None:
        result = _post_pxq(monkeypatch, httpx.Response(200, json={"prices": []}))

        assert result["ok"] is True
        assert result["ambiguous"] is False
        assert result["status_code"] == 200


class TestSharedClassifierNotRegressed:
    """GUARDRAIL. `_classify_write_response` is shared with the promotions
    write path (`enroll_item` / `remove_item`), where `pxq_write` does not
    exist. This class exists so that anyone tempted to move the PxQ rule
    into the shared classifier breaks a test instead of silently turning
    every promotions non-2xx into an ambiguous write."""

    def test_enroll_item_5xx_still_ambiguous_by_status(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(502, json={"message": "bad gateway"})

        _patch_client(monkeypatch, _mock_transport(handler))
        client = MLWebhookClient()

        result = asyncio.run(client.enroll_item("MLA123456789", "DEAL-1", "DEAL", 900.0))
        assert result["ambiguous"] is True

    def test_enroll_item_4xx_still_definitive_by_status(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(400, json={"message": "invalid price"})

        _patch_client(monkeypatch, _mock_transport(handler))
        client = MLWebhookClient()

        result = asyncio.run(client.enroll_item("MLA123456789", "DEAL-1", "DEAL", 900.0))
        assert result["ambiguous"] is False

    def test_enroll_item_ignores_a_pxq_write_field_if_one_ever_appears(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # Promotions must classify by status ALONE. If this ever starts
        # returning False, the PxQ rule leaked into the shared classifier.
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(502, json={"pxq_write": "not_attempted"})

        _patch_client(monkeypatch, _mock_transport(handler))
        client = MLWebhookClient()

        result = asyncio.run(client.enroll_item("MLA123456789", "DEAL-1", "DEAL", 900.0))
        assert result["ambiguous"] is True

    def test_remove_item_5xx_still_ambiguous_by_status(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(503, json={"pxq_write": "not_attempted"})

        _patch_client(monkeypatch, _mock_transport(handler))
        client = MLWebhookClient()

        result = asyncio.run(client.remove_item("MLA123456789", "DEAL", "DEAL-1"))
        assert result["ambiguous"] is True

    def test_remove_item_4xx_still_definitive_by_status(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(409, json={"message": "conflict"})

        _patch_client(monkeypatch, _mock_transport(handler))
        client = MLWebhookClient()

        result = asyncio.run(client.remove_item("MLA123456789", "DEAL", "DEAL-1"))
        assert result["ambiguous"] is False
