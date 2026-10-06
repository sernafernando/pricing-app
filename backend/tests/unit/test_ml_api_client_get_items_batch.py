"""`MercadoLibreAPIClient.get_items_batch` uses `/items/bulk` (ML deprecates `/items?ids=` on 2026-10-25).

Fixtures: real capture `tests/fixtures/ml/items_bulk_capture_20261006.json`.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import httpx
import pytest

from app.services.ml_api_client import MercadoLibreAPIClient

CAPTURE = Path(__file__).resolve().parent.parent / "fixtures" / "ml" / "items_bulk_capture_20261006.json"
FOUND = ["MLA935110613", "MLA934406852"]


def _call(name: str) -> list:
    data = json.loads(CAPTURE.read_text(encoding="utf-8"))
    return next(c["body"] for c in data["calls"] if c["name"] == name)


async def _fake_token() -> str:
    return "fake-token"


def _client(monkeypatch: pytest.MonkeyPatch, handler) -> MercadoLibreAPIClient:
    original_init = httpx.AsyncClient.__init__

    def patched_init(self, *args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        original_init(self, *args, **kwargs)

    monkeypatch.setattr(httpx.AsyncClient, "__init__", patched_init)
    client = MercadoLibreAPIClient()
    monkeypatch.setattr(client, "get_access_token", lambda: _fake_token())
    return client


@pytest.mark.parametrize("fixture", ["bulk_full", "legacy_multiget"])
def test_requests_bulk_path_and_parses_both_shapes(monkeypatch: pytest.MonkeyPatch, fixture: str) -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=_call(fixture))

    result = asyncio.run(_client(monkeypatch, handler).get_items_batch([*FOUND, "MLA1"]))

    assert len(seen) == 1
    assert seen[0].url.path == "/items/bulk"
    assert seen[0].url.params["ids"] == ",".join([*FOUND, "MLA1"])
    assert sorted(result) == sorted(FOUND)
    assert result[FOUND[0]]["id"] == FOUND[0]


def test_chunks_of_twenty(monkeypatch: pytest.MonkeyPatch) -> None:
    sizes: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        sizes.append(len(request.url.params["ids"].split(",")))
        return httpx.Response(200, json=[])

    asyncio.run(_client(monkeypatch, handler).get_items_batch([f"MLA{i}" for i in range(45)]))
    assert sizes == [20, 20, 5]
