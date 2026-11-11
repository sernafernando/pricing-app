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
from app.services.gestion_full.inventory_keys import (
    excel_codigo_ml,
    is_synthetic_inventory_id,
)

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

_ENRICH_BY_MLAU_SQL = text(
    """
    SELECT DISTINCT ON (i.user_product_id)
      i.user_product_id,
      i.seller_sku,
      i.item_id AS mla
    FROM ml_items i
    WHERE i.user_product_id IN :mlaus
      AND i.never_existed IS NOT TRUE
      AND i.gone_at IS NULL
    ORDER BY i.user_product_id, (i.inventory_id IS NULL), i.inventory_id, i.item_id
    """
).bindparams(bindparam("mlaus", expanding=True))

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
    real_inv_ids = [
        ln.inventory_id for ln in lines if ln.inventory_id and not is_synthetic_inventory_id(ln.inventory_id)
    ]
    mlaus = [ln.user_product_id for ln in lines if is_synthetic_inventory_id(ln.inventory_id) or not ln.inventory_id]
    erp_ids = [ln.producto_item_id for ln in lines]
    by_inv: dict[str, Any] = {}
    if real_inv_ids:
        for row in db.execute(_ENRICH_SQL, {"ids": real_inv_ids}).mappings():
            by_inv[row.inventory_id] = row
    by_mlau: dict[str, Any] = {}
    if mlaus:
        for row in db.execute(_ENRICH_BY_MLAU_SQL, {"mlaus": mlaus}).mappings():
            by_mlau[row.user_product_id] = row
    by_erp: dict[int, Any] = {}
    if erp_ids:
        for row in db.execute(_EAN_SQL, {"ids": erp_ids}).mappings():
            by_erp[row.producto_item_id] = row

    out: list[dict[str, Any]] = []
    for ln in lines:
        inv = None if is_synthetic_inventory_id(ln.inventory_id) else by_inv.get(ln.inventory_id)
        mlau_row = by_mlau.get(ln.user_product_id)
        erp = by_erp.get(ln.producto_item_id)
        seller_sku = (
            (inv.seller_sku if inv else None)
            or (mlau_row.seller_sku if mlau_row else None)
            or (erp.ean if erp else None)
        )
        mla = (inv.mla if inv else None) or (mlau_row.mla if mlau_row else None)
        out.append(
            {
                "line": ln,
                "seller_sku": seller_sku,
                "mla_digits": _mla_digits(mla),
                "ean": erp.ean if erp else None,
                "descripcion": erp.descripcion if erp else None,
            }
        )
    return out


def _stock_by_producto_ids(db: Session, producto_item_ids: set[int]) -> dict[int, int]:
    """One ``IN`` query for ERP stock; missing products count as 0."""
    out = {int(pid): 0 for pid in producto_item_ids}
    if not producto_item_ids:
        return out
    for prod in db.query(ProductoERP).filter(ProductoERP.item_id.in_(producto_item_ids)).all():
        out[int(prod.item_id)] = max(0, int(prod.stock if prod.stock is not None else 0))
    return out


def _caja_producto_ids(db: Session, producto_item_ids: set[int]) -> set[int]:
    """Producto ids that already have unidades/caja (one ``IN`` query)."""
    if not producto_item_ids:
        return set()
    return {
        int(pid)
        for (pid,) in db.query(GestionFullUnidadesCaja.producto_item_id)
        .filter(GestionFullUnidadesCaja.producto_item_id.in_(producto_item_ids))
        .all()
    }


