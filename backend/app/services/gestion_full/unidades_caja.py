"""Persist units-per-closed-box for Gestión Full (per ERP product)."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.models.gestion_full_unidades_caja import GestionFullUnidadesCaja
from app.models.usuario import Usuario


def upsert_unidades_caja(
    db: Session,
    *,
    producto_item_id: int,
    unidades: int,
    usuario: Usuario,
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
