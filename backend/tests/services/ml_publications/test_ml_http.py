"""Sync ML HTTP client: typed responses, token re-read on 401, fail-closed config,
no credential ever stored (design D3).

Response BODIES come from the real `/items/bulk` capture. Transport faults
(401/429/5xx/timeouts, `Retry-After` formats) are labelled synthetic: they test
non-payload behavior only.
"""

from __future__ import annotations

import json
import random
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from app.core.config import settings
from app.services.ml_publications import ml_http
from app.services.ml_publications.ml_http import MlHttpClient, MlResponse
from app.services.ml_publications.pacing import DEADLINE, Pacer
from tests.services.ml_publications.conftest import bulk_call
from tests.services.ml_publications.test_pacing import FakeClock

SECRET = "APP_USR-SECRET-TOKEN-123"
FAR_FUTURE_EPOCH = 4_102_444_800.0  # 2100-01-01


class Ticking:
    """Wall clock that advances 1 ms on every read."""

    def __init__(self) -> None:
        self.t = datetime(2026, 10, 6, 12, 0, 0, tzinfo=timezone.utc)

    def __call__(self) -> datetime:
        self.t += timedelta(milliseconds=1)
        return self.t


class Tokens:
    """Token loader stub that serves successive tokens and counts reads."""

    def __init__(self, *tokens: str, expires_epoch: float = FAR_FUTURE_EPOCH) -> None:
        self.tokens = list(tokens) or [SECRET]
        self.expires_epoch = expires_epoch
        self.reads = 0

    def __call__(self):
        token = self.tokens[min(self.reads, len(self.tokens) - 1)]
        self.reads += 1
        return {"access_token": token, "expires_epoch": self.expires_epoch}


@pytest.fixture(autouse=True)
def configured(monkeypatch):
    monkeypatch.setattr(settings, "ML_USER_ID", "413658225")
    monkeypatch.setattr(settings, "ML_CLIENT_ID", "1234567890")