def assert_package_exportable(db: Session, package: GestionFullPackage) -> None:
    """Raise ValueError when package cannot be exported."""
    if package.status == PACKAGE_STATUS_LOCKED:
        raise ValueError("paquete hard-locked")
    if any(ln.inbound_id for ln in package.lines):
        raise ValueError("hay inbound_id asignados; borrarlos antes de regenerar")
    if not package.lines:
        raise ValueError("paquete sin líneas")
    ship_ids = {int(ln.producto_item_id) for ln in package.lines if int(ln.qty_export or 0) >= 1}
    with_caja = _caja_producto_ids(db, ship_ids)
    missing_caja = sorted(ship_ids - with_caja)
    if missing_caja:
        raise ValueError(f"faltan unidades/caja en productos: {missing_caja}")


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
        _write_text_cell(ws, r, 3, excel_codigo_ml(ln.inventory_id))
        _write_text_cell(ws, r, 4, e["mla_digits"])
        _write_text_cell(ws, r, 6, int(ln.qty_export))
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def build_ops_ean_xlsx(db: Session, package: GestionFullPackage) -> bytes:
    """Simple ops sheet: EAN, descripción, cantidad (qty_export)."""
    assert_package_exportable(db, package)
    enriched = _enrich_lines(db, list(package.lines))
    rows = [e for e in enriched if e["line"].qty_export >= 1]
    if not rows:
        raise ValueError("ninguna línea exportable (qty≥1)")
    wb = Workbook()
    ws = wb.active
    ws.title = "Envio"
    _write_text_cell(ws, 1, 1, "EAN")
    _write_text_cell(ws, 1, 2, "Descripcion")
    _write_text_cell(ws, 1, 3, "Cantidad")
    for row_i, e in enumerate(rows, start=2):
        ln = e["line"]
        _write_text_cell(ws, row_i, 1, e["ean"] or "")
        _write_text_cell(ws, row_i, 2, e["descripcion"] or "")
        _write_text_cell(ws, row_i, 3, int(ln.qty_export))
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def recap_qty_export_to_stock(db: Session, package: GestionFullPackage) -> int:
    """Clamp each line's qty_export to current ``productos_erp.stock``. Returns changed count."""
    stocks = _stock_by_producto_ids(db, {int(ln.producto_item_id) for ln in package.lines})
    changed = 0
    for ln in package.lines:
        stock = stocks.get(int(ln.producto_item_id), 0)
        if ln.qty_export > stock:
            ln.qty_export = stock
            changed += 1
    return changed


def assert_ship_qty_within_stock(db: Session, package: GestionFullPackage) -> None:
    """Raise when any shippable line (qty_export ≥ 1) exceeds current ERP stock.

    Export must not silently shrink qty: the gestor removes or lowers those SKUs first.
    """
    stocks = _stock_by_producto_ids(db, {int(ln.producto_item_id) for ln in package.lines})
    short: list[int] = []
    for ln in package.lines:
        qty = int(ln.qty_export or 0)
        if qty < 1:
            continue
        if stocks.get(int(ln.producto_item_id), 0) < qty:
            short.append(int(ln.producto_item_id))
    if short:
        ids = sorted(set(short))
        raise ValueError(
            "stock ERP insuficiente para la qty a enviar en productos "
            f"{ids}; sacalos del paquete o bajá qty export antes de exportar"
        )


def prepare_package_for_export(db: Session, package: GestionFullPackage) -> GestionFullPackage:
    """Row-lock and validate stock covers qty_export before building Excel bytes.

    Refuses the download when ERP stock is below qty a enviar (gestor must fix the package).
    A no-op re-cap remains as a race guard after the assert.
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
    assert_ship_qty_within_stock(db, pkg)
    recap_qty_export_to_stock(db, pkg)
    db.flush()
    return pkg


def mark_package_exported(
    db: Session,
    package: GestionFullPackage,
    *,
    usuario_id: int,
) -> GestionFullPackage:
    """Re-cap qty_export to stock_erp, then flip open → exported (idempotent if exported)."""
    from app.models.auditoria import TipoAccion
    from app.services.gestion_full.audit import registrar

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
    became_exported = False
    if pkg.status == PACKAGE_STATUS_OPEN:
        pkg.status = PACKAGE_STATUS_EXPORTED
        pkg.exported_at = datetime.now(UTC)
        became_exported = True
    if became_exported:
        registrar(
            db,
            tipo=TipoAccion.GESTION_FULL_EXPORTED,
            usuario_id=int(usuario_id),
            despues={
                "package_id": int(pkg.id),
                "exported_at": pkg.exported_at.isoformat() if pkg.exported_at else None,
                "line_count": len(pkg.lines),
            },
        )
    db.commit()
    db.refresh(pkg)
    return pkg
