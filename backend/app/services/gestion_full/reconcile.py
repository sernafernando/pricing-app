"""Reconcile declared package lines vs persisted INBOUND_RECEPTION ops (D8)."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any, Optional

from sqlalchemy.orm import Session

from app.models.gestion_full_envio import GestionFullEnvio, GestionFullInboundReceptionOp
from app.models.gestion_full_package import GestionFullPackage, GestionFullPackageLine
from app.services.gestion_full.inbound import (
    MAX_RANGE_DAYS,
    TYPE_INBOUND,
    _inbound_id_from_refs,
    _parse_occurred_at,
)
from app.services.ml_publications.ml_http import MlHttpClient

CLOSE_AFTER_IDLE = timedelta(days=3)


def ensure_envio(
    db: Session,
    *,
    package: GestionFullPackage,
    inbound_id: str,
) -> GestionFullEnvio:
    """Create envio row for an assigned inbound_id if missing."""
    inbound = (inbound_id or "").strip()
    row = db.get(GestionFullEnvio, inbound)
    if row is not None:
        return row
    row = GestionFullEnvio(
        inbound_id=inbound,
        package_id=package.id,
        week_monday=package.week_monday,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def list_open_envios(db: Session) -> list[GestionFullEnvio]:
    """Envíos still polling for reception (not locally closed)."""
    return (
        db.query(GestionFullEnvio)
        .filter(GestionFullEnvio.reception_closed_at.is_(None))
        .order_by(GestionFullEnvio.created_at.asc())
        .all()
    )


def upsert_reception_op(
    db: Session,
    *,
    inbound_id: str,
    operation_id: int,
    inventory_id: str,
    cantidad: int,
    occurred_at: datetime,
) -> bool:
    """Insert op if new. Returns True when a row was added."""
    existing = db.query(GestionFullInboundReceptionOp).filter_by(operation_id=operation_id).one_or_none()
    if existing is not None:
        return False
    db.add(
        GestionFullInboundReceptionOp(
            operation_id=operation_id,
            inbound_id=inbound_id,
            inventory_id=inventory_id,
            cantidad=cantidad,
            occurred_at=occurred_at,
        )
    )
    return True


def _op_from_ml_row(row: dict[str, Any], *, inventory_id: str) -> Optional[dict[str, Any]]:
    if str(row.get("type") or "").upper() != TYPE_INBOUND:
        return None
    inbound_id = _inbound_id_from_refs(row.get("external_references"))
    if not inbound_id:
        return None
    occurred = _parse_occurred_at(row.get("date_created"))
    if occurred is None:
        return None
    detail = row.get("detail") if isinstance(row.get("detail"), dict) else {}
    qty = detail.get("available_quantity")
    if qty is None:
        return None
    try:
        cantidad = int(qty)
        operation_id = int(row["id"])
    except (TypeError, ValueError, KeyError):
        return None
    return {
        "inbound_id": str(inbound_id),
        "operation_id": operation_id,
        "inventory_id": inventory_id,
        "cantidad": cantidad,
        "occurred_at": occurred,
    }


def reconcile_envio(
    db: Session,
    envio: GestionFullEnvio,
    *,
    client: MlHttpClient,
    now: Optional[datetime] = None,
) -> dict[str, Any]:
    """Pull recent receptions for inventory_ids on this inbound; maybe close."""
    now_dt = now or datetime.now(UTC)
    if envio.reception_closed_at is not None:
        return {"inbound_id": envio.inbound_id, "skipped": "closed"}

    inv_ids = [
        ln.inventory_id
        for ln in db.query(GestionFullPackageLine)
        .filter_by(package_id=envio.package_id, inbound_id=envio.inbound_id)
        .all()
    ]
    inserted = 0
    # Reuse last-inbound walk but collect via client search windows — lean: one lookback call path
    # using fetch_last_inbound which only returns newest; instead walk one 60d window via client.
    from app.core.config import settings
    from app.services.gestion_full.inbound import ENDPOINT_FAMILY, OPERATIONS_PATH

    seller = str(settings.ML_USER_ID or "")
    today = now_dt.date()
    start = today - timedelta(days=MAX_RANGE_DAYS - 1)
    for inventory_id in inv_ids:
        try:
            response = client.get(
                ENDPOINT_FAMILY,
                OPERATIONS_PATH,
                {
                    "seller_id": seller,
                    "inventory_id": inventory_id,
                    "date_from": start.isoformat(),
                    "date_to": today.isoformat(),
                    "type": TYPE_INBOUND,
                },
            )
        except Exception:  # noqa: BLE001 -- keep poller alive
            continue
        if response.status != 200 or not isinstance(response.body, dict):
            continue
        results = response.body.get("results") or []
        if not isinstance(results, list):
            continue
        for row in results:
            if not isinstance(row, dict):
                continue
            parsed = _op_from_ml_row(row, inventory_id=inventory_id)
            if parsed is None or parsed["inbound_id"] != envio.inbound_id:
                continue
            if upsert_reception_op(db, **parsed):
                inserted += 1
                if envio.last_reception_at is None or parsed["occurred_at"] > envio.last_reception_at:
                    envio.last_reception_at = parsed["occurred_at"]

    closed = False
    anchor = envio.last_reception_at or envio.created_at
    if anchor is not None:
        if anchor.tzinfo is None:
            anchor = anchor.replace(tzinfo=UTC)
        if now_dt - anchor >= CLOSE_AFTER_IDLE:
            envio.reception_closed_at = now_dt
            closed = True

    db.commit()
    return {
        "inbound_id": envio.inbound_id,
        "inserted": inserted,
        "closed": closed,
        "inventories": inv_ids,
    }


def envio_detail(db: Session, inbound_id: str) -> Optional[dict[str, Any]]:
    """Declared vs received for one inbound_id."""
    envio = db.get(GestionFullEnvio, inbound_id)
    if envio is None:
        return None
    lines = db.query(GestionFullPackageLine).filter_by(package_id=envio.package_id, inbound_id=inbound_id).all()
    ops = db.query(GestionFullInboundReceptionOp).filter_by(inbound_id=inbound_id).all()
    received_by_inv: dict[str, int] = {}
    for op in ops:
        received_by_inv[op.inventory_id] = received_by_inv.get(op.inventory_id, 0) + int(op.cantidad)

    detail_lines = []
    for ln in lines:
        received = received_by_inv.get(ln.inventory_id, 0)
        declared = int(ln.qty_export)
        detail_lines.append(
            {
                "inventory_id": ln.inventory_id,
                "user_product_id": ln.user_product_id,
                "declared": declared,
                "received": received,
                "diff": received - declared,
            }
        )
    from app.services.gestion_full.assign_inbound import human_envio_id

    return {
        "inbound_id": inbound_id,
        "human_id": human_envio_id(envio.package, inbound_id)
        if envio.package
        else f"{envio.week_monday.strftime('%Y%m%d')}_{inbound_id}",
        "week_monday": envio.week_monday.isoformat(),
        "package_id": envio.package_id,
        "reception_closed_at": envio.reception_closed_at.isoformat() if envio.reception_closed_at else None,
        "last_reception_at": envio.last_reception_at.isoformat() if envio.last_reception_at else None,
        "lines": detail_lines,
    }
