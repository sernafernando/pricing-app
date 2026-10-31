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


def clear_inbound_ids(db: Session, package: GestionFullPackage) -> int:
    """Clear all inbound assignments (required before Excel regenerate)."""
    if package.status == PACKAGE_STATUS_LOCKED:
        raise PermissionError("package hard-locked")
    n = 0
    for ln in package.lines:
        if ln.inbound_id is not None:
            ln.inbound_id = None
            n += 1
    if n:
        if package.status == PACKAGE_STATUS_EXPORTED:
            package.status = PACKAGE_STATUS_OPEN
            package.exported_at = None
        db.commit()
    return n


def assign_inbound_to_lines(
    db: Session,
    package: GestionFullPackage,
    *,
    line_ids: Iterable[int],
    inbound_id: str,
) -> list[GestionFullPackageLine]:
    """Set the same inbound_id on selected lines (1:1 line→inbound allowed shared id)."""
    if package.status == PACKAGE_STATUS_LOCKED:
        raise PermissionError("package hard-locked")
    inbound = (inbound_id or "").strip()
    if not inbound:
        raise ValueError("inbound_id vacío")

    id_set = {int(x) for x in line_ids}
    if not id_set:
        raise ValueError("sin líneas")

    updated: list[GestionFullPackageLine] = []
    for ln in package.lines:
        if ln.id in id_set:
            ln.inbound_id = inbound
            updated.append(ln)
    missing = id_set - {ln.id for ln in updated}
    if missing:
        raise LookupError(f"líneas no del paquete: {sorted(missing)}")

    db.commit()
    for ln in updated:
        db.refresh(ln)

    from app.services.gestion_full.reconcile import ensure_envio

    ensure_envio(db, package=package, inbound_id=inbound)
    maybe_hard_lock(db, package)
    return updated


def maybe_hard_lock(db: Session, package: GestionFullPackage) -> Optional[GestionFullPackage]:
    """Lock when every line has inbound_id (D3 / D3b all-or-nothing)."""
    lines = list(package.lines)
    if not lines:
        return None
    if any(ln.inbound_id is None or not str(ln.inbound_id).strip() for ln in lines):
        return None
    if package.status == PACKAGE_STATUS_LOCKED:
        return package
    package.status = PACKAGE_STATUS_LOCKED
    package.locked_at = datetime.now(UTC)
    if package.exported_at is None:
        package.exported_at = package.locked_at
    db.commit()
    db.refresh(package)
    return package


def human_envio_id(package: GestionFullPackage, inbound_id: str) -> str:
    """Display id `{YYYYMMDD_monday}_{inbound_id}` (D4)."""
    monday = package.week_monday.strftime("%Y%m%d")
    return f"{monday}_{inbound_id}"
