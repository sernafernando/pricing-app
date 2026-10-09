"""ml-billing-balance PR 5-i -- the typed flex `/details` fetch (task 5.2, BF-1).

Flex details page by `offset` (limit 500), not by `from_id`, and ML answers 422
`MISSING_PARAMETER_ERROR` when `document_type` is absent (captured in
`flex_billing_capture_20261007_145118.json`). The 400 body is the real envelope
from `captured_400_envelope.json`; like the general fetch, the transport REPLAYS
it, because the proxy forwarding that status was never separately confirmed.
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
_PAGE = {"results": [], "total": 3324, "limit": 500, "offset": 500, "last_id": 71947563232, "errors": []}


def _patch_client(monkeypatch: pytest.MonkeyPatch, handler) -> None:
    original_init = httpx.AsyncClient.__init__

    def patched_init(self, *args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        original_init(self, *args, **kwargs)

    monkeypatch.setattr(httpx.AsyncClient, "__init__", patched_init)


def _fetch(**overrides) -> BillingFetch:
    args = {"period_key": "2026-10-01", "group": "ML", "document_type": "CREDIT_NOTE", "limit": 500, "offset": 500}
    args.update(overrides)
    return asyncio.run(MLWebhookClient().fetch_billing_flex_details(**args))


class TestFetchBillingFlexDetails:
    def test_the_request_pages_by_offset_and_always_names_the_document_type(self, monkeypatch) -> None:
        seen = []
        _patch_client(monkeypatch, lambda request: seen.append(request) or httpx.Response(200, json=_PAGE))
        fetch = _fetch()
        resource = seen[0].url.params["resource"]
        assert resource == (
            "/billing/integration/periods/key/2026-10-01/group/ML/flex/details"
            "?document_type=CREDIT_NOTE&limit=500&offset=500"
        )
        assert (fetch.status, fetch.body, fetch.ok) == (200, _PAGE, True)

    def test_there_is_no_from_id_and_no_sort_on_a_flex_request(self, monkeypatch) -> None:
        seen = []
        _patch_client(monkeypatch, lambda request: seen.append(request) or httpx.Response(200, json=_PAGE))
        _fetch(offset=0)
        assert "from_id" not in seen[0].url.params["resource"]
        assert "sort_by" not in seen[0].url.params["resource"]

    def test_limit_defaults_to_500_and_offset_to_zero(self, monkeypatch) -> None:
        seen = []
        _patch_client(monkeypatch, lambda request: seen.append(request) or httpx.Response(200, json=_PAGE))
        asyncio.run(MLWebhookClient().fetch_billing_flex_details("2026-10-01", "ML", "BILL"))
        assert seen[0].url.params["resource"].endswith("?document_type=BILL&limit=500&offset=0")

    def test_a_bare_400_is_told_apart(self, monkeypatch) -> None:
        _patch_client(monkeypatch, lambda request: httpx.Response(400, json=_ENVELOPE))
        fetch = _fetch()
        assert (fetch.status, fetch.body, fetch.ok, fetch.is_bare_400) == (400, _ENVELOPE, False, True)

    def test_a_429_is_not_a_400(self, monkeypatch) -> None:
        _patch_client(monkeypatch, lambda request: httpx.Response(429, json={"message": "local_rate_limited"}))
        fetch = _fetch()
        assert (fetch.status, fetch.is_bare_400, fetch.ok) == (429, False, False)

    def test_a_timeout_has_no_status(self, monkeypatch) -> None:
        def timeout(request):
            raise httpx.ReadTimeout("slow", request=request)

        _patch_client(monkeypatch, timeout)
        fetch = _fetch()
        assert (fetch.status, fetch.body, fetch.ok) == (None, None, False) and fetch.error

    @pytest.mark.parametrize(
        "bad",
        [
            {"document_type": "BILL&offset=0"},
            {"document_type": None},
            {"group": "ML/x"},
            {"period_key": "../x"},
            {"offset": -1},
            {"offset": "5;DROP"},
            {"limit": 0},
            {"limit": 501},
            {"limit": 1.5},
            {"offset": 2.0},
            {"offset": True},
        ],
    )
    def test_invalid_arguments_raise_before_any_request(self, monkeypatch, bad) -> None:
        calls = []
        _patch_client(monkeypatch, lambda request: calls.append(request) or httpx.Response(200, json=_PAGE))
        with pytest.raises(ValueError):
            _fetch(**bad)
        assert calls == []
