"""SKU repair job: only PUTs drifted linked pubs vs ERP codigo."""

from __future__ import annotations

import asyncio

import pytest

from app.services.publicacion_repair import sku as sku_mod


@pytest.fixture
def patched_audit(monkeypatch: pytest.MonkeyPatch):
    events: list[dict] = []
    finish_kw: dict = {}
    refresh: list[str] = []
    logs: list[tuple] = []

    monkeypatch.setattr(sku_mod.repair_audit, "start_run_bg", lambda **kw: 9)

    def _finish(run_id, **kw):
        finish_kw.clear()
        finish_kw["run_id"] = run_id
        finish_kw.update(kw)

    monkeypatch.setattr(sku_mod.repair_audit, "finish_run_bg", _finish)
    monkeypatch.setattr(sku_mod.repair_audit, "record_event_bg", lambda **kw: events.append(kw))
    monkeypatch.setattr(
        sku_mod.repair_audit,
        "record_ml_write_log",
        lambda mla, action, payload: logs.append((mla, action, payload)),
    )
    monkeypatch.setattr(
        sku_mod.repair_audit,
        "enqueue_item_refresh_safely",
        lambda mla: refresh.append(mla),
    )
    monkeypatch.setattr(sku_mod.settings, "ML_PUB_KILL_SWITCH", False)
    monkeypatch.setattr(sku_mod.settings, "ML_ITEM_DATA_WRITE_ENABLED", True)
    return finish_kw, events, refresh, logs


def test_run_sku_repair_fixes_drift_only(monkeypatch: pytest.MonkeyPatch, patched_audit) -> None:
    _finish, events, refresh, logs = patched_audit
    monkeypatch.setattr(
        sku_mod,
        "_load_work_items",
        lambda db: [
            ("MLA_OK", 1, "111", "111", "active"),
            ("MLA_DRIFT", 2, None, "840006603337", "active"),
            ("MLA_CLOSED", 3, "old", "222", "closed"),
        ],
    )

    calls: list[tuple[str, dict]] = []

    class FakeClient:
        async def put_item_data(self, mla: str, body: dict):
            calls.append((mla, body))
            return {"ok": True, "status_code": 200, "ambiguous": False, "body": {}}

    stats = asyncio.run(sku_mod.run_sku_repair(client=FakeClient(), pacing_seconds=0))

    assert calls == [("MLA_DRIFT", {"attributes": [{"id": "SELLER_SKU", "value_name": "840006603337"}]})]
    assert stats["scanned"] == 3
    assert stats["changed"] == 1
    assert stats["skipped"] == 1
    assert refresh == ["MLA_DRIFT"]
    actions = {e["mla_id"]: e["action"] for e in events}
    assert actions["MLA_DRIFT"] == "changed"
    assert actions["MLA_CLOSED"] == "skipped"


def test_run_sku_repair_kill_switch(monkeypatch: pytest.MonkeyPatch, patched_audit) -> None:
    finish_kw, events, *_ = patched_audit
    monkeypatch.setattr(sku_mod.settings, "ML_PUB_KILL_SWITCH", True)

    class Boom:
        async def put_item_data(self, *a, **k):
            raise AssertionError("must not write")

    stats = asyncio.run(sku_mod.run_sku_repair(client=Boom(), pacing_seconds=0))
    assert stats["scanned"] == 0
    assert events == []
    assert finish_kw["error_message"] == "ML_PUB_KILL_SWITCH=true"


def test_run_sku_repair_disabled_writes_nothing(monkeypatch: pytest.MonkeyPatch, patched_audit) -> None:
    finish_kw, events, *_ = patched_audit
    monkeypatch.setattr(sku_mod.settings, "ML_ITEM_DATA_WRITE_ENABLED", False)

    class Boom:
        async def put_item_data(self, *a, **k):
            raise AssertionError("must not write")

    stats = asyncio.run(sku_mod.run_sku_repair(client=Boom(), pacing_seconds=0))
    assert stats["scanned"] == 0
    assert events == []
    assert finish_kw["error_message"] == "ML_ITEM_DATA_WRITE_ENABLED=false"


def test_run_sku_repair_ml_reject_is_skipped(monkeypatch: pytest.MonkeyPatch, patched_audit) -> None:
    _finish, events, *_ = patched_audit
    monkeypatch.setattr(
        sku_mod,
        "_load_work_items",
        lambda db: [("MLA_X", 1, "old", "999", "active")],
    )

    class FakeClient:
        async def put_item_data(self, mla: str, body: dict):
            return {
                "ok": False,
                "status_code": 400,
                "ambiguous": False,
                "body": {"data_write": "not_attempted", "message": "nope"},
            }

    stats = asyncio.run(sku_mod.run_sku_repair(client=FakeClient(), pacing_seconds=0))
    assert stats["skipped"] == 1
    assert events[0]["action"] == "skipped"
