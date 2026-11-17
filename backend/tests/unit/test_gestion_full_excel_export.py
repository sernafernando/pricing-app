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
    from unittest.mock import patch

    db = MagicMock()
    db.query.return_value.filter.return_value.all.return_value = [
        SimpleNamespace(item_id=7, codigo="4897098683446", descripcion="UB500"),
    ]
    pkg = SimpleNamespace(
        status="open",
        lines=[SimpleNamespace(inbound_id=None, qty_export=2, producto_item_id=7)],
    )
    with patch(
        "app.services.gestion_full.unidades_caja.producto_ids_con_caja_efectiva",
        return_value=set(),
    ):
        with pytest.raises(ValueError, match="unidades por caja.*4897098683446"):
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
    db.query.return_value.filter.return_value.all.return_value = [
        SimpleNamespace(item_id=1, stock=3),
        SimpleNamespace(item_id=2, stock=10),
    ]
    assert recap_qty_export_to_stock(db, pkg) == 1
    assert ln_hi.qty_export == 3
    assert ln_ok.qty_export == 3


def test_assert_ship_qty_within_stock_rejects_shortfall() -> None:
    from app.services.gestion_full.excel_export import assert_ship_qty_within_stock

    ln = SimpleNamespace(producto_item_id=7, qty_export=5)
    pkg = SimpleNamespace(lines=[ln])
    db = MagicMock()
    db.query.return_value.filter.return_value.all.return_value = [
        SimpleNamespace(item_id=7, stock=2),
    ]
    with pytest.raises(ValueError, match="stock ERP insuficiente"):
        assert_ship_qty_within_stock(db, pkg)


def test_prepare_package_for_export_refuses_when_stock_below_qty() -> None:
    from app.services.gestion_full.excel_export import prepare_package_for_export

    ln = SimpleNamespace(producto_item_id=1, qty_export=20)
    pkg_locked = SimpleNamespace(id=9, status="open", lines=[ln])
    db = MagicMock()
    lock_q = MagicMock()
    lock_q.filter.return_value.populate_existing.return_value.with_for_update.return_value.one.return_value = pkg_locked
    stock_q = MagicMock()
    stock_q.filter.return_value.all.return_value = [SimpleNamespace(item_id=1, stock=3)]

    def _query(model: object) -> MagicMock:
        name = getattr(model, "__name__", "")
        if name == "ProductoERP":
            return stock_q
        return lock_q

    db.query.side_effect = _query
    with pytest.raises(ValueError, match="stock ERP insuficiente"):
        prepare_package_for_export(db, SimpleNamespace(id=9))
    db.flush.assert_not_called()


def test_prepare_package_for_export_ok_when_stock_covers_qty() -> None:
    from app.services.gestion_full.excel_export import prepare_package_for_export

    ln = SimpleNamespace(producto_item_id=1, qty_export=3)
    pkg_locked = SimpleNamespace(id=9, status="open", lines=[ln])
    db = MagicMock()
    lock_q = MagicMock()
    lock_q.filter.return_value.populate_existing.return_value.with_for_update.return_value.one.return_value = pkg_locked
    stock_q = MagicMock()
    stock_q.filter.return_value.all.return_value = [SimpleNamespace(item_id=1, stock=3)]

    def _query(model: object) -> MagicMock:
        name = getattr(model, "__name__", "")
        if name == "ProductoERP":
            return stock_q
        return lock_q

    db.query.side_effect = _query
    out = prepare_package_for_export(db, SimpleNamespace(id=9))
    assert out is pkg_locked
    assert ln.qty_export == 3
    db.flush.assert_called_once()


def test_export_routes_call_prepare_before_build() -> None:
    """Fernando: removing prepare from the route must fail this test."""
    import inspect

    from app.routers import gestion_full as mod

    for fn in (mod.get_package_export_ml, mod.get_package_export_ops):
        src = inspect.getsource(fn)
        assert "prepare_package_for_export" in src
        build = "build_ml_full_xlsx" if fn is mod.get_package_export_ml else "build_ops_ean_xlsx"
        assert src.index("prepare_package_for_export") < src.index(build)


