"""Unit tests for Gestión Full PM ready / lock helpers (no DB)."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from app.services.gestion_full.pm_ready import (
    compute_qty_pm,
    mark_pm_ready,
    unlock_pm_ready,
)


def test_compute_qty_pm_prefers_override_capped_by_stock() -> None:
    assert compute_qty_pm(override=50, target=100, stock_full=10, stock_erp=40) == 40
    assert compute_qty_pm(override=20, target=100, stock_full=10, stock_erp=40) == 20


def test_compute_qty_pm_falls_back_to_sugerido() -> None:
    # sugerido = min(100-10, 40) = 40
    assert compute_qty_pm(override=None, target=100, stock_full=10, stock_erp=40) == 40


def test_compute_qty_pm_none_without_override_or_target() -> None:
    assert compute_qty_pm(override=None, target=None, stock_full=10, stock_erp=40) is None


def test_mark_pm_ready_idempotent_when_row_exists() -> None:
    existing = SimpleNamespace(
        producto_item_id=1,
        user_product_id="MLAU1",
        inventory_id="INV1",
        qty_pm=12,
    )
    db = MagicMock()
    usuario = SimpleNamespace(id=9)

    with patch(
        "app.services.gestion_full.pm_ready.get_pm_ready",
        return_value=existing,
    ):
        out = mark_pm_ready(
            db,
            producto_item_id=1,
            user_product_id="MLAU1",
            usuario=usuario,
        )

    assert out is existing
    db.add.assert_not_called()


def test_mark_pm_ready_rejects_without_qty() -> None:
    db = MagicMock()
    usuario = SimpleNamespace(id=1)

    with (
        patch("app.services.gestion_full.pm_ready.get_pm_ready", return_value=None),
        patch(
            "app.services.gestion_full.pm_ready.load_row_for_ready",
            return_value={
                "inventory_id": "INV1",
                "override": None,
                "target": None,
                "stock_full": 0,
                "stock_erp": 10,
            },
        ),
    ):
        with pytest.raises(ValueError, match="sin cantidad"):
            mark_pm_ready(
                db,
                producto_item_id=1,
                user_product_id="MLAU1",
                usuario=usuario,
            )


def test_mark_pm_ready_creates_row() -> None:
    db = MagicMock()
    db.get.return_value = None
    usuario = SimpleNamespace(id=3)

    with (
        patch("app.services.gestion_full.pm_ready.get_pm_ready", return_value=None),
        patch(
            "app.services.gestion_full.pm_ready.load_row_for_ready",
            return_value={
                "inventory_id": "INV9",
                "override": 15,
                "target": 100,
                "stock_full": 20,
                "stock_erp": 50,
            },
        ),
    ):
        row = mark_pm_ready(
            db,
            producto_item_id=7,
            user_product_id="MLAU9",
            usuario=usuario,
        )

    db.add.assert_called_once()
    db.commit.assert_called_once()
    assert row.producto_item_id == 7
    assert row.user_product_id == "MLAU9"
    assert row.inventory_id == "INV9"
    assert row.qty_pm == 15
    assert row.ready_by_id == 3


def test_unlock_pm_ready_noop_when_missing() -> None:
    db = MagicMock()
    with patch("app.services.gestion_full.pm_ready.get_pm_ready", return_value=None):
        assert unlock_pm_ready(db, producto_item_id=1, user_product_id="X") is False
    db.delete.assert_not_called()
