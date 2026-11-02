"""Envio repair job: only PUTs drifted linked pubs; classifies skip/error."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.services.ml_api_client import ShippingWriteResult
from app.services.publicacion_repair import envio as envio_mod
from app.services.publicacion_repair.constants import ENVIO_TARGET


def _pub(mla: str, item_id: int = 1) -> SimpleNamespace:
    return SimpleNamespace(mla=mla, item_id=item_id)


def _snap(**overrides):
    base = dict(
        shipping_mode="me2",
        logistic_type="cross_docking",
        local_pick_up=True,
        free_shipping=True,
        store_pick_up=False,
        shipping_tags=list(ENVIO_TARGET["tags"]),
    )
    base.update(overrides)
    return SimpleNamespace(**base)


@pytest.fixture
def patched_tracker(monkeypatch: pytest.MonkeyPatch):
    run = SimpleNamespace(id=7)
    events: list[dict] = []

    monkeypatch.setattr(envio_mod, "start_run", lambda db, **kw: run)

    def _finish(db, run_obj, **kw):
        run_obj.stats = kw
        return run_obj

    monkeypatch.setattr(envio_mod, "finish_run", _finish)

    def _record(db, **kw):
        events.append(kw)
        return SimpleNamespace(**kw)

    monkeypatch.setattr(envio_mod, "record_event", _record)
    return run, events


def test_run_envio_repair_skips_matching_and_fixes_drift(monkeypatch: pytest.MonkeyPatch, patched_tracker) -> None:
    _run, events = patched_tracker
    pubs = [_pub("MLA_OK"), _pub("MLA_DRIFT"), _pub("MLA_NOSNAP")]
    snaps = {
        "MLA_OK": _snap(),
        "MLA_DRIFT": _snap(free_shipping=False),
    }
    monkeypatch.setattr(envio_mod, "linked_publicaciones", lambda db: pubs)
    monkeypatch.setattr(envio_mod, "latest_snapshots_for_mlas", lambda db, mlas: snaps)

    calls: list[str] = []

    class FakeClient:
        async def put_item_shipping(self, mla_id: str, shipping: dict):
            calls.append(mla_id)
            return ShippingWriteResult(ok=True, status_code=200)

    stats = asyncio.run(envio_mod.run_envio_repair(MagicMock(), client=FakeClient()))

    assert calls == ["MLA_DRIFT"]
    assert stats["scanned"] == 3
    assert stats["changed"] == 1
    assert stats["skipped"] == 1  # no_snapshot
    assert stats["errors"] == 0
    actions = {e["mla_id"]: e["action"] for e in events}
    assert actions["MLA_DRIFT"] == "changed"
    assert actions["MLA_NOSNAP"] == "skipped"


def test_run_envio_repair_ml_not_allowed_is_skipped(monkeypatch: pytest.MonkeyPatch, patched_tracker) -> None:
    _run, events = patched_tracker
    monkeypatch.setattr(envio_mod, "linked_publicaciones", lambda db: [_pub("MLA_X")])
    monkeypatch.setattr(
        envio_mod,
        "latest_snapshots_for_mlas",
        lambda db, mlas: {"MLA_X": _snap(shipping_mode="custom")},
    )

    class FakeClient:
        async def put_item_shipping(self, mla_id: str, shipping: dict):
            return ShippingWriteResult(ok=False, status_code=400, not_allowed=True, detail="http_400")

    stats = asyncio.run(envio_mod.run_envio_repair(MagicMock(), client=FakeClient()))
    assert stats["skipped"] == 1
    assert stats["errors"] == 0
    assert events[0]["action"] == "skipped"
