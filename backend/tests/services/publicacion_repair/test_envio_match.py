"""Pure drift checks for envio repair target constants."""

from __future__ import annotations

from types import SimpleNamespace

from app.services.publicacion_repair.constants import ENVIO_TARGET
from app.services.publicacion_repair.envio import (
    shipping_from_snapshot,
    shipping_matches_target,
    tags_match,
)


def test_tags_match_order_independent() -> None:
    assert tags_match(["mandatory_free_shipping", "self_service_in"])
    assert not tags_match(["self_service_in"])
    assert not tags_match(None)


def test_shipping_matches_target_ok() -> None:
    assert shipping_matches_target(dict(ENVIO_TARGET))


def test_shipping_matches_target_rejects_wrong_mode() -> None:
    bad = dict(ENVIO_TARGET)
    bad["mode"] = "me1"
    assert not shipping_matches_target(bad)


def test_shipping_from_snapshot_flattens_tags() -> None:
    snap = SimpleNamespace(
        shipping_mode="me2",
        logistic_type="cross_docking",
        local_pick_up=True,
        free_shipping=True,
        store_pick_up=False,
        shipping_tags=["self_service_in", "mandatory_free_shipping"],
    )
    current = shipping_from_snapshot(snap)
    assert shipping_matches_target(current)
