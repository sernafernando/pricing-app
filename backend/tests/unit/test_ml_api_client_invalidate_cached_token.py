"""
Unit tests for `MercadoLibreAPIClient.invalidate_cached_token` (ML publications
sync OAuth fix): the three `sync_ml_publications*` scripts used to do their
own OAuth exchange, burning the shared refresh token owned by ml-webhook.
They now read the access token from ml-webhook's DB via this client and, on a
401, call `invalidate_cached_token()` to force a fresh DB read instead of
re-exchanging any token.
"""

from __future__ import annotations

import time

import pytest

from app.services.ml_api_client import MercadoLibreAPIClient


class TestInvalidateCachedToken:
    def test_clears_cached_token_and_expiry(self) -> None:
        client = MercadoLibreAPIClient()
        client._cached_token = "some-cached-token"
        client._cached_expires_epoch = time.time() + 3600

        client.invalidate_cached_token()

        assert client._cached_token is None
        assert client._cached_expires_epoch == 0.0

    def test_forces_db_reread_on_next_get_access_token(self, monkeypatch: pytest.MonkeyPatch) -> None:
        client = MercadoLibreAPIClient()
        client._cached_token = "stale-token"
        client._cached_expires_epoch = time.time() + 3600

        calls = {"count": 0}

        def fake_load_token() -> dict:
            calls["count"] += 1
            return {"access_token": "fresh-token", "expires_epoch": time.time() + 3600}

        monkeypatch.setattr("app.services.ml_api_client._load_token_from_mlwebhook", fake_load_token)

        client.invalidate_cached_token()

        import asyncio

        token = asyncio.run(client.get_access_token())

        assert token == "fresh-token"
        assert calls["count"] == 1

    def test_noop_when_already_empty(self) -> None:
        client = MercadoLibreAPIClient()
        assert client._cached_token is None

        client.invalidate_cached_token()

        assert client._cached_token is None
        assert client._cached_expires_epoch == 0.0
