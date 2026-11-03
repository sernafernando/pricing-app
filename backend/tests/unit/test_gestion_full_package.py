"""Unit tests for Gestión Full package helpers (no DB)."""

from __future__ import annotations

import inspect
from datetime import date
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

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


def _pkg_lock_query(pkg: object) -> MagicMock:
    m = MagicMock()
    m.filter.return_value.populate_existing.return_value.with_for_update.return_value.one.return_value = pkg
    return m


def _add_all_query(
    *,
    pkg: object,
    ready_rows: list[object],
    package_lines: list[object],
    stock_rows: list[object],
) -> object:
    """MagicMock db.query router for batched add_all_ready_lines_to_package."""
    ready_q = MagicMock()
    ready_q.all.return_value = ready_rows
    stock_q = MagicMock()
    stock_q.filter.return_value.all.return_value = stock_rows
    line_q = MagicMock()
    line_q.filter.return_value.all.return_value = package_lines

    def _query(model: object) -> MagicMock:
        name = getattr(model, "__name__", "")
        if name == "GestionFullPmReady":
            return ready_q
        if name == "ProductoERP":
            return stock_q
        if name == "GestionFullPackageLine":
            return line_q
        return _pkg_lock_query(pkg)

    return _query


def test_upsert_package_line_creates() -> None:
    db = MagicMock()
    pkg = SimpleNamespace(id=9, status="open")
    line_q = MagicMock()
    line_q.filter_by.return_value.one_or_none.return_value = None

    def _query(model: object) -> MagicMock:
        name = getattr(model, "__name__", "")
        if name == "GestionFullPackageLine":
            return line_q
        return _pkg_lock_query(pkg)

    db.query.side_effect = _query
    db.get.return_value = SimpleNamespace(stock=100)
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
    from app.services.gestion_full.package import add_all_ready_lines_to_package

    pkg = SimpleNamespace(id=9, status="open", lines=[])
    db = MagicMock()
    ready = SimpleNamespace(
        producto_item_id=2,
        user_product_id="MLAU2",
        inventory_id="INV2",
        qty_pm=12,
    )
    db.query.side_effect = _add_all_query(
        pkg=pkg,
        ready_rows=[ready],
        package_lines=[],
        stock_rows=[SimpleNamespace(item_id=2, stock=100)],
    )
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
        patch(
            "app.services.gestion_full.assign_inbound.maybe_hard_lock",
            return_value=None,
        ) as lock,
    ):
        out_pkg, touched = add_all_ready_lines_to_package(db, usuario=usuario)
    assert out_pkg is pkg
    assert touched == 1
    db.add.assert_called_once()
    added = db.add.call_args[0][0]
    assert added.qty_export == 12
    lock.assert_called_once()
    db.commit.assert_called()


def test_add_all_ready_caps_auto_qty_export_to_stock() -> None:
    """Sumar Listo must not reset auto qty_export above ERP stock."""
    from app.services.gestion_full.package import add_all_ready_lines_to_package

    existing = SimpleNamespace(
        producto_item_id=2,
        user_product_id="MLAU2",
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
    db.query.side_effect = _add_all_query(
        pkg=pkg,
        ready_rows=[ready],
        package_lines=[existing],
        stock_rows=[SimpleNamespace(item_id=2, stock=3)],
    )
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
        patch(
            "app.services.gestion_full.assign_inbound.maybe_hard_lock",
            return_value=None,
        ),
    ):
        add_all_ready_lines_to_package(db, usuario=usuario)
    assert existing.qty_export == 3
    recap.assert_called_once()


