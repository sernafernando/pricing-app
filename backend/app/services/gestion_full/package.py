"""Open Gestión Full send package helpers (no Excel / assign yet)."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from datetime import UTC
from typing import Iterable, Optional

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.gestion_full_package import (
    PACKAGE_STATUS_EXPORTED,
    PACKAGE_STATUS_LOCKED,
    PACKAGE_STATUS_OPEN,
    GestionFullPackage,
    GestionFullPackageLine,
    GestionFullQtyExportAudit,
)
from app.models.gestion_full_pm_ready import GestionFullPmReady
from app.models.producto import ProductoERP
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


def _package_for_update(db: Session, package_id: int) -> GestionFullPackage:
    """Row-lock and refresh identity map so status checks see concurrent commits."""
    return (
        db.query(GestionFullPackage)
        .filter(GestionFullPackage.id == package_id)
        .populate_existing()
        .with_for_update()
        .one()
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
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        existing = get_active_package(db)
        if existing is not None:
            return existing
        raise
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
    """Add or refresh a line; auto qty_export capped to ERP stock."""
    if qty_pm < 0:
        raise ValueError("qty_pm must be >= 0")

    pkg = _package_for_update(db, package.id)
    if pkg.status == PACKAGE_STATUS_LOCKED:
        raise PermissionError("package hard-locked")

    stock = _stock_erp_for_item(db, producto_item_id)
    capped = min(int(qty_pm), stock)
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
        if pkg.status == PACKAGE_STATUS_EXPORTED:
            raise ValueError("paquete ya exportado: líneas Listo nuevas van al próximo envío")
        line = GestionFullPackageLine(
            package_id=package.id,
            producto_item_id=producto_item_id,
            user_product_id=user_product_id,
            inventory_id=inventory_id,
            qty_pm=qty_pm,
            qty_export=capped,
        )
        db.add(line)
    else:
        line.inventory_id = inventory_id
        line.qty_pm = qty_pm
        # Keep gestor qty_export if already adjusted; else mirror capped qty_pm.
        if line.qty_export_updated_by_id is None:
            if pkg.status == PACKAGE_STATUS_EXPORTED:
                line.qty_export = min(int(line.qty_export), stock)
            else:
                line.qty_export = capped
    db.commit()
    db.refresh(line)
    return line


def _stock_erp_for_item(db: Session, producto_item_id: int) -> int:
    prod = db.get(ProductoERP, producto_item_id)
    if prod is None or prod.stock is None:
        return 0
    return max(0, int(prod.stock))


def add_all_ready_lines_to_package(
    db: Session,
    *,
    usuario: Usuario,
) -> tuple[GestionFullPackage, int]:
    """Upsert every ``gestion_full_pm_ready`` row into the active package (one transaction).

    Auto ``qty_export`` (no gestor touch) is capped to ERP stock. On an **exported**
    package, new Listo rows are skipped (they wait for the next shipment); existing
    lines only ever lower qty_export (never raise above the Excel amount).
    """
    pkg = get_or_create_open_package(db, usuario=usuario)
    pkg = _package_for_update(db, pkg.id)
    if pkg.status == PACKAGE_STATUS_LOCKED:
        raise PermissionError("package hard-locked")

    exported = pkg.status == PACKAGE_STATUS_EXPORTED
    ready_rows = [r for r in db.query(GestionFullPmReady).all() if r.qty_pm >= 0]
    item_ids = {int(r.producto_item_id) for r in ready_rows}
    stock_by_id: dict[int, int] = {pid: 0 for pid in item_ids}
    if item_ids:
        for prod in db.query(ProductoERP).filter(ProductoERP.item_id.in_(item_ids)).all():
            stock_by_id[int(prod.item_id)] = max(0, int(prod.stock if prod.stock is not None else 0))
    lines_by_key: dict[tuple[int, str], GestionFullPackageLine] = {
        (int(ln.producto_item_id), str(ln.user_product_id)): ln
        for ln in db.query(GestionFullPackageLine).filter(GestionFullPackageLine.package_id == pkg.id).all()
    }

    touched = 0
    for ready in ready_rows:
        stock = stock_by_id.get(int(ready.producto_item_id), 0)
        capped = min(int(ready.qty_pm), stock)
        key = (int(ready.producto_item_id), str(ready.user_product_id))
        line = lines_by_key.get(key)
        if line is None:
            # After Excel download, PM Listo changes wait for the next shipment.
            if exported:
                continue
            line = GestionFullPackageLine(
                package_id=pkg.id,
                producto_item_id=ready.producto_item_id,
                user_product_id=ready.user_product_id,
                inventory_id=ready.inventory_id,
                qty_pm=ready.qty_pm,
                qty_export=capped,
            )
            db.add(line)
            lines_by_key[key] = line
        else:
            line.inventory_id = ready.inventory_id
            line.qty_pm = ready.qty_pm
            if line.qty_export_updated_by_id is None:
                # Exported: only cap down so Excel qty stays the ceiling.
                line.qty_export = min(int(line.qty_export), stock) if exported else capped
        touched += 1
    # autoflush=False: make new lines visible to recap / hard-lock identity map.
    db.flush()
    db.expire(pkg, ["lines"])
    # Re-cap again after upserts (stock may be lower than any auto value).
    from app.services.gestion_full.excel_export import recap_qty_export_to_stock

    recap_qty_export_to_stock(db, pkg)
    # Stock→0 on the last unassigned shippable line must hard-lock like set_qty_export.
    from app.services.gestion_full.assign_inbound import maybe_hard_lock

    maybe_hard_lock(db, pkg, already_locked=True)
    db.commit()
    db.refresh(pkg)
    return pkg, touched


def _stock_erp_for_line(db: Session, line: GestionFullPackageLine) -> int:
    return _stock_erp_for_item(db, line.producto_item_id)


def set_qty_export(
    db: Session,
    *,
    line: GestionFullPackageLine,
    qty_export: int,
    usuario: Usuario,
    reason: Optional[str] = None,
    stock_erp: Optional[int] = None,
) -> GestionFullPackageLine:
    """Gestor adjusts qty_export capped by server ``productos_erp.stock``; writes audit.

    ``stock_erp`` is ignored when provided by clients — cap always comes from the DB.
    """
    del stock_erp  # never trust client-supplied stock
    pkg = _package_for_update(db, line.package_id)
    if pkg.status == PACKAGE_STATUS_LOCKED:
        raise PermissionError("package hard-locked")
    if qty_export < 0:
        raise ValueError("qty_export must be >= 0")
    capped = min(qty_export, _stock_erp_for_line(db, line))

    # Re-bind line under lock; populate_existing so concurrent PATCH isn't stale.
    line = (
        db.query(GestionFullPackageLine)
        .filter(GestionFullPackageLine.id == line.id)
        .populate_existing()
        .with_for_update()
        .one()
    )
    old = line.qty_export
    qty_unchanged = old == capped and (reason or None) == (line.qty_export_reason or None)
    if not qty_unchanged:
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
    # Always evaluate hard-lock (even when qty unchanged — e.g. PATCH 0 no-op after Sumar).
    from app.services.gestion_full.assign_inbound import maybe_hard_lock

    maybe_hard_lock(db, pkg, already_locked=True)
    db.commit()
    db.refresh(line)
    return line


def remove_package_lines(
    db: Session,
    package: GestionFullPackage,
    *,
    line_ids: Iterable[int],
) -> int:
    """Delete selected lines from the active package (same selection UX as assign-inbound).

    Closes orphan envíos whose inbound_id no longer appears on any line. Refuses a
    hard-locked package. May hard-lock afterwards if every remaining shippable line
    already has an inbound_id.
    """
    from app.services.gestion_full.assign_inbound import _close_orphan_envios, maybe_hard_lock

    pkg = _package_for_update(db, package.id)
    if pkg.status == PACKAGE_STATUS_LOCKED:
        raise PermissionError("package hard-locked")

    id_set = {int(x) for x in line_ids}
    if not id_set:
        raise ValueError("sin líneas")

    to_delete = [ln for ln in pkg.lines if int(ln.id) in id_set]
    missing = id_set - {int(ln.id) for ln in to_delete}
    if missing:
        raise LookupError(f"líneas no del paquete: {sorted(missing)}")

    cleared: set[str] = set()
    for ln in to_delete:
        if ln.inbound_id is not None and str(ln.inbound_id).strip():
            cleared.add(str(ln.inbound_id).strip())
        db.delete(ln)

    db.flush()
    if cleared:
        _close_orphan_envios(db, cleared)
    db.expire(pkg, ["lines"])
    maybe_hard_lock(db, pkg, already_locked=True)
    db.commit()
    db.refresh(pkg)
    return len(to_delete)
