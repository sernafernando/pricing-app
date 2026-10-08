"""ml-billing-balance PR 4a-iii -- the typed billing fetch (task 4a.1).

`get_billing_details` answers `None` for EVERY failure, so a bare 400 (a poison
row), a 429 (proxy throttle) and a timeout are indistinguishable. The poison
row engine needs the status, so `fetch_billing_details` returns it.

The 400 body is the real envelope ML sent, copied verbatim into
`captured_400_envelope.json`. Whether the PROXY forwards ML's 400 status as is
was never confirmed live: these tests REPLAY it (the transport answers 400
with that body) and pin only what the client does with it.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import httpx
import pytest

from app.services.ml_webhook_client import BillingFetch, MLWebhookClient

_ENVELOPE = json.loads(
    (Path(__file__).resolve().parents[1] / "fixtures" / "ml_billing" / "captured_400_envelope.json").read_text()
)
_PAGE = {"results": [], "total": 0, "limit": 1, "offset": 0, "last_id": 0}


def _patch_client(monkeypatch: pytest.MonkeyPatch, handler) -> None:
    original_init = httpx.AsyncClient.__init__

    def patched_init(self, *args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        original_init(self, *args, **kwargs)

    monkeypatch.setattr(httpx.AsyncClient, "__init__", patched_init)


def _fetch(**overrides) -> BillingFetch:
    args = {"period_key": "2026-09-01", "group": "ML", "document_type": "BILL", "limit": 1, "from_id": 70714313961}
    args.update(overrides)
    return asyncio.run(MLWebhookClient().fetch_billing_details(**args))


class TestFetchBillingDetails:
    def test_success_carries_status_and_body(self, monkeypatch) -> None:
        _patch_client(monkeypatch, lambda request: httpx.Response(200, json=_PAGE))
        fetch = _fetch()
        assert (fetch.status, fetch.body, fetch.error, fetch.ok) == (200, _PAGE, None, True)

    def test_the_request_carries_every_parameter(self, monkeypatch) -> None:
        seen = []
        _patch_client(monkeypatch, lambda request: seen.append(request) or httpx.Response(200, json=_PAGE))
        _fetch(document_type="CREDIT_NOTE", limit=500, from_id=71)
        resource = seen[0].url.params["resource"]
        assert "/periods/key/2026-09-01/group/ML/details" in resource
        assert "document_type=CREDIT_NOTE" in resource and "limit=500" in resource and "from_id=71" in resource

    def test_a_bare_400_is_told_apart(self, monkeypatch) -> None:
        _patch_client(monkeypatch, lambda request: httpx.Response(400, json=_ENVELOPE))
        fetch = _fetch()
        assert (fetch.status, fetch.body, fetch.ok, fetch.is_bare_400) == (400, _ENVELOPE, False, True)

    def test_a_400_that_names_a_cause_is_not_bare(self, monkeypatch) -> None:
        # A rejected parameter is a bug of ours, not a poison row to skip.
        body = {**_ENVELOPE, "error": "invalid_param", "cause": ["from_id must be numeric"]}
        _patch_client(monkeypatch, lambda request: httpx.Response(400, json=body))
        fetch = _fetch()
        assert fetch.status == 400 and not fetch.is_bare_400

    @pytest.mark.parametrize("status", [429, 500, 502, 503, 404, 422])
    def test_other_statuses_are_not_a_bare_400(self, monkeypatch, status) -> None:
        _patch_client(monkeypatch, lambda request: httpx.Response(status, json={"message": "x"}))
        fetch = _fetch()
        assert (fetch.status, fetch.ok, fetch.is_bare_400) == (status, False, False)

    def test_a_400_without_a_json_body_is_not_bare(self, monkeypatch) -> None:
        _patch_client(monkeypatch, lambda request: httpx.Response(400, text="<html>bad gateway</html>"))
        fetch = _fetch()
        assert (fetch.status, fetch.body, fetch.is_bare_400) == (400, None, False)

    def test_a_timeout_has_no_status_and_names_itself(self, monkeypatch) -> None:
        def handler(request):
            raise httpx.ReadTimeout("", request=request)

        _patch_client(monkeypatch, handler)
        fetch = _fetch()
        assert (fetch.status, fetch.ok, fetch.is_bare_400) == (None, False, False)
        assert "ReadTimeout" in fetch.error

    def test_a_cursor_that_is_not_an_id_raises_before_any_request(self, monkeypatch) -> None:
        _patch_client(monkeypatch, lambda request: pytest.fail("no request expected"))
        with pytest.raises(ValueError):
            _fetch(from_id="1; DROP")

    def test_the_legacy_helper_still_answers_none_on_a_400(self, monkeypatch) -> None:
        _patch_client(monkeypatch, lambda request: httpx.Response(400, json=_ENVELOPE))
        assert asyncio.run(MLWebhookClient().get_billing_details("2026-09-01", "ML", limit=1, from_id=1)) is None
