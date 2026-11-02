"""Assign inbound_id to package lines and hard-lock when complete."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Iterable, Optional

from sqlalchemy.orm import Session

from app.models.gestion_full_package import (
    PACKAGE_STATUS_EXPORTED,
    PACKAGE_STATUS_LOCKED,
    PACKAGE_STATUS_OPEN,
    GestionFullPackage,
    GestionFullPackageLine,
)
from app.models.gestion_full_pm_ready import GestionFullPmReady


def _package_for_update(db: Session, package: GestionFullPackage) -> GestionFullPackage:
    """Row-lock the package for assign / clear / hard-lock."""
    return db.query(GestionFullPackage).filter(GestionFullPackage.id == package.id).with_for_update().one()


def _consume_pm_ready_for_package(db: Session, package: GestionFullPackage) -> int:
    """Delete pm_ready rows for every package line so PMs can close next week."""
    deleted = 0
    for ln in package.lines:
        row = db.get(GestionFullPmReady, (ln.producto_item_id, ln.user_product_id))
        if row is not None:
            db.delete(row)
            deleted += 1
    return deleted


def clear_inbound_ids(db: Session, package: GestionFullPackage) -> int:
    """Clear all inbound assignments (required before Excel regenerate)."""
    pkg = _package_for_update(db, package)
    if pkg.status == PACKAGE_STATUS_LOCKED:
        raise PermissionError("package hard-locked")
    n = 0
    for ln in pkg.lines:
        if ln.inbound_id is not None:
            ln.inbound_id = None
            n += 1
    if n:
        if pkg.status == PACKAGE_STATUS_EXPORTED:
            pkg.status = PACKAGE_STATUS_OPEN
            pkg.exported_at = None
        db.commit()
    return n


def assign_inbound_to_lines(
    db: Session,
    package: GestionFullPackage,
    *,
    line_ids: Iterable[int],
    inbound_id: str,
) -> list[GestionFullPackageLine]:
    """Set the same inbound_id on selected lines (1:1 line→inbound allowed shared id).

    Requires ``exported`` status (Excel already generated through the U/caja gate).
    Hard-locks in the same transaction when every shippable line (qty_export ≥ 1)
    has an inbound_id; consumes pm_ready for the package lines.
    """
    pkg = _package_for_update(db, package)
    if pkg.status == PACKAGE_STATUS_LOCKED:
        raise PermissionError("package hard-locked")
    if pkg.status != PACKAGE_STATUS_EXPORTED:
        raise ValueError("paquete debe estar exported antes de asignar inbound")

    inbound = (inbound_id or "").strip()
    if not inbound:
        raise ValueError("inbound_id vacío")

    id_set = {int(x) for x in line_ids}
    if not id_set:
        raise ValueError("sin líneas")

    updated: list[GestionFullPackageLine] = []
    for ln in pkg.lines:
        if ln.id in id_set:
            ln.inbound_id = inbound
            updated.append(ln)
    missing = id_set - {ln.id for ln in updated}
    if missing:
        raise LookupError(f"líneas no del paquete: {sorted(missing)}")

    maybe_hard_lock(db, pkg, already_locked=True)
    db.commit()
    for ln in updated:
        db.refresh(ln)
    db.refresh(pkg)
    return updated


def maybe_hard_lock(
    db: Session,
    package: GestionFullPackage,
    *,
    already_locked: bool = False,
) -> Optional[GestionFullPackage]:
    """Lock when every shippable line (qty_export ≥ 1) has inbound_id (D3 / D3b).

    Lines with qty_export 0 are not in the Excel and do not block the lock.
    Consumes ``gestion_full_pm_ready`` for all package lines on transition to locked.
    """
    pkg = package if already_locked else _package_for_update(db, package)
    ship_lines = [ln for ln in pkg.lines if int(ln.qty_export or 0) >= 1]
    if not ship_lines:
        return None
    if any(ln.inbound_id is None or not str(ln.inbound_id).strip() for ln in ship_lines):
        return None
    if pkg.status == PACKAGE_STATUS_LOCKED:
        return pkg

    pkg.status = PACKAGE_STATUS_LOCKED
    pkg.locked_at = datetime.now(UTC)
    if pkg.exported_at is None:
        pkg.exported_at = pkg.locked_at
    _consume_pm_ready_for_package(db, pkg)
    if not already_locked:
        db.commit()
        db.refresh(pkg)
    return pkg


def human_envio_id(package: GestionFullPackage, inbound_id: str) -> str:
    """Display id `{YYYYMMDD_monday}_{inbound_id}` (D4)."""
    monday = package.week_monday.strftime("%Y%m%d")
    return f"{monday}_{inbound_id}"
