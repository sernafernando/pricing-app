"""The three publication sync scripts call `/items/bulk` (ML deprecates `/items?ids=` on 2026-10-25)
and parse the bulk (`status_code`) and legacy (`code`) shapes.

Fixtures: real capture `tests/fixtures/ml/items_bulk_capture_20261006.json`.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from app.scripts import sync_ml_publications, sync_ml_publications_full, sync_ml_publications_incremental

CAPTURE = Path(__file__).resolve().parent.parent / "fixtures" / "ml" / "items_bulk_capture_20261006.json"
IDS = ["MLA935110613", "MLA934406852", "MLA1"]


def _call(name: str) -> list:
    data = json.loads(CAPTURE.read_text(encoding="utf-8"))
    return next(c["body"] for c in data["calls"] if c["name"] == name)


def _fake_meli(response: list, endpoints: list[str]):
    async def fake(*args, **kwargs):
        endpoints.append([a for a in args if isinstance(a, str)][0])
        return response

    return fake


async def _no_sleep(*_a, **_k) -> None:
    return None


@pytest.mark.parametrize("fixture", ["bulk_full", "legacy_multiget"])
def test_sync_ml_publications(monkeypatch: pytest.MonkeyPatch, fixture: str) -> None:
    endpoints: list[str] = []
    monkeypatch.setattr(sync_ml_publications, "call_meli", _fake_meli(_call(fixture), endpoints))
    monkeypatch.setattr(sync_ml_publications.asyncio, "sleep", _no_sleep)

    saved = asyncio.run(sync_ml_publications.traer_detalles_batch(IDS, MagicMock()))

    assert endpoints == [f"/items/bulk?ids={','.join(IDS)}"]
    assert saved == 2


@pytest.mark.parametrize("fixture", ["bulk_full", "legacy_multiget"])
def test_sync_ml_publications_incremental(monkeypatch: pytest.MonkeyPatch, fixture: str) -> None:
    endpoints: list[str] = []
    mod = sync_ml_publications_incremental
    monkeypatch.setattr(mod, "call_meli", _fake_meli(_call(fixture), endpoints))
    monkeypatch.setattr(mod.asyncio, "sleep", _no_sleep)
    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = None

    saved, updated = asyncio.run(mod.traer_detalles_batch(IDS, db))

    assert endpoints == [f"/items/bulk?ids={','.join(IDS)}"]
    assert (saved, updated) == (2, 0)


@pytest.mark.parametrize("fixture", ["bulk_full", "legacy_multiget"])
def test_sync_ml_publications_full(monkeypatch: pytest.MonkeyPatch, fixture: str) -> None:
    endpoints: list[str] = []
    mod = sync_ml_publications_full
    monkeypatch.setattr(mod, "call_meli", _fake_meli(_call(fixture), endpoints))
    monkeypatch.setattr(mod.asyncio, "sleep", _no_sleep)

    saved, updated, errors, detail = asyncio.run(mod.procesar_batch(IDS, MagicMock(), 1, 1, MagicMock(), {}))

    assert endpoints == [f"/items/bulk?ids={','.join(IDS)}"]
    assert (saved, updated, errors) == (2, 0, 1)
    assert "404" in detail[0]
