"""Build Gestión Full Excel exports (official ML template + ops EAN sheet)."""

from __future__ import annotations

import io
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Optional

from openpyxl import Workbook, load_workbook
from sqlalchemy import bindparam, text
from sqlalchemy.orm import Session

from app.models.gestion_full_package import (
    PACKAGE_STATUS_EXPORTED,
    PACKAGE_STATUS_LOCKED,
    PACKAGE_STATUS_OPEN,
    GestionFullPackage,
    GestionFullPackageLine,
)
from app.models.gestion_full_unidades_caja import GestionFullUnidadesCaja
from app.models.producto import ProductoERP

_TEMPLATE = Path(__file__).resolve().parents[2] / "assets" / "gestion_full" / "envio-de-stock-full.xlsx"
_SHEET = " Selección de productos"
_DATA_START_ROW = 6

_ENRICH_SQL = text(
    """
    SELECT DISTINCT ON (i.inventory_id)
      i.inventory_id,
      i.seller_sku,
      i.item_id AS mla
    FROM ml_items i
    WHERE i.inventory_id IN :ids
      AND i.never_existed IS NOT TRUE
      AND i.gone_at IS NULL
    ORDER BY i.inventory_id, i.item_id
    """
).bindparams(bindparam("ids", expanding=True))

_EAN_SQL = text(
    """
    SELECT p.item_id AS producto_item_id, p.codigo AS ean, p.descripcion
    FROM productos_erp p
    WHERE p.item_id IN :ids
    """
).bindparams(bindparam("ids", expanding=True))


def _mla_digits(mla: Optional[str]) -> Optional[str]:
    if not mla:
        return None
    s = str(mla).strip().upper()
    if s.startswith("MLA"):
        s = s[3:]
    return s if s.isdigit() else None


def _write_text_cell(ws: Any, row: int, col: int, value: object) -> None:
    """Write ``value`` as an Excel **string** cell (never a formula).

    openpyxl treats strings starting with ``=``, ``+``, ``-``, or ``@`` as
    formulas; Seller Center still needs the literal SKU/EAN text, so we force
    ``data_type='s'`` after assign (no leading apostrophe that would change the value).
    """
    text_val = "" if value is None else str(value)
    cell = ws.cell(row=row, column=col, value=text_val)
    cell.data_type = "s"
    cell.number_format = "@"


def _enrich_lines(
    db: Session,
    lines: list[GestionFullPackageLine],
) -> list[dict[str, Any]]:
    inv_ids = [ln.inventory_id for ln in lines]
    erp_ids = [ln.producto_item_id for ln in lines]
    by_inv: dict[str, Any] = {}
    if inv_ids:
        for row in db.execute(_ENRICH_SQL, {"ids": inv_ids}).mappings():
            by_inv[row.inventory_id] = row
    by_erp: dict[int, Any] = {}
    if erp_ids:
        for row in db.execute(_EAN_SQL, {"ids": erp_ids}).mappings():
            by_erp[row.producto_item_id] = row

    out: list[dict[str, Any]] = []
    for ln in lines:
        inv = by_inv.get(ln.inventory_id)
        erp = by_erp.get(ln.producto_item_id)
        out.append(
            {
                "line": ln,
                "seller_sku": (inv.seller_sku if inv else None) or (erp.ean if erp else None),
                "mla_digits": _mla_digits(inv.mla if inv else None),
                "ean": erp.ean if erp else None,
                "descripcion": erp.descripcion if erp else None,
            }
        )
    return out


def assert_package_exportable(db: Session, package: GestionFullPackage) -> None:
    """Raise ValueError when package cannot be exported."""
    if package.status == PACKAGE_STATUS_LOCKED:
        raise ValueError("paquete hard-locked")
    if any(ln.inbound_id for ln in package.lines):
        raise ValueError("hay inbound_id asignados; borrarlos antes de regenerar")
    if not package.lines:
        raise ValueError("paquete sin líneas")
    missing_caja: list[int] = []
    for ln in package.lines:
        if ln.qty_export < 1:
            continue
        caja = db.get(GestionFullUnidadesCaja, ln.producto_item_id)
        if caja is None:
            missing_caja.append(ln.producto_item_id)
    if missing_caja:
        raise ValueError(f"faltan unidades/caja en productos: {sorted(set(missing_caja))}")


