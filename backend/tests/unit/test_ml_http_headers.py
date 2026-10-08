"""ml-billing-balance PR 1a -- `MlHttpClient.get(..., headers=...)` (design D5, ADS-2).

The ads endpoints need a per-call `Api-Version` header (`2` for product_ads,
`1` for advertisers/display/brand_ads), so one client serves both versions.
The Authorization header stays owned by the client.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

import httpx
import pytest

from app.core.config import settings
from app.services.ml_publications.ml_http import MlHttpClient
from app.services.ml_publications.pacing import Pacer


class _FakeClock:
    def __init__(self) -> None:
        self._t = 0.0

    def monotonic(self) -> float:
        return self._t

    def now(self) -> datetime:
        return datetime(2026, 10, 8, tzinfo=timezone.utc)

    def sleep(self, seconds: float) -> None:
        self._t += seconds


class _Recorder:
    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return httpx.Response(200, json={"ok": True})


@pytest.fixture()
def recorder(monkeypatch) -> _Recorder:
    monkeypatch.setattr(settings, "ML_USER_ID", "413658225")
    monkeypatch.setattr(settings, "ML_CLIENT_ID", "7211863044554429")
    return _Recorder()


def _client(recorder: _Recorder) -> MlHttpClient:
    return MlHttpClient(
        pacer=Pacer(clock=_FakeClock()),
        transport=httpx.MockTransport(recorder),
        token_loader=lambda: {"access_token": "tok-secret", "expires_epoch": 9e12},
    )


class TestExtraHeaders:
    def test_api_version_header_is_sent_alongside_authorization(self, recorder: _Recorder) -> None:
        with _client(recorder) as client:
            response = client.get("ads", "/advertising/product_ads/campaigns", headers={"Api-Version": "2"})

        assert response.status == 200
        assert len(recorder.requests) == 1
        sent = recorder.requests[0].headers
        assert sent["api-version"] == "2"
        assert sent["authorization"] == "Bearer tok-secret"

    def test_other_version_value_is_sent_verbatim(self, recorder: _Recorder) -> None:
        with _client(recorder) as client:
            client.get("ads", "/advertising/advertisers", headers={"Api-Version": "1"})

        assert recorder.requests[0].headers["api-version"] == "1"

    def test_without_headers_nothing_extra_is_sent(self, recorder: _Recorder) -> None:
        with _client(recorder) as client:
            client.get("ads", "/advertising/advertisers")

        assert "api-version" not in recorder.requests[0].headers
        assert recorder.requests[0].headers["authorization"] == "Bearer tok-secret"

    def test_headers_survive_the_401_retry(self, monkeypatch) -> None:
        monkeypatch.setattr(settings, "ML_USER_ID", "413658225")
        monkeypatch.setattr(settings, "ML_CLIENT_ID", "7211863044554429")
        seen: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            return httpx.Response(401 if len(seen) == 1 else 200, json={})

        client = MlHttpClient(
            pacer=Pacer(clock=_FakeClock()),
            transport=httpx.MockTransport(handler),
            token_loader=lambda: {"access_token": "t", "expires_epoch": 9e12},
        )
        with client:
            response = client.get("ads", "/x", headers={"Api-Version": "2"})

        assert response.status == 200
        assert [r.headers["api-version"] for r in seen] == ["2", "2"]


class TestAuthorizationIsNotOverridable:
    @pytest.mark.parametrize("name", ["Authorization", "authorization", "AUTHORIZATION"])
    def test_authorization_override_raises_before_any_call(self, recorder: _Recorder, name: str) -> None:
        with _client(recorder) as client:
            with pytest.raises(ValueError):
                client.get("ads", "/x", headers={name: "Bearer evil"})

        assert recorder.requests == []


class TestHeaderValuesAreNotLogged:
    def test_header_values_never_reach_the_logs(self, recorder: _Recorder, caplog) -> None:
        caplog.set_level(logging.DEBUG)
        with _client(recorder) as client:
            client.get("ads", "/x", headers={"Api-Version": "2-sentinel-value"})
            with pytest.raises(ValueError):
                client.get("ads", "/x", headers={"authorization": "Bearer sentinel-evil"})

        assert "2-sentinel-value" not in caplog.text
        assert "sentinel-evil" not in caplog.text
