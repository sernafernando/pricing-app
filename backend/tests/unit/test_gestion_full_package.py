"""Unit tests for Gestión Full package helpers (no DB)."""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.services.gestion_full.package import (
    get_or_create_open_package,
    upsert_package_line,
    week_monday_on,
)


def test_week_monday_on() -> None:
    assert week_monday_on(date(2026, 10, 31)) == date(2026, 10, 26)  # Saturday → Mon
    assert week_monday_on(date(2026, 10, 26)) == date(2026, 10, 26)


def test_get_or_create_returns_existing_active() -> None:
    existing = SimpleNamespace(id=3, status="open")
    db = MagicMock()
    db.query.return_value.filter.return_value.order_by.return_value.first.return_value = existing
    usuario = SimpleNamespace(id=1)

    out = get_or_create_open_package(db, usuario=usuario, on_day=date(2026, 10, 31))
    assert out is existing
    db.add.assert_not_called()


def test_upsert_package_line_rejects_negative() -> None:
    db = MagicMock()
    pkg = SimpleNamespace(id=1)
    with pytest.raises(ValueError, match="qty_pm"):
        upsert_package_line(
            db,
            package=pkg,
            producto_item_id=1,
            user_product_id="MLAU",
            inventory_id="INV",
            qty_pm=-1,
        )


def test_upsert_package_line_creates() -> None:
    db = MagicMock()
    db.query.return_value.filter_by.return_value.one_or_none.return_value = None
    pkg = SimpleNamespace(id=9)
    line = upsert_package_line(
        db,
        package=pkg,
        producto_item_id=2,
        user_product_id="MLAU2",
        inventory_id="INV2",
        qty_pm=12,
    )
    db.add.assert_called_once()
    db.commit.assert_called_once()
    assert line.qty_pm == 12
    assert line.qty_export == 12


def test_set_qty_export_caps_and_audits() -> None:
    from app.services.gestion_full.package import set_qty_export

    line = SimpleNamespace(
        id=5,
        package_id=1,
        package=SimpleNamespace(status="open"),
        qty_export=10,
        qty_export_reason=None,
    )
    db = MagicMock()
    usuario = SimpleNamespace(id=2)
    out = set_qty_export(
        db,
        line=line,
        qty_export=50,
        usuario=usuario,
        reason="ajuste",
        stock_erp=20,
    )
    assert out.qty_export == 20
    assert out.qty_export_reason == "ajuste"
    assert db.add.call_count >= 1
    db.commit.assert_called_once()
