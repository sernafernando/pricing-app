"""Persist units-per-closed-box for Gestión Full (per ERP product)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.gestion_full_unidades_caja import GestionFullUnidadesCaja
from app.models.producto import ProductoERP
from app.models.usuario import Usuario


def upsert_unidades_caja(
    db: Session,
    *,
    producto_item_id: int,
    unidades: int,
    usuario: Usuario,
    commit: bool = True,
) -> GestionFullUnidadesCaja:
    """Create or update units-per-box for an ERP product. unidades must be >= 1."""
    if unidades < 1:
        raise ValueError("unidades must be >= 1")
    row = db.get(GestionFullUnidadesCaja, producto_item_id)
    if row is None:
        row = GestionFullUnidadesCaja(
            producto_item_id=producto_item_id,
            unidades=unidades,
            updated_by_id=usuario.id,
            updated_at=datetime.now(UTC),
        )
        db.add(row)
    else:
        row.unidades = unidades
        row.updated_by_id = usuario.id
        row.updated_at = datetime.now(UTC)
    if commit:
        db.commit()
        db.refresh(row)
    return row


def clear_unidades_caja(db: Session, *, producto_item_id: int) -> None:
    """Delete the units-per-box row if present."""
    row = db.get(GestionFullUnidadesCaja, producto_item_id)
    if row is None:
        return
    db.delete(row)
    db.commit()


def import_unidades_caja_por_ean(
    db: Session,
    *,
    rows: list[dict[str, Any]],
    usuario: Usuario,
) -> dict[str, Any]:
    """Upsert many units-per-box rows resolved by ERP EAN (`productos_erp.codigo`).

    Each row: ``{"ean": str, "unidades": int}``. Unknown EANs are skipped with
    an error entry; invalid unidades likewise. One commit at the end.
    """
    updated = 0
    errors: list[dict[str, Any]] = []
    for idx, raw in enumerate(rows):
        ean = str(raw.get("ean") or "").strip()
        unidades_raw = raw.get("unidades")
        if not ean:
            errors.append({"index": idx, "ean": ean, "error": "ean vacío"})
            continue
        try:
            unidades = int(unidades_raw)
        except (TypeError, ValueError):
            errors.append({"index": idx, "ean": ean, "error": "unidades inválidas"})
            continue
        if unidades < 1:
            errors.append({"index": idx, "ean": ean, "error": "unidades debe ser >= 1"})
            continue
        producto = db.execute(select(ProductoERP).where(ProductoERP.codigo == ean)).scalar_one_or_none()
        if producto is None:
            errors.append({"index": idx, "ean": ean, "error": "EAN no encontrado"})
            continue
        upsert_unidades_caja(
            db,
            producto_item_id=producto.item_id,
            unidades=unidades,
            usuario=usuario,
            commit=False,
        )
        updated += 1
    if updated:
        db.commit()
    return {"updated": updated, "errors": errors}