def build_ml_full_xlsx(db: Session, package: GestionFullPackage) -> bytes:
    """Fill the official ML Full template from package qty_export (≥1)."""
    assert_package_exportable(db, package)
    if not _TEMPLATE.is_file():
        raise FileNotFoundError(f"template missing: {_TEMPLATE}")

    enriched = _enrich_lines(db, list(package.lines))
    rows = [e for e in enriched if e["line"].qty_export >= 1 and e["seller_sku"] and e["mla_digits"]]
    if not rows:
        raise ValueError("ninguna línea exportable (SKU + MLA + qty≥1)")

    wb = load_workbook(io.BytesIO(_TEMPLATE.read_bytes()))
    ws = wb[_SHEET]
    for offset, e in enumerate(rows):
        r = _DATA_START_ROW + offset
        ln = e["line"]
        _write_text_cell(ws, r, 1, e["seller_sku"])
        _write_text_cell(ws, r, 3, ln.inventory_id)
        _write_text_cell(ws, r, 4, e["mla_digits"])
        _write_text_cell(ws, r, 6, int(ln.qty_export))
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def build_ops_ean_xlsx(db: Session, package: GestionFullPackage) -> bytes:
    """Simple ops sheet: EAN, descripción, cantidad (qty_export)."""
    assert_package_exportable(db, package)
    enriched = _enrich_lines(db, list(package.lines))
    wb = Workbook()
    ws = wb.active
    ws.title = "Envio"
    _write_text_cell(ws, 1, 1, "EAN")
    _write_text_cell(ws, 1, 2, "Descripcion")
    _write_text_cell(ws, 1, 3, "Cantidad")
    row_i = 2
    for e in enriched:
        ln = e["line"]
        if ln.qty_export < 1:
            continue
        _write_text_cell(ws, row_i, 1, e["ean"] or "")
        _write_text_cell(ws, row_i, 2, e["descripcion"] or "")
        _write_text_cell(ws, row_i, 3, int(ln.qty_export))
        row_i += 1
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def recap_qty_export_to_stock(db: Session, package: GestionFullPackage) -> int:
    """Clamp each line's qty_export to current ``productos_erp.stock``. Returns changed count."""
    changed = 0
    for ln in package.lines:
        prod = db.get(ProductoERP, ln.producto_item_id)
        stock = max(0, int(prod.stock if prod is not None and prod.stock is not None else 0))
        if ln.qty_export > stock:
            ln.qty_export = stock
            changed += 1
    return changed


def prepare_package_for_export(db: Session, package: GestionFullPackage) -> GestionFullPackage:
    """Row-lock, re-cap qty_export to ERP stock, flush — call **before** building Excel bytes.

    The first download must already reflect the stock cap (D6); building before re-cap
    shipped uncapped qty while the DB was corrected only on mark_package_exported.
    """
    pkg = (
        db.query(GestionFullPackage)
        .filter(GestionFullPackage.id == package.id)
        .populate_existing()
        .with_for_update()
        .one()
    )
    if pkg.status == PACKAGE_STATUS_LOCKED:
        raise ValueError("paquete hard-locked")
    recap_qty_export_to_stock(db, pkg)
    db.flush()
    return pkg


def mark_package_exported(db: Session, package: GestionFullPackage) -> GestionFullPackage:
    """Re-cap qty_export to stock_erp, then flip open → exported (idempotent if exported)."""
    pkg = (
        db.query(GestionFullPackage)
        .filter(GestionFullPackage.id == package.id)
        .populate_existing()
        .with_for_update()
        .one()
    )
    if pkg.status == PACKAGE_STATUS_LOCKED:
        raise ValueError("paquete hard-locked")
    recap_qty_export_to_stock(db, pkg)
    if pkg.status == PACKAGE_STATUS_OPEN:
        pkg.status = PACKAGE_STATUS_EXPORTED
        pkg.exported_at = datetime.now(UTC)
    db.commit()
    db.refresh(pkg)
    return pkg
