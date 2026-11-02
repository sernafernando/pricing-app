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


def _lock_chain(db: MagicMock, pkg: object) -> None:
    db.query.return_value.filter.return_value.populate_existing.return_value.with_for_update.return_value.one.return_value = pkg


def test_upsert_package_line_creates() -> None:
    db = MagicMock()
    pkg = SimpleNamespace(id=9)
    _lock_chain(db, pkg)
    db.query.return_value.filter_by.return_value.one_or_none.return_value = None
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


def test_add_all_ready_lines_to_package() -> None:
    from unittest.mock import patch

    from app.services.gestion_full.package import add_all_ready_lines_to_package

    pkg = SimpleNamespace(id=9, status="open", lines=[])
    db = MagicMock()
    ready = SimpleNamespace(
        producto_item_id=2,
        user_product_id="MLAU2",
        inventory_id="INV2",
        qty_pm=12,
    )
    ready_q = MagicMock()
    ready_q.all.return_value = [ready]
    line_q = MagicMock()
    line_q.filter_by.return_value.one_or_none.return_value = None

    def _query(model: object) -> MagicMock:
        name = getattr(model, "__name__", "")
        if name == "GestionFullPmReady":
            return ready_q
        if name == "GestionFullPackageLine":
            return line_q
        m = MagicMock()
        m.filter.return_value.populate_existing.return_value.with_for_update.return_value.one.return_value = pkg
        return m

    db.query.side_effect = _query
    db.get.return_value = SimpleNamespace(stock=100)
    usuario = SimpleNamespace(id=1)
    with (
        patch(
            "app.services.gestion_full.package.get_or_create_open_package",
            return_value=pkg,
        ),
        patch(
            "app.services.gestion_full.excel_export.recap_qty_export_to_stock",
            return_value=0,
        ),
    ):
        out_pkg, touched = add_all_ready_lines_to_package(db, usuario=usuario)
    assert out_pkg is pkg
    assert touched == 1
    db.add.assert_called_once()
    added = db.add.call_args[0][0]
    assert added.qty_export == 12
    db.commit.assert_called()


def test_add_all_ready_caps_auto_qty_export_to_stock() -> None:
    """Sumar Listo must not reset auto qty_export above ERP stock (Fernando #2)."""
    from unittest.mock import patch

    from app.services.gestion_full.package import add_all_ready_lines_to_package

    existing = SimpleNamespace(
        inventory_id="INV2",
        qty_pm=20,
        qty_export=3,
        qty_export_updated_by_id=None,
    )
    pkg = SimpleNamespace(id=9, status="exported", lines=[existing])
    db = MagicMock()
    ready = SimpleNamespace(
        producto_item_id=2,
        user_product_id="MLAU2",
        inventory_id="INV2",
        qty_pm=20,
    )
    ready_q = MagicMock()
    ready_q.all.return_value = [ready]
    line_q = MagicMock()
    line_q.filter_by.return_value.one_or_none.return_value = existing

    def _query(model: object) -> MagicMock:
        name = getattr(model, "__name__", "")
        if name == "GestionFullPmReady":
            return ready_q
        if name == "GestionFullPackageLine":
            return line_q
        m = MagicMock()
        m.filter.return_value.populate_existing.return_value.with_for_update.return_value.one.return_value = pkg
        return m

    db.query.side_effect = _query
    db.get.return_value = SimpleNamespace(stock=3)
    usuario = SimpleNamespace(id=1)
    with (
        patch(
            "app.services.gestion_full.package.get_or_create_open_package",
            return_value=pkg,
        ),
        patch(
            "app.services.gestion_full.excel_export.recap_qty_export_to_stock",
            return_value=0,
        ) as recap,
    ):
        add_all_ready_lines_to_package(db, usuario=usuario)
    assert existing.qty_export == 3
    recap.assert_called_once()


def test_set_qty_export_caps_and_audits() -> None:
    from unittest.mock import patch

    from app.services.gestion_full.package import set_qty_export

    line = SimpleNamespace(
        id=5,
        package_id=1,
        package=SimpleNamespace(status="open"),
        qty_export=10,
        qty_export_reason=None,
        producto_item_id=99,
    )
    pkg = SimpleNamespace(id=1, status="open")
    db = MagicMock()
    _lock_chain(db, pkg)

    def _get(_model: object, key: object) -> object:
        if key == 99:
            return SimpleNamespace(stock=20)
        if key == 5:
            return line
        return None

    db.get.side_effect = _get
    usuario = SimpleNamespace(id=2)
    with patch(
        "app.services.gestion_full.assign_inbound.maybe_hard_lock",
        return_value=None,
    ) as lock:
        out = set_qty_export(
            db,
            line=line,
            qty_export=50,
            usuario=usuario,
            reason="ajuste",
            stock_erp=999,  # client value ignored
        )
    assert out.qty_export == 20
    assert out.qty_export_reason == "ajuste"
    assert db.add.call_count >= 1
    lock.assert_called_once()
    db.commit.assert_called_once()
