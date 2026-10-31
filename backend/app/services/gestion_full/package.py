"""Open Gestión Full send package helpers (no Excel / assign yet)."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from datetime import UTC
from typing import Optional

from sqlalchemy.orm import Session

from app.models.gestion_full_package import (
    PACKAGE_STATUS_LOCKED,
    PACKAGE_STATUS_OPEN,
    GestionFullPackage,
    GestionFullPackageLine,
    GestionFullQtyExportAudit,
)
from app.models.usuario import Usuario


def week_monday_on(day: date) -> date:
    """Monday of the ISO week containing `day`."""
    return day - timedelta(days=day.weekday())


def get_active_package(db: Session) -> Optional[GestionFullPackage]:
    """The single open or exported package, if any (D4b)."""
    return (
        db.query(GestionFullPackage)
        .filter(GestionFullPackage.status.in_(("open", "exported")))
        .order_by(GestionFullPackage.id.desc())
        .first()
    )


def get_or_create_open_package(
    db: Session,
    *,
    usuario: Usuario,
    on_day: Optional[date] = None,
) -> GestionFullPackage:
    """Return the active package, or create an open one for this week's Monday."""
    existing = get_active_package(db)
    if existing is not None:
        return existing

    monday = week_monday_on(on_day or datetime.now(UTC).date())
    pkg = GestionFullPackage(
        week_monday=monday,
        status=PACKAGE_STATUS_OPEN,
        created_by_id=usuario.id,
    )
    db.add(pkg)
    db.commit()
    db.refresh(pkg)
    return pkg


def upsert_package_line(
    db: Session,
    *,
    package: GestionFullPackage,
    producto_item_id: int,
    user_product_id: str,
    inventory_id: str,
    qty_pm: int,
) -> GestionFullPackageLine:
    """Add or refresh a line; qty_export defaults to qty_pm on create."""
    if qty_pm < 0:
        raise ValueError("qty_pm must be >= 0")

    line = (
        db.query(GestionFullPackageLine)
        .filter_by(
            package_id=package.id,
            producto_item_id=producto_item_id,
            user_product_id=user_product_id,
        )
        .one_or_none()
    )
    if line is None:
        line = GestionFullPackageLine(
            package_id=package.id,
            producto_item_id=producto_item_id,
            user_product_id=user_product_id,
            inventory_id=inventory_id,
            qty_pm=qty_pm,
            qty_export=qty_pm,
        )
        db.add(line)
    else:
        line.inventory_id = inventory_id
        line.qty_pm = qty_pm
        # Keep gestor qty_export if already adjusted; else mirror qty_pm.
        if line.qty_export_updated_by_id is None:
            line.qty_export = qty_pm
    db.commit()
    db.refresh(line)
    return line


def set_qty_export(
    db: Session,
    *,
    line: GestionFullPackageLine,
    qty_export: int,
    usuario: Usuario,
    reason: Optional[str] = None,
    stock_erp: Optional[int] = None,
) -> GestionFullPackageLine:
    """Gestor adjusts qty_export (capped by stock_erp when provided); writes audit."""
    pkg = line.package or db.get(GestionFullPackage, line.package_id)
    if pkg is not None and pkg.status == PACKAGE_STATUS_LOCKED:
        raise PermissionError("package hard-locked")
    if qty_export < 0:
        raise ValueError("qty_export must be >= 0")
    capped = qty_export
    if stock_erp is not None:
        capped = min(qty_export, max(0, int(stock_erp)))

    old = line.qty_export
    if old == capped and (reason or None) == (line.qty_export_reason or None):
        return line

    line.qty_export = capped
    line.qty_export_reason = reason
    line.qty_export_updated_by_id = usuario.id
    line.qty_export_updated_at = datetime.now(UTC)
    db.add(
        GestionFullQtyExportAudit(
            package_line_id=line.id,
            old_qty=old,
            new_qty=capped,
            reason=reason,
            updated_by_id=usuario.id,
        )
    )
    db.commit()
    db.refresh(line)
    return line
