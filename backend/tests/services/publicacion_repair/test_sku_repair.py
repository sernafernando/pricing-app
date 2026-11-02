"""SKU repair job: only PUTs drifted linked pubs vs ERP codigo."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.services.publicacion_repair import sku as sku_mod


def _pub(mla: str, item_id: int = 1) -> SimpleNamespace:
    return SimpleNamespace(mla=mla, item_id=item_id)


@pytest.fixture
def patched_tracker(monkeypatch: pytest.MonkeyPatch):
    run = SimpleNamespace(id=9)
    events: list[dict] = []
    monkeypatch.setattr(sku_mod, "start_run", lambda db, **kw: run)
    monkeypatch.setattr(sku_mod, "finish_run", lambda db, run_obj, **kw: setattr(run_obj, "stats", kw) or run_obj)
    monkeypatch.setattr(sku_mod, "record_event", lambda db, **kw: events.append(kw) or SimpleNamespace(**kw))
    return run, events


def test_run_sku_repair_fixes_drift_only(monkeypatch: pytest.MonkeyPatch, patched_tracker) -> None:
    _run, events = patched_tracker
    monkeypatch.setattr(sku_mod.settings, "ML_ITEM_DATA_WRITE_ENABLED", True)
    monkeypatch.setattr(
        sku_mod,
        "linked_pubs_with_erp_codigo",
        lambda db: [
            (_pub("MLA_OK"), "111"),
            (_pub("MLA_DRIFT"), "840006603337"),
            (_pub("MLA_NOSNAP"), "222"),
        ],
    )
    monkeypatch.setattr(
        sku_mod,
        "latest_snapshots_for_mlas",
        lambda db, mlas: {
            "MLA_OK": SimpleNamespace(seller_sku="111"),
            "MLA_DRIFT": SimpleNamespace(seller_sku=None),
        },
    )

    calls: list[tuple[str, dict]] = []

    class FakeClient:
        async def put_item_data(self, mla: str, body: dict):
            calls.append((mla, body))
            return {"ok": True, "status_code": 200, "ambiguous": False, "body": {}}

    stats = asyncio.run(sku_mod.run_sku_repair(MagicMock(), client=FakeClient()))

    assert calls == [("MLA_DRIFT", {"attributes": [{"id": "SELLER_SKU", "value_name": "840006603337"}]})]
    assert stats == {"scanned": 3, "changed": 1, "skipped": 1, "errors": 0}
    actions = {e["mla_id"]: e["action"] for e in events}
    assert actions["MLA_DRIFT"] == "changed"
    assert actions["MLA_NOSNAP"] == "skipped"


def test_run_sku_repair_disabled_writes_nothing(monkeypatch: pytest.MonkeyPatch, patched_tracker) -> None:
    run, events = patched_tracker
    monkeypatch.setattr(sku_mod.settings, "ML_ITEM_DATA_WRITE_ENABLED", False)

    class Boom:
        async def put_item_data(self, *a, **k):
            raise AssertionError("must not write")

    stats = asyncio.run(sku_mod.run_sku_repair(MagicMock(), client=Boom()))
    assert stats["scanned"] == 0
    assert events == []
    assert run.stats["error_message"] == "ML_ITEM_DATA_WRITE_ENABLED=false"


def test_run_sku_repair_ml_reject_is_skipped(monkeypatch: pytest.MonkeyPatch, patched_tracker) -> None:
    _run, events = patched_tracker
    monkeypatch.setattr(sku_mod.settings, "ML_ITEM_DATA_WRITE_ENABLED", True)
    monkeypatch.setattr(
        sku_mod,
        "linked_pubs_with_erp_codigo",
        lambda db: [(_pub("MLA_X"), "999")],
    )
    monkeypatch.setattr(
        sku_mod,
        "latest_snapshots_for_mlas",
        lambda db, mlas: {"MLA_X": SimpleNamespace(seller_sku="old")},
    )

    class FakeClient:
        async def put_item_data(self, mla: str, body: dict):
            return {
                "ok": False,
                "status_code": 400,
                "ambiguous": False,
                "body": {"data_write": "not_attempted", "message": "nope"},
            }

    stats = asyncio.run(sku_mod.run_sku_repair(MagicMock(), client=FakeClient()))
    assert stats["skipped"] == 1
    assert events[0]["action"] == "skipped"
