"""Unit tests for Gestión Full Excel helpers (no DB / no template IO)."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from openpyxl import Workbook

from app.services.gestion_full.excel_export import (
    _mla_digits,
    _write_text_cell,
    assert_package_exportable,
)


def test_mla_digits_strips_prefix() -> None:
    assert _mla_digits("MLA1173239744") == "1173239744"
    assert _mla_digits("1173239744") == "1173239744"
    assert _mla_digits("MLAU123") is None
    assert _mla_digits(None) is None


def test_assert_package_exportable_locked() -> None:
    db = MagicMock()
    pkg = SimpleNamespace(status="locked", lines=[])
    with pytest.raises(ValueError, match="hard-locked"):
        assert_package_exportable(db, pkg)


def test_assert_package_exportable_inbound_blocks_regen() -> None:
    db = MagicMock()
    pkg = SimpleNamespace(
        status="exported",
        lines=[SimpleNamespace(inbound_id="99", qty_export=1, producto_item_id=1)],
    )
    with pytest.raises(ValueError, match="inbound_id"):
        assert_package_exportable(db, pkg)


def test_assert_package_exportable_requires_caja() -> None:
    db = MagicMock()
    db.get.return_value = None
    pkg = SimpleNamespace(
        status="open",
        lines=[SimpleNamespace(inbound_id=None, qty_export=2, producto_item_id=7)],
    )
    with pytest.raises(ValueError, match="unidades/caja"):
        assert_package_exportable(db, pkg)


def test_write_text_cell_forces_string_not_formula() -> None:
    """Values starting with '=' must not become Excel formulas (injection)."""
    wb = Workbook()
    ws = wb.active
    dangerous = '=HYPERLINK("http://evil.example","x")'
    _write_text_cell(ws, 1, 1, dangerous)
    cell = ws.cell(1, 1)
    assert cell.value == dangerous
    assert cell.data_type == "s"
    assert cell.data_type != "f"


def test_recap_qty_export_to_stock() -> None:
    from app.services.gestion_full.excel_export import recap_qty_export_to_stock

    ln_hi = SimpleNamespace(producto_item_id=1, qty_export=20)
    ln_ok = SimpleNamespace(producto_item_id=2, qty_export=3)
    pkg = SimpleNamespace(lines=[ln_hi, ln_ok])
    db = MagicMock()

    def _get(_model: object, key: object) -> object:
        if key == 1:
            return SimpleNamespace(stock=3)
        if key == 2:
            return SimpleNamespace(stock=10)
        return None

    db.get.side_effect = _get
    assert recap_qty_export_to_stock(db, pkg) == 1
    assert ln_hi.qty_export == 3
    assert ln_ok.qty_export == 3


def test_assert_ship_qty_within_stock_rejects_shortfall() -> None:
    from app.services.gestion_full.excel_export import assert_ship_qty_within_stock

    ln = SimpleNamespace(producto_item_id=7, qty_export=5)
    pkg = SimpleNamespace(lines=[ln])
    db = MagicMock()
    db.get.return_value = SimpleNamespace(stock=2)
    with pytest.raises(ValueError, match="stock ERP insuficiente"):
        assert_ship_qty_within_stock(db, pkg)


def test_prepare_package_for_export_refuses_when_stock_below_qty() -> None:
    from app.services.gestion_full.excel_export import prepare_package_for_export

    ln = SimpleNamespace(producto_item_id=1, qty_export=20)
    pkg_locked = SimpleNamespace(id=9, status="open", lines=[ln])
    db = MagicMock()
    db.query.return_value.filter.return_value.populate_existing.return_value.with_for_update.return_value.one.return_value = pkg_locked
    db.get.return_value = SimpleNamespace(stock=3)
    with pytest.raises(ValueError, match="stock ERP insuficiente"):
        prepare_package_for_export(db, SimpleNamespace(id=9))
    db.flush.assert_not_called()


def test_prepare_package_for_export_ok_when_stock_covers_qty() -> None:
    from app.services.gestion_full.excel_export import prepare_package_for_export

    ln = SimpleNamespace(producto_item_id=1, qty_export=3)
    pkg_locked = SimpleNamespace(id=9, status="open", lines=[ln])
    db = MagicMock()
    db.query.return_value.filter.return_value.populate_existing.return_value.with_for_update.return_value.one.return_value = pkg_locked
    db.get.return_value = SimpleNamespace(stock=3)
    out = prepare_package_for_export(db, SimpleNamespace(id=9))
    assert out is pkg_locked
    assert ln.qty_export == 3
    db.flush.assert_called_once()
