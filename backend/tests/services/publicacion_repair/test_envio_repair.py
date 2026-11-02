"""Envio repair job: Full/free_shipping safety + Flex endpoint + short sessions."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.services.ml_api_client import ShippingWriteResult
from app.services.publicacion_repair import envio as envio_mod


def _shipping(**overrides):
    base = {
        "mode": "me2",
        "logistic_type": "cross_docking",
        "local_pick_up": True,
        "free_shipping": False,
        "store_pick_up": False,
        "tags": ["self_service_in"],
    }
    base.update(overrides)
    return base


@pytest.fixture
def patched_audit(monkeypatch: pytest.MonkeyPatch):
    run = SimpleNamespace(id=7)
    events: list[dict] = []
    shipping_logs: list[tuple] = []
    flex_logs: list[str] = []

    monkeypatch.setattr(envio_mod.repair_audit, "start_run_bg", lambda **kw: run)

    def _finish(run_obj, **kw):
        run_obj.stats = kw
        return run_obj

    monkeypatch.setattr(envio_mod.repair_audit, "finish_run_bg", _finish)
    monkeypatch.setattr(envio_mod.repair_audit, "record_event_bg", lambda **kw: events.append(kw))
    monkeypatch.setattr(
        envio_mod.repair_audit,
        "after_shipping_changed",
        lambda mla, payload: shipping_logs.append((mla, payload)),
    )
    monkeypatch.setattr(
        envio_mod.repair_audit,
        "after_flex_enabled",
        lambda mla: flex_logs.append(mla),
    )
    monkeypatch.setattr(envio_mod.settings, "ML_PUB_KILL_SWITCH", False)
    monkeypatch.setattr(envio_mod.settings, "ML_ITEM_DATA_WRITE_ENABLED", True)
    return run, events, shipping_logs, flex_logs


def test_free_shipping_mismatch_does_not_call_ml(monkeypatch: pytest.MonkeyPatch, patched_audit) -> None:
    _run, events, *_ = patched_audit
    monkeypatch.setattr(
        envio_mod,
        "_load_work_items",
        lambda db: [("MLA_FS", 1, _shipping(free_shipping=True))],
    )

    class Boom:
        async def put_item_shipping(self, *a, **k):
            raise AssertionError("must not PUT shipping for free_shipping-only drift")

        async def enable_item_flex(self, *a, **k):
            raise AssertionError("must not enable flex")

    stats = asyncio.run(envio_mod.run_envio_repair(MagicMock(), client=Boom(), pacing_seconds=0))
    assert stats["changed"] == 0
    assert events == []


def test_full_skipped_no_ml(monkeypatch: pytest.MonkeyPatch, patched_audit) -> None:
    _run, events, *_ = patched_audit
    monkeypatch.setattr(
        envio_mod,
        "_load_work_items",
        lambda db: [("MLA_FULL", 1, _shipping(logistic_type="fulfillment", tags=[]))],
    )

    class Boom:
        async def put_item_shipping(self, *a, **k):
            raise AssertionError("must not touch Full")

        async def enable_item_flex(self, *a, **k):
            raise AssertionError("must not touch Full")

    stats = asyncio.run(envio_mod.run_envio_repair(MagicMock(), client=Boom(), pacing_seconds=0))
    assert stats["skipped"] == 1
    assert events[0]["detail"] == "full_fulfillment"


def test_missing_flex_calls_flex_and_write_log(monkeypatch: pytest.MonkeyPatch, patched_audit) -> None:
    _run, events, shipping_logs, flex_logs = patched_audit
    monkeypatch.setattr(
        envio_mod,
        "_load_work_items",
        lambda db: [("MLA_FLEX", 1, _shipping(tags=[]))],
    )
    puts: list[dict] = []

    class Fake:
        async def put_item_shipping(self, mla, shipping):
            puts.append(shipping)
            return ShippingWriteResult(ok=True, status_code=200)

        async def enable_item_flex(self, mla, site_id="MLA"):
            return ShippingWriteResult(ok=True, status_code=204)

    stats = asyncio.run(envio_mod.run_envio_repair(MagicMock(), client=Fake(), pacing_seconds=0))
    assert puts == []
    assert flex_logs == ["MLA_FLEX"]
    assert shipping_logs == []
    assert stats["changed"] == 1
    assert events[0]["action"] == "changed"


def test_me1_put_logs_shipping_without_free_shipping(monkeypatch: pytest.MonkeyPatch, patched_audit) -> None:
    _run, events, shipping_logs, flex_logs = patched_audit
    monkeypatch.setattr(
        envio_mod,
        "_load_work_items",
        lambda db: [
            (
                "MLA_ME1",
                1,
                _shipping(mode="me1", local_pick_up=False, tags=["self_service_in"]),
            )
        ],
    )

    class Fake:
        async def put_item_shipping(self, mla, shipping):
            return ShippingWriteResult(ok=True, status_code=200)

        async def enable_item_flex(self, *a, **k):
            raise AssertionError("flex already present")

    asyncio.run(envio_mod.run_envio_repair(MagicMock(), client=Fake(), pacing_seconds=0))
    assert shipping_logs == [("MLA_ME1", {"mode": "me2", "local_pick_up": True})]
    assert flex_logs == []


def test_kill_switch_blocks_all_writes(monkeypatch: pytest.MonkeyPatch, patched_audit) -> None:
    run, events, *_ = patched_audit
    monkeypatch.setattr(envio_mod.settings, "ML_PUB_KILL_SWITCH", True)

    class Boom:
        async def put_item_shipping(self, *a, **k):
            raise AssertionError("kill switch")

        async def enable_item_flex(self, *a, **k):
            raise AssertionError("kill switch")

    stats = asyncio.run(envio_mod.run_envio_repair(MagicMock(), client=Boom(), pacing_seconds=0))
    assert stats["scanned"] == 0
    assert run.stats["error_message"] == "ML_PUB_KILL_SWITCH=true"
    assert events == []


def test_max_writes_cap(monkeypatch: pytest.MonkeyPatch, patched_audit) -> None:
    _run, events, shipping_logs, _flex = patched_audit
    monkeypatch.setattr(
        envio_mod,
        "_load_work_items",
        lambda db: [
            ("MLA_A", 1, _shipping(mode="me1", tags=["self_service_in"])),
            ("MLA_B", 2, _shipping(mode="me1", tags=["self_service_in"])),
        ],
    )

    class Fake:
        async def put_item_shipping(self, mla, shipping):
            return ShippingWriteResult(ok=True, status_code=200)

        async def enable_item_flex(self, *a, **k):
            raise AssertionError("no flex")

    stats = asyncio.run(
        envio_mod.run_envio_repair(MagicMock(), client=Fake(), max_writes=1, pacing_seconds=0)
    )
    assert stats["changed"] == 1
    assert stats["skipped"] == 1
    assert any(e.get("detail") == "max_writes_cap" for e in events)