def test_add_all_ready_exported_does_not_raise_when_stock_rises() -> None:
    """Round-3 #3: after export F6=3, stock→10, Sumar must keep qty_export at 3."""
    from app.services.gestion_full.package import add_all_ready_lines_to_package

    existing = SimpleNamespace(
        producto_item_id=2,
        user_product_id="MLAU2",
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
    db.query.side_effect = _add_all_query(
        pkg=pkg,
        ready_rows=[ready],
        package_lines=[existing],
        stock_rows=[SimpleNamespace(item_id=2, stock=10)],
    )
    with (
        patch(
            "app.services.gestion_full.package.get_or_create_open_package",
            return_value=pkg,
        ),
        patch(
            "app.services.gestion_full.excel_export.recap_qty_export_to_stock",
            return_value=0,
        ),
        patch(
            "app.services.gestion_full.assign_inbound.maybe_hard_lock",
            return_value=None,
        ),
    ):
        add_all_ready_lines_to_package(db, usuario=SimpleNamespace(id=1))
    assert existing.qty_export == 3


def test_add_all_ready_exported_skips_new_listo_lines() -> None:
    """After Excel download, new PM Listo rows wait for the next shipment."""
    from app.services.gestion_full.package import add_all_ready_lines_to_package

    existing = SimpleNamespace(
        producto_item_id=1,
        user_product_id="MLAU1",
        inventory_id="INV1",
        qty_pm=5,
        qty_export=5,
        qty_export_updated_by_id=None,
    )
    pkg = SimpleNamespace(id=9, status="exported", lines=[existing])
    db = MagicMock()
    ready_existing = SimpleNamespace(
        producto_item_id=1,
        user_product_id="MLAU1",
        inventory_id="INV1",
        qty_pm=5,
    )
    ready_new = SimpleNamespace(
        producto_item_id=2,
        user_product_id="MLAU2",
        inventory_id="INV2",
        qty_pm=6,
    )
    db.query.side_effect = _add_all_query(
        pkg=pkg,
        ready_rows=[ready_existing, ready_new],
        package_lines=[existing],
        stock_rows=[
            SimpleNamespace(item_id=1, stock=10),
            SimpleNamespace(item_id=2, stock=10),
        ],
    )
    with (
        patch(
            "app.services.gestion_full.package.get_or_create_open_package",
            return_value=pkg,
        ),
        patch(
            "app.services.gestion_full.excel_export.recap_qty_export_to_stock",
            return_value=0,
        ),
        patch(
            "app.services.gestion_full.assign_inbound.maybe_hard_lock",
            return_value=None,
        ),
    ):
        _pkg, touched = add_all_ready_lines_to_package(db, usuario=SimpleNamespace(id=1))
    assert touched == 1
    db.add.assert_not_called()
    db.flush.assert_called()
    db.expire.assert_called()


def test_add_all_ready_batches_stock_and_lines() -> None:
    """Fernando N+1: Sumar must preload stock + lines with IN, not per ready row."""
    from app.services.gestion_full import package as mod

    src = inspect.getsource(mod.add_all_ready_lines_to_package)
    assert "ProductoERP.item_id.in_" in src
    assert "GestionFullPackageLine.package_id" in src
    assert "_stock_erp_for_item" not in src


def test_package_locks_require_populate_existing() -> None:
    """Fernando please-check: removing `.populate_existing()` must fail this test."""
    from app.services.gestion_full import package as mod

    assert ".populate_existing()" in inspect.getsource(mod._package_for_update)
    assert ".populate_existing()" in inspect.getsource(mod.set_qty_export)


def test_set_qty_export_caps_and_audits() -> None:
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
    line_filter = MagicMock()
    line_filter.populate_existing.return_value.with_for_update.return_value.one.return_value = line
    pkg_query = _pkg_lock_query(pkg)
    pkg_filter = pkg_query.filter.return_value

    def _query(model: object) -> MagicMock:
        name = getattr(model, "__name__", "")
        if name == "GestionFullPackageLine":
            m = MagicMock()
            m.filter.return_value = line_filter
            return m
        return pkg_query

    db.query.side_effect = _query
    db.get.return_value = SimpleNamespace(stock=20)
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
    line_filter.populate_existing.assert_called()
    pkg_filter.populate_existing.assert_called()


def test_set_qty_export_noop_still_tries_hard_lock() -> None:
    """Round-3 #2: early return must not skip maybe_hard_lock."""
    from app.services.gestion_full.package import set_qty_export

    line = SimpleNamespace(
        id=5,
        package_id=1,
        qty_export=0,
        qty_export_reason=None,
        producto_item_id=99,
    )
    pkg = SimpleNamespace(id=1, status="exported")
    db = MagicMock()

    def _query(model: object) -> MagicMock:
        name = getattr(model, "__name__", "")
        if name == "GestionFullPackageLine":
            m = MagicMock()
            m.filter.return_value.populate_existing.return_value.with_for_update.return_value.one.return_value = line
            return m
        return _pkg_lock_query(pkg)

    db.query.side_effect = _query
    db.get.return_value = SimpleNamespace(stock=0)
    with patch(
        "app.services.gestion_full.assign_inbound.maybe_hard_lock",
        return_value=None,
    ) as lock:
        set_qty_export(db, line=line, qty_export=0, usuario=SimpleNamespace(id=2))
    lock.assert_called_once()
    db.commit.assert_called_once()