def build(handler, tokens=None, clock=None, now=None, **kwargs) -> tuple[MlHttpClient, list[httpx.Request]]:
    seen: list[httpx.Request] = []

    def recording(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return handler(request)

    clock = clock or FakeClock()
    client = MlHttpClient(
        pacer=Pacer(clock=clock, rng=random.Random(1)),
        transport=httpx.MockTransport(recording),
        token_loader=tokens or Tokens(),
        now=now or Ticking(),
        **kwargs,
    )
    return client, seen


def ok_bulk(_request: httpx.Request) -> httpx.Response:
    return httpx.Response(200, content=json.dumps(bulk_call("bulk_full")))


class TestTypedResponse:
    def test_200_returns_status_exact_body_and_ordered_timestamps(self) -> None:
        client, seen = build(ok_bulk)
        response = client.get("items_bulk", "/items/bulk", {"ids": "MLA935110613,MLA934406852"})
        assert isinstance(response, MlResponse)
        assert (response.endpoint, response.status, response.outcome) == ("items_bulk", 200, "2xx")
        assert response.body == bulk_call("bulk_full")
        assert response.request_started_at < response.received_at
        assert str(seen[0].url) == "https://api.mercadolibre.com/items/bulk?ids=MLA935110613%2CMLA934406852"

    def test_large_integer_ids_survive_parsing_exactly(self) -> None:
        client, _ = build(ok_bulk)
        response = client.get("items_bulk", "/items/bulk", {"ids": "x"})
        family_ids = [e["body"].get("family_id") for e in response.body if e.get("body")]
        assert 7695306917964170 in family_ids

    def test_request_started_before_the_transport_is_invoked(self) -> None:
        clock_reads: list[datetime] = []
        ticking = Ticking()

        def handler(_request):
            clock_reads.append(ticking.t)  # last value handed out before the transport ran
            return httpx.Response(200, json=[])

        client = MlHttpClient(
            pacer=Pacer(clock=FakeClock()),
            transport=httpx.MockTransport(handler),
            token_loader=Tokens(),
            now=ticking,
        )
        response = client.get("items_bulk", "/items/bulk", {"ids": "x"})
        assert response.request_started_at == clock_reads[0]
        assert response.received_at > response.request_started_at

    def test_404_is_a_typed_response_not_an_exception(self) -> None:
        body = {"message": "Item with id MLA1 not found", "error": "not_found", "status": 404, "cause": []}
        client, _ = build(lambda r: httpx.Response(404, json=body))  # real /items/MLA1 404 body (capture 1)
        response = client.get("items_single", "/items/MLA1")
        assert (response.status, response.outcome, response.body) == (404, "404", body)

    @pytest.mark.parametrize(
        ("status", "outcome"), [(200, "2xx"), (400, "4xx"), (403, "4xx"), (404, "404"), (429, "429"), (503, "5xx")]
    )
    def test_status_maps_to_an_outcome_class(self, status, outcome) -> None:
        client, _ = build(lambda r: httpx.Response(status, json={}))
        assert client.get("items_bulk", "/items/bulk").outcome == outcome

    def test_non_json_error_body_is_kept_as_none(self) -> None:
        client, _ = build(lambda r: httpx.Response(502, content=b"<html>bad gateway</html>"))
        response = client.get("items_bulk", "/items/bulk")
        assert (response.status, response.body, response.outcome) == (502, None, "5xx")

    def test_2xx_with_undecodable_body_is_flagged(self) -> None:
        client, _ = build(lambda r: httpx.Response(200, content=b"not json"))
        response = client.get("items_bulk", "/items/bulk")
        assert (response.status, response.body, response.error) == (200, None, "invalid_json")


class TestTransportFaults:
    def test_timeout_is_a_network_outcome(self) -> None:
        def handler(request):
            raise httpx.ReadTimeout("slow", request=request)

        client, _ = build(handler)
        response = client.get("items_bulk", "/items/bulk")
        assert (response.status, response.outcome, response.error) == (0, "network", "timeout")
        assert response.body is None

    def test_connection_failure_is_a_network_outcome(self) -> None:
        def handler(request):
            raise httpx.ConnectError("refused", request=request)

        client, _ = build(handler)
        response = client.get("items_bulk", "/items/bulk")
        assert (response.status, response.outcome, response.error) == (0, "network", "network")

    def test_429_feeds_the_pacer_cooldown_from_retry_after(self) -> None:
        client, _ = build(lambda r: httpx.Response(429, headers={"Retry-After": "30"}, json={}))
        response = client.get("items_bulk", "/items/bulk")
        assert response.outcome == "429"
        assert response.headers["retry-after"] == "30"
        assert client.pacer.cooldown_remaining() == pytest.approx(30.0)

    def test_success_resets_the_pacer_backoff(self) -> None:
        statuses = iter([429, 429, 200, 429])
        client, _ = build(lambda r: httpx.Response(next(statuses), json={}))
        for _ in range(4):
            client.get("items_bulk", "/items/bulk")
        assert client.pacer.cooldown_remaining() <= 2.0  # exponent restarted after the 200


class TestTokenHandling:
    def test_401_rereads_the_token_once_and_retries_once(self) -> None:
        statuses = iter([401, 200])
        tokens = Tokens("old-token", "new-token")
        client, seen = build(lambda r: httpx.Response(next(statuses), json=[]), tokens=tokens)
        response = client.get("items_bulk", "/items/bulk")
        assert response.status == 200
        assert tokens.reads == 2
        assert [r.headers["authorization"] for r in seen] == ["Bearer old-token", "Bearer new-token"]

    def test_second_401_returns_the_failure_without_a_third_attempt(self) -> None:
        tokens = Tokens("old-token", "new-token")
        client, seen = build(lambda r: httpx.Response(401, json={"message": "invalid_token"}), tokens=tokens)
        response = client.get("items_bulk", "/items/bulk")
        assert (response.status, response.outcome) == (401, "4xx")
        assert len(seen) == 2
        assert tokens.reads == 2

    def test_token_is_cached_until_close_to_expiry(self) -> None:
        tokens = Tokens()
        client, _ = build(lambda r: httpx.Response(200, json=[]), tokens=tokens)
        for _ in range(3):
            client.get("items_bulk", "/items/bulk")
        assert tokens.reads == 1

    def test_token_about_to_expire_is_reread_every_call(self) -> None:
        wall = Ticking()
        tokens = Tokens(expires_epoch=wall.t.timestamp() + 30)  # inside the 60 s safety margin
        client, _ = build(lambda r: httpx.Response(200, json=[]), tokens=tokens, now=wall)
        for _ in range(3):
            client.get("items_bulk", "/items/bulk")
        assert tokens.reads == 3

    def test_expiry_is_judged_on_the_injected_clock_not_the_system_clock(self) -> None:
        wall = Ticking()
        tokens = Tokens(expires_epoch=wall.t.timestamp() + 3600)
        client, _ = build(lambda r: httpx.Response(200, json=[]), tokens=tokens, now=wall)
        client.get("items_bulk", "/items/bulk")
        client.get("items_bulk", "/items/bulk")
        assert tokens.reads == 1
        wall.t += timedelta(seconds=3600 - 59)  # now inside the safety margin
        client.get("items_bulk", "/items/bulk")
        assert tokens.reads == 2

    def test_missing_token_makes_no_call(self) -> None:
        client, seen = build(ok_bulk, tokens=lambda: None)
        response = client.get("items_bulk", "/items/bulk")
        assert (response.status, response.outcome, response.error) == (0, "no_token", "no_token")
        assert seen == []


class TestFailClosed:
    @pytest.mark.parametrize("missing", ["ML_USER_ID", "ML_CLIENT_ID"])
    def test_no_call_when_a_credential_setting_is_unset(self, monkeypatch, missing) -> None:
        monkeypatch.setattr(settings, missing, None)
        tokens = Tokens()
        client, seen = build(ok_bulk, tokens=tokens)
        response = client.get("items_bulk", "/items/bulk")
        assert (response.status, response.outcome, response.error) == (0, "not_configured", "not_configured")
        assert seen == [] and tokens.reads == 0

    def test_refused_calls_are_not_counted_as_ml_traffic(self, monkeypatch) -> None:
        monkeypatch.setattr(settings, "ML_USER_ID", None)
        client, _ = build(ok_bulk)
        client.get("items_bulk", "/items/bulk")
        assert client.counters.snapshot() == {}

    def test_pacer_deadline_refuses_the_call(self) -> None:
        clock = FakeClock()
        client, seen = build(ok_bulk, clock=clock)
        client.pacer.on_rate_limited("30")
        response = client.get("items_bulk", "/items/bulk", deadline=clock.now() + timedelta(seconds=5))
        assert (response.status, response.outcome, response.error) == (0, DEADLINE, DEADLINE)
        assert seen == []


class TestNoCredentialStored:
    def test_authorization_header_never_appears_in_returned_structures(self) -> None:
        client, seen = build(ok_bulk, tokens=Tokens(SECRET))
        response = client.get("items_bulk", "/items/bulk", {"ids": "MLA935110613"})
        assert seen[0].headers["authorization"] == f"Bearer {SECRET}"  # it IS sent...
        dumped = repr(response) + json.dumps(dict(response.headers)) + repr(vars(response))
        dumped += json.dumps(client.counters.snapshot()) + repr(client)
        assert SECRET not in dumped  # ...and never kept
        assert "authorization" not in {k.lower() for k in response.headers}

    def test_credential_like_response_headers_are_dropped(self) -> None:
        headers = {"Authorization": "Bearer echoed", "Set-Cookie": "sid=1", "Retry-After": "3", "X-Request-Id": "r1"}
        client, _ = build(lambda r: httpx.Response(200, headers=headers, json=[]))
        kept = client.get("items_bulk", "/items/bulk").headers
        assert "authorization" not in kept and "set-cookie" not in kept
        assert (kept["retry-after"], kept["x-request-id"]) == ("3", "r1")

    def test_query_parameters_never_carry_the_token(self) -> None:
        client, seen = build(ok_bulk, tokens=Tokens(SECRET))
        client.get("items_bulk", "/items/bulk", {"ids": "a"})
        assert SECRET not in str(seen[0].url)


class TestCounters:
    def test_counters_increment_per_endpoint_family_and_outcome_class(self) -> None:
        statuses = iter([200, 200, 404, 429, 503])
        client, _ = build(lambda r: httpx.Response(next(statuses), json={}))
        for _ in range(5):
            client.get("items_bulk", "/items/bulk")
        client.pacer.on_success()

        def boom(request):
            raise httpx.ConnectError("x", request=request)

        other, _ = build(boom)
        other.get("description", "/items/MLA1/description")
        assert client.counters.snapshot() == {"items_bulk": {"2xx": 2, "404": 1, "429": 1, "5xx": 1}}
        assert other.counters.snapshot() == {"description": {"network": 1}}

    def test_a_401_retry_counts_both_attempts(self) -> None:
        statuses = iter([401, 200])
        client, _ = build(lambda r: httpx.Response(next(statuses), json=[]), tokens=Tokens("a", "b"))
        client.get("prices", "/items/MLA1/prices")
        assert client.counters.snapshot() == {"prices": {"4xx": 1, "2xx": 1}}


def test_module_reuses_the_bridge_token_loader_instead_of_copying_it() -> None:
    from app.services import ml_api_client

    assert ml_http._load_token_from_mlwebhook is ml_api_client._load_token_from_mlwebhook
