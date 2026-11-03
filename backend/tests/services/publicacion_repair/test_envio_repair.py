"""Envio repair job: Full/free_shipping safety + Flex endpoint + short sessions."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

from app.services.ml_api_client import ShippingWriteResult
from app.services.publicacion_repair import envio as envio_mod


def _fresh() -> datetime:
    return datetime.now(timezone.utc)


def _shipping(**overrides):
    base = {
        "mode": "me2",
        "logistic_type": "cross_docking",
        "local_pick_up": True,
        "free_shipping": False,
        "store_pick_up": False,
        "tags": ["self_service_in"],
        "status": "active",
        "fetched_at": _fresh(),
    }
    base.update(overrides)
    return base


@pytest.fixture
def patched_audit(monkeypatch: pytest.MonkeyPatch):
    events: list[dict] = []
    shipping_logs: list[tuple] = []
    flex_logs: list[str] = []
    finish_kw: dict = {}

    monkeypatch.setattr(envio_mod.repair_audit, "start_run_bg", lambda **kw: 7)

    def _finish(run_id, **kw):
        finish_kw.clear()
        finish_kw["run_id"] = run_id
        finish_kw.update(kw)

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
    monkeypatch.setattr(envio_mod, "latest_flex_refusal_fingerprints", lambda db, mlas: {})
    return finish_kw, events, shipping_logs, flex_logs


def test_closed_status_skipped(monkeypatch: pytest.MonkeyPatch, patched_audit) -> None:
    _finish, events, *_ = patched_audit
    monkeypatch.setattr(
        envio_mod,
        "_load_work_items",
        lambda db: [("MLA_CLOSED", 1, _shipping(status="closed", mode="me1"))],
    )

    class Boom:
        async def put_item_shipping(self, *a, **k):
            raise AssertionError("must not write closed")

        async def enable_item_flex(self, *a, **k):
            raise AssertionError("must not write closed")

    stats = asyncio.run(envio_mod.run_envio_repair(client=Boom(), pacing_seconds=0))
    assert stats["skipped"] == 1
    assert events[0]["detail"] == "status_not_modifiable"


def test_free_shipping_mismatch_does_not_call_ml(monkeypatch: pytest.MonkeyPatch, patched_audit) -> None:
    _finish, events, *_ = patched_audit
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

    stats = asyncio.run(envio_mod.run_envio_repair(client=Boom(), pacing_seconds=0))
    assert stats["changed"] == 0
    assert events == []


def test_full_skipped_no_ml(monkeypatch: pytest.MonkeyPatch, patched_audit) -> None:
    _finish, events, *_ = patched_audit
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

    stats = asyncio.run(envio_mod.run_envio_repair(client=Boom(), pacing_seconds=0))
    assert stats["skipped"] == 1
    assert events[0]["detail"] == "full_fulfillment"


def test_missing_flex_calls_flex_and_write_log(monkeypatch: pytest.MonkeyPatch, patched_audit) -> None:
    _finish, events, shipping_logs, flex_logs = patched_audit
    monkeypatch.setattr(
        envio_mod,
        "_load_work_items",
        lambda db: [("MLA_FLEX", 1, _shipping(tags=[]))],
    )

    class Fake:
        async def put_item_shipping(self, mla, shipping):
            raise AssertionError("no shipping put needed")

        async def enable_item_flex(self, mla, site_id="MLA"):
            return ShippingWriteResult(ok=True, status_code=204)

    stats = asyncio.run(envio_mod.run_envio_repair(client=Fake(), pacing_seconds=0))
    assert flex_logs == ["MLA_FLEX"]
    assert shipping_logs == []
    assert stats["changed"] == 1
    assert events[0]["action"] == "changed"


def test_me1_put_logs_shipping_without_free_shipping(monkeypatch: pytest.MonkeyPatch, patched_audit) -> None:
    _finish, events, shipping_logs, flex_logs = patched_audit
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

    asyncio.run(envio_mod.run_envio_repair(client=Fake(), pacing_seconds=0))
    assert shipping_logs == [("MLA_ME1", {"mode": "me2", "local_pick_up": True})]
    assert flex_logs == []


def test_kill_switch_blocks_all_writes(monkeypatch: pytest.MonkeyPatch, patched_audit) -> None:
    finish_kw, events, *_ = patched_audit
    monkeypatch.setattr(envio_mod.settings, "ML_PUB_KILL_SWITCH", True)

    class Boom:
        async def put_item_shipping(self, *a, **k):
            raise AssertionError("kill switch")

        async def enable_item_flex(self, *a, **k):
            raise AssertionError("kill switch")

    stats = asyncio.run(envio_mod.run_envio_repair(client=Boom(), pacing_seconds=0))
    assert stats["scanned"] == 0
    assert finish_kw["error_message"] == "ML_PUB_KILL_SWITCH=true"
    assert events == []


def test_before_write_false_stops_run(monkeypatch: pytest.MonkeyPatch, patched_audit) -> None:
    _finish, events, *_ = patched_audit
    monkeypatch.setattr(
        envio_mod,
        "_load_work_items",
        lambda db: [
            ("MLA_A", 1, _shipping(mode="me1", tags=["self_service_in"])),
            ("MLA_B", 2, _shipping(mode="me1", tags=["self_service_in"])),
        ],
    )
    puts: list[str] = []

    class Fake:
        async def put_item_shipping(self, mla, shipping):
            puts.append(mla)
            return ShippingWriteResult(ok=True, status_code=200)

        async def enable_item_flex(self, *a, **k):
            raise AssertionError("no flex")

    stats = asyncio.run(
        envio_mod.run_envio_repair(
            client=Fake(),
            pacing_seconds=0,
            before_write=lambda: False,
        )
    )
    assert puts == []
    assert any(e.get("detail") == "pacer_deadline" for e in events)
    assert stats["skipped"] >= 1


def test_max_writes_cap_counts_attempts(monkeypatch: pytest.MonkeyPatch, patched_audit) -> None:
    """Cap counts items we attempt, including Flex refusals — not only full success."""
    _finish, events, shipping_logs, _flex = patched_audit
    monkeypatch.setattr(
        envio_mod,
        "_load_work_items",
        lambda db: [
            ("MLA_A", 1, _shipping(mode="me1", tags=["self_service_in"])),
            ("MLA_B", 2, _shipping(mode="me1", tags=["self_service_in"])),
        ],
    )
    puts: list[str] = []

    class Fake:
        async def put_item_shipping(self, mla, shipping):
            puts.append(mla)
            return ShippingWriteResult(ok=True, status_code=200)

        async def enable_item_flex(self, *a, **k):
            raise AssertionError("no flex")

    stats = asyncio.run(
        envio_mod.run_envio_repair(client=Fake(), max_writes=1, pacing_seconds=0)
    )
    assert puts == ["MLA_A"]
    assert stats["changed"] == 1
    assert stats["skipped"] == 1
    assert any(e.get("detail") == "max_writes_cap" for e in events)


def test_flex_refusal_is_recorded_with_fingerprint(monkeypatch: pytest.MonkeyPatch, patched_audit) -> None:
    _finish, events, *_ = patched_audit
    current = _shipping(tags=[])  # needs Flex enable; shipping already ME2/colecta/pickup
    monkeypatch.setattr(envio_mod, "_load_work_items", lambda db: [("MLA_FLEX", 1, current)])

    class Fake:
        async def put_item_shipping(self, *a, **k):
            raise AssertionError("no shipping put expected")

        async def enable_item_flex(self, mla: str):
            return ShippingWriteResult(ok=False, status_code=400, not_allowed=True, detail="flex blocked")

    stats = asyncio.run(envio_mod.run_envio_repair(client=Fake(), pacing_seconds=0))
    assert stats["skipped"] == 1
    assert events[0]["detail"] == envio_mod.DETAIL_FLEX_REFUSED
    assert events[0]["after"]["fingerprint"] == envio_mod.ml_item_shipping_fingerprint(current)
    assert events[0]["after"]["ml_detail"] == "flex blocked"


def test_flex_refusal_skips_while_ml_items_unchanged(monkeypatch: pytest.MonkeyPatch, patched_audit) -> None:
    _finish, events, *_ = patched_audit
    current = _shipping(tags=[])
    fp = envio_mod.ml_item_shipping_fingerprint(current)
    monkeypatch.setattr(envio_mod, "_load_work_items", lambda db: [("MLA_FLEX", 1, current)])
    monkeypatch.setattr(
        envio_mod,
        "latest_flex_refusal_fingerprints",
        lambda db, mlas: {"MLA_FLEX": fp},
    )

    class Boom:
        async def put_item_shipping(self, *a, **k):
            raise AssertionError("must not write after flex refusal cache hit")

        async def enable_item_flex(self, *a, **k):
            raise AssertionError("must not re-POST Flex while ml_items unchanged")

    stats = asyncio.run(envio_mod.run_envio_repair(client=Boom(), pacing_seconds=0))
    assert stats["skipped"] == 1
    assert events[0]["detail"] == envio_mod.DETAIL_FLEX_REFUSED_UNCHANGED


def test_flex_refusal_retries_when_ml_items_fingerprint_changes(
    monkeypatch: pytest.MonkeyPatch, patched_audit
) -> None:
    _finish, events, _shipping_logs, flex_logs = patched_audit
    current = _shipping(tags=[])
    monkeypatch.setattr(envio_mod, "_load_work_items", lambda db: [("MLA_FLEX", 1, current)])
    monkeypatch.setattr(
        envio_mod,
        "latest_flex_refusal_fingerprints",
        lambda db, mlas: {"MLA_FLEX": "stale-fingerprint"},
    )
    flex_calls: list[str] = []

    class Fake:
        async def put_item_shipping(self, *a, **k):
            raise AssertionError("no shipping put")

        async def enable_item_flex(self, mla: str):
            flex_calls.append(mla)
            return ShippingWriteResult(ok=True, status_code=204)

    stats = asyncio.run(envio_mod.run_envio_repair(client=Fake(), pacing_seconds=0))
    assert flex_calls == ["MLA_FLEX"]
    assert stats["changed"] == 1
    assert flex_logs == ["MLA_FLEX"]
