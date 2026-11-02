"""Envio repair job: Full/free_shipping safety + Flex endpoint."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.services.ml_api_client import ShippingWriteResult
from app.services.publicacion_repair import envio as envio_mod


def _pub(mla: str, item_id: int = 1) -> SimpleNamespace:
    return SimpleNamespace(mla=mla, item_id=item_id)


def _snap(**overrides):
    base = dict(
        shipping_mode="me2",
        logistic_type="cross_docking",
        local_pick_up=True,
        free_shipping=False,
        store_pick_up=False,
        shipping_tags=["self_service_in"],
    )
    base.update(overrides)
    return SimpleNamespace(**base)


@pytest.fixture
def patched_tracker(monkeypatch: pytest.MonkeyPatch):
    run = SimpleNamespace(id=7)
    events: list[dict] = []
    monkeypatch.setattr(envio_mod, "start_run", lambda db, **kw: run)
    monkeypatch.setattr(envio_mod, "finish_run", lambda db, run_obj, **kw: setattr(run_obj, "stats", kw) or run_obj)
    monkeypatch.setattr(envio_mod, "record_event", lambda db, **kw: events.append(kw) or SimpleNamespace(**kw))
    monkeypatch.setattr(envio_mod.settings, "ML_PUB_KILL_SWITCH", False)
    monkeypatch.setattr(envio_mod.settings, "ML_ITEM_DATA_WRITE_ENABLED", True)
    return run, events


def test_free_shipping_mismatch_does_not_call_ml(monkeypatch: pytest.MonkeyPatch, patched_tracker) -> None:
    _run, events = patched_tracker
    monkeypatch.setattr(envio_mod, "linked_publicaciones", lambda db: [_pub("MLA_FS")])
    monkeypatch.setattr(
        envio_mod,
        "latest_snapshots_for_mlas",
        lambda db, mlas: {"MLA_FS": _snap(free_shipping=True)},
    )

    class Boom:
        async def put_item_shipping(self, *a, **k):
            raise AssertionError("must not PUT shipping for free_shipping-only drift")

        async def enable_item_flex(self, *a, **k):
            raise AssertionError("must not enable flex")

    stats = asyncio.run(envio_mod.run_envio_repair(MagicMock(), client=Boom()))
    assert stats["changed"] == 0
    assert events == []


def test_full_skipped_no_ml(monkeypatch: pytest.MonkeyPatch, patched_tracker) -> None:
    _run, events = patched_tracker
    monkeypatch.setattr(envio_mod, "linked_publicaciones", lambda db: [_pub("MLA_FULL")])
    monkeypatch.setattr(
        envio_mod,
        "latest_snapshots_for_mlas",
        lambda db, mlas: {"MLA_FULL": _snap(logistic_type="fulfillment", shipping_tags=[])},
    )

    class Boom:
        async def put_item_shipping(self, *a, **k):
            raise AssertionError("must not touch Full")

        async def enable_item_flex(self, *a, **k):
            raise AssertionError("must not touch Full")

    stats = asyncio.run(envio_mod.run_envio_repair(MagicMock(), client=Boom()))
    assert stats["skipped"] == 1
    assert events[0]["detail"] == "full_fulfillment"


def test_missing_flex_calls_flex_endpoint_only(monkeypatch: pytest.MonkeyPatch, patched_tracker) -> None:
    _run, events = patched_tracker
    monkeypatch.setattr(envio_mod, "linked_publicaciones", lambda db: [_pub("MLA_FLEX")])
    monkeypatch.setattr(
        envio_mod,
        "latest_snapshots_for_mlas",
        lambda db, mlas: {"MLA_FLEX": _snap(shipping_tags=[])},
    )
    puts: list[dict] = []
    flex: list[str] = []

    class Fake:
        async def put_item_shipping(self, mla, shipping):
            puts.append(shipping)
            return ShippingWriteResult(ok=True, status_code=200)

        async def enable_item_flex(self, mla, site_id="MLA"):
            flex.append(mla)
            return ShippingWriteResult(ok=True, status_code=204)

    stats = asyncio.run(envio_mod.run_envio_repair(MagicMock(), client=Fake()))
    assert puts == []
    assert flex == ["MLA_FLEX"]
    assert stats["changed"] == 1
    assert events[0]["action"] == "changed"


def test_me1_put_never_includes_free_shipping(monkeypatch: pytest.MonkeyPatch, patched_tracker) -> None:
    _run, events = patched_tracker
    monkeypatch.setattr(envio_mod, "linked_publicaciones", lambda db: [_pub("MLA_ME1")])
    monkeypatch.setattr(
        envio_mod,
        "latest_snapshots_for_mlas",
        lambda db, mlas: {
            "MLA_ME1": _snap(shipping_mode="me1", local_pick_up=False, shipping_tags=["self_service_in"])
        },
    )
    puts: list[dict] = []

    class Fake:
        async def put_item_shipping(self, mla, shipping):
            puts.append(shipping)
            return ShippingWriteResult(ok=True, status_code=200)

        async def enable_item_flex(self, *a, **k):
            raise AssertionError("flex already present")

    asyncio.run(envio_mod.run_envio_repair(MagicMock(), client=Fake()))
    assert puts == [{"mode": "me2", "local_pick_up": True}]
    assert "free_shipping" not in puts[0]


def test_kill_switch_blocks_all_writes(monkeypatch: pytest.MonkeyPatch, patched_tracker) -> None:
    run, events = patched_tracker
    monkeypatch.setattr(envio_mod.settings, "ML_PUB_KILL_SWITCH", True)
    monkeypatch.setattr(envio_mod, "linked_publicaciones", lambda db: [_pub("MLA_X")])

    class Boom:
        async def put_item_shipping(self, *a, **k):
            raise AssertionError("kill switch")

        async def enable_item_flex(self, *a, **k):
            raise AssertionError("kill switch")

    stats = asyncio.run(envio_mod.run_envio_repair(MagicMock(), client=Boom()))
    assert stats["scanned"] == 0
    assert run.stats["error_message"] == "ML_PUB_KILL_SWITCH=true"
    assert events == []
