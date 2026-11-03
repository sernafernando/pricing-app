"""Assign inbound_id to package lines and hard-lock when complete."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Iterable, Optional

from sqlalchemy import func, tuple_
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
    """Row-lock and refresh identity map so status checks see concurrent commits."""
    return (
        db.query(GestionFullPackage)
        .filter(GestionFullPackage.id == package.id)
        .populate_existing()
        .with_for_update()
        .one()
    )


def _consume_pm_ready_for_package(db: Session, package: GestionFullPackage) -> int:
    """Delete pm_ready rows for every package line so PMs can close next week."""
    keys = [(int(ln.producto_item_id), str(ln.user_product_id)) for ln in package.lines]
    if not keys:
        return 0
    return (
        db.query(GestionFullPmReady)
        .filter(tuple_(GestionFullPmReady.producto_item_id, GestionFullPmReady.user_product_id).in_(keys))
        .delete(synchronize_session=False)
    )


def _close_orphan_envios(db: Session, cleared: set[str]) -> None:
    """Close never-received envíos with no remaining line refs (no-op before envío model)."""
    try:
        from app.models.gestion_full_envio import GestionFullEnvio
    except ImportError:
        # Stack PRs before #1981 do not ship gestion_full_envio yet.
        return

    if not cleared:
        return

    ref_counts = dict(
        db.query(GestionFullPackageLine.inbound_id, func.count())
        .filter(GestionFullPackageLine.inbound_id.in_(cleared))
        .group_by(GestionFullPackageLine.inbound_id)
        .all()
    )
    envios = {
        e.inbound_id: e for e in db.query(GestionFullEnvio).filter(GestionFullEnvio.inbound_id.in_(cleared)).all()
    }
    now = datetime.now(UTC)
    for inbound_id in cleared:
        if int(ref_counts.get(inbound_id, 0)) > 0:
            continue
        envio = envios.get(inbound_id)
        if envio is None or envio.reception_closed_at is not None:
            continue
        # Keep envíos that already received stock open — re-assign of the same
        # inbound must be able to resume reconcile (Fernando round-3 #1).
        if envio.last_reception_at is not None:
            continue
        envio.reception_closed_at = now


def clear_inbound_ids(db: Session, package: GestionFullPackage) -> int:
    """Clear all inbound assignments (required before Excel regenerate).

    Closes local envío rows that no longer have any package line referencing them,
    so "Limpiar inbounds" cannot leave forever-open orphans starving the reconcile batch.
    """
    pkg = _package_for_update(db, package)
    if pkg.status == PACKAGE_STATUS_LOCKED:
        raise PermissionError("package hard-locked")
    n = 0
    cleared: set[str] = set()
    for ln in pkg.lines:
        if ln.inbound_id is not None:
            cleared.add(str(ln.inbound_id))
            ln.inbound_id = None
            n += 1
    if n:
        if pkg.status == PACKAGE_STATUS_EXPORTED:
            pkg.status = PACKAGE_STATUS_OPEN
            pkg.exported_at = None
        # autoflush=False in production — flush so the ref count sees cleared lines.
        db.flush()
        _close_orphan_envios(db, cleared)
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

    try:
        from app.services.gestion_full.reconcile import ensure_envio
    except ImportError:
        ensure_envio = None  # type: ignore[assignment]

    # Same transaction as assign + hard-lock when reconcile exists (#1981+).
    if ensure_envio is not None:
        ensure_envio(db, package=pkg, inbound_id=inbound, commit=False)
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
