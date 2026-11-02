"""Pure planning checks for envio repair (Full/free_shipping/Flex/colecta)."""

from __future__ import annotations

from types import SimpleNamespace

from app.services.publicacion_repair.envio import (
    has_colecta,
    has_flex,
    plan_envio_repair,
    sanitize_shipping_put,
    shipping_from_snapshot,
)


def _base(**overrides):
    data = {
        "mode": "me2",
        "logistic_type": "cross_docking",
        "local_pick_up": True,
        "free_shipping": False,
        "store_pick_up": False,
        "tags": ["self_service_in"],
    }
    data.update(overrides)
    return data


def test_ok_me2_colecta_flex_pickup_needs_no_write() -> None:
    plan = plan_envio_repair(_base())
    assert plan.skip_reason is None
    assert not plan.needs_write


def test_full_is_always_skipped() -> None:
    plan = plan_envio_repair(_base(logistic_type="fulfillment", tags=[]))
    assert plan.skip_reason == "full_fulfillment"
    assert not plan.needs_write


def test_incomplete_snapshot_skipped() -> None:
    plan = plan_envio_repair(
        {
            "mode": None,
            "logistic_type": None,
            "local_pick_up": None,
            "free_shipping": None,
            "store_pick_up": None,
            "tags": [],
        }
    )
    assert plan.skip_reason == "incomplete_snapshot"


def test_free_shipping_false_does_not_trigger_put() -> None:
    """free_shipping is observability-only: mismatch must not create a shipping PUT."""
    plan = plan_envio_repair(_base(free_shipping=False))
    assert "free_shipping" not in plan.shipping_put
    assert not plan.shipping_put or "free_shipping" not in plan.shipping_put
    # Already me2/colecta/flex/pickup — no write at all
    assert not plan.needs_write


def test_missing_flex_only_enables_flex_endpoint() -> None:
    plan = plan_envio_repair(_base(tags=["mandatory_free_shipping"]))
    assert plan.enable_flex is True
    assert plan.shipping_put == {}


def test_missing_me2_and_pickup_builds_safe_put() -> None:
    plan = plan_envio_repair(_base(mode="me1", local_pick_up=False, tags=["self_service_in"]))
    assert plan.shipping_put == {"mode": "me2", "local_pick_up": True}
    assert "free_shipping" not in plan.shipping_put
    assert "tags" not in plan.shipping_put
    assert plan.enable_flex is False


def test_drop_off_gets_colecta_but_not_when_flex_primary() -> None:
    plan_drop = plan_envio_repair(_base(logistic_type="drop_off", tags=["self_service_in"]))
    assert plan_drop.shipping_put.get("logistic_type") == "cross_docking"

    # Flex as primary logistic: do not replace with cross_docking; already has Flex.
    assert has_flex(_base(logistic_type="self_service", tags=[])) is True
    plan_flex_primary = plan_envio_repair(_base(logistic_type="self_service", tags=[]))
    assert "logistic_type" not in plan_flex_primary.shipping_put
    assert plan_flex_primary.enable_flex is False


def test_sanitize_strips_forbidden_keys() -> None:
    cleaned = sanitize_shipping_put({"mode": "me2", "free_shipping": True, "tags": ["x"], "local_pick_up": True})
    assert cleaned == {"mode": "me2", "local_pick_up": True}


def test_helpers_colecta_flex_from_snapshot() -> None:
    snap = SimpleNamespace(
        shipping_mode="me2",
        logistic_type="cross_docking",
        local_pick_up=True,
        free_shipping=False,
        store_pick_up=False,
        shipping_tags=["self_service_in"],
    )
    current = shipping_from_snapshot(snap)
    assert has_colecta(current)
    assert has_flex(current)