def test_envio_export_ops_skips_prepare_and_uses_inbound_builder() -> None:
    """Post-inbound ops must not require active package / stock re-cap."""
    import inspect

    from app.routers import gestion_full as mod

    src = inspect.getsource(mod.get_envio_export_ops)
    assert "build_ops_ean_xlsx_for_envio" in src
    assert "prepare_package_for_export" not in src
    assert "mark_package_exported" not in src


def test_build_ops_ean_xlsx_for_envio_missing() -> None:
    from app.services.gestion_full.excel_export import build_ops_ean_xlsx_for_envio

    db = MagicMock()
    db.get.return_value = None
    with pytest.raises(LookupError, match="envío no encontrado"):
        build_ops_ean_xlsx_for_envio(db, "79909756")


def test_build_ops_ean_xlsx_for_envio_happy_path() -> None:
    from unittest.mock import patch

    from app.services.gestion_full.excel_export import build_ops_ean_xlsx_for_envio

    db = MagicMock()
    envio = SimpleNamespace(package_id=12, inbound_id="79909756")
    db.get.return_value = envio
    ln = SimpleNamespace(producto_item_id=7, qty_export=3, inbound_id="79909756")
    db.query.return_value.filter.return_value.all.return_value = [ln]
    with (
        patch(
            "app.services.gestion_full.excel_export._assert_ship_lines_have_caja",
        ) as assert_caja,
        patch(
            "app.services.gestion_full.excel_export._ops_ean_xlsx_bytes",
            return_value=b"PK",
        ) as build_bytes,
    ):
        out = build_ops_ean_xlsx_for_envio(db, "79909756")
    assert out == b"PK"
    assert_caja.assert_called_once()
    build_bytes.assert_called_once_with(db, [ln])


def test_envio_ops_export_accepts_pack_inheriting_base_caja() -> None:
    """Pack X2 of a base with U/caja passes inbound ops export (same gate as #2303)."""
    from unittest.mock import patch

    from app.services.gestion_full.excel_export import build_ops_ean_xlsx_for_envio

    db = MagicMock()
    db.get.return_value = SimpleNamespace(package_id=12, inbound_id="79909756")
    pack_ln = SimpleNamespace(producto_item_id=4693, qty_export=5, inbound_id="79909756")
    db.query.return_value.filter.return_value.all.return_value = [pack_ln]
    with (
        patch(
            "app.services.gestion_full.unidades_caja.producto_ids_con_caja_efectiva",
            return_value={4693},
        ) as effective,
        patch(
            "app.services.gestion_full.excel_export._ops_ean_xlsx_bytes",
            return_value=b"PK-pack",
        ) as build_bytes,
    ):
        out = build_ops_ean_xlsx_for_envio(db, "79909756")
    assert out == b"PK-pack"
    effective.assert_called_once_with(db, {4693})
    build_bytes.assert_called_once_with(db, [pack_ln])


def test_assert_ship_lines_have_caja_uses_efectiva_and_ean_message() -> None:
    """Inbound/package caja gate must reuse #2303 effective coverage + EAN message."""
    import inspect

    from app.services.gestion_full import excel_export as mod

    src = inspect.getsource(mod._assert_ship_lines_have_caja)
    assert "producto_ids_con_caja_efectiva" in src
    assert "_format_missing_caja_message" in src
    assert "_caja_producto_ids" not in src


def test_export_stock_and_caja_helpers_batch_with_in() -> None:
    """Fernando N+1: stock/U-caja must not db.get per line."""
    import inspect

    from app.services.gestion_full import excel_export as mod
    from app.services.gestion_full import unidades_caja as caja_mod

    for fn in (
        mod._stock_by_producto_ids,
        caja_mod.producto_ids_con_caja,
        caja_mod.producto_ids_con_caja_efectiva,
        mod._assert_ship_lines_have_caja,
        mod.recap_qty_export_to_stock,
        mod.assert_ship_qty_within_stock,
        mod.assert_package_exportable,
    ):
        src = inspect.getsource(fn)
        assert "db.get(" not in src
    assert ".in_(" in inspect.getsource(mod._stock_by_producto_ids)
    assert ".in_(" in inspect.getsource(caja_mod.producto_ids_con_caja)


def test_get_envios_joinedloads_package() -> None:
    """Fernando N+1: list envíos must joinedload package (no lazy per row)."""
    import inspect

    from app.routers import gestion_full as mod

    src = inspect.getsource(mod.get_envios)
    assert "joinedload(GestionFullEnvio.package)" in src
