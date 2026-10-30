"""Persist and authorize Gestión Full overrides (per inventory_id)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.models.gestion_full_override import GestionFullOverride
from app.models.usuario import Usuario
from app.services.pm_scope import get_pares_marca_categoria_usuario

_RESOLVE_PRODUCT_SQL = text(
    """
    SELECT DISTINCT ON (i.inventory_id)
      l.producto_item_id,
      p.marca,
      p.categoria
    FROM ml_items i
    JOIN ml_item_product_links l
      ON l.item_id = i.item_id
     AND l.producto_item_id IS NOT NULL
     AND l.variation_id = 0
    JOIN productos_erp p ON p.item_id = l.producto_item_id
    WHERE i.inventory_id = :inventory_id
      AND i.never_existed IS NOT TRUE
      AND i.gone_at IS NULL
    ORDER BY i.inventory_id, i.item_id
    LIMIT 1
    """
)


def puede_editar_override_para(
    usuario: Usuario,
    db: Session,
    marca: Optional[str],
    categoria: Optional[str],
) -> bool:
    """True when the user may write an override for a product with this marca/categoria."""
    pares = get_pares_marca_categoria_usuario(db, usuario)
    if pares is None:
        return True
    if not pares:
        return False
    key = ((marca or "").upper(), (categoria or "").upper())
    return key in set(pares)


def usuario_puede_editar_algun_override(usuario: Usuario, db: Session) -> bool:
    """True when the user has full-view or at least one PM/sub-PM pair."""
    pares = get_pares_marca_categoria_usuario(db, usuario)
    if pares is None:
        return True
    return bool(pares)


def resolve_producto_por_inventory_id(db: Session, inventory_id: str) -> Optional[dict[str, Any]]:
    """ERP product linked to this Full inventory_id, or None if unknown."""
    row = db.execute(_RESOLVE_PRODUCT_SQL, {"inventory_id": inventory_id}).mappings().first()
    if row is None:
        return None
    return {
        "producto_item_id": row.producto_item_id,
        "marca": row.marca,
        "categoria": row.categoria,
    }


def upsert_override(
    db: Session,
    *,
    inventory_id: str,
    cantidad: int,
    usuario: Usuario,
) -> GestionFullOverride:
    """Create or update the override qty for inventory_id."""
    row = db.get(GestionFullOverride, inventory_id)
    now = datetime.now(UTC)
    if row is None:
        row = GestionFullOverride(
            inventory_id=inventory_id,
            cantidad=cantidad,
            updated_by_id=usuario.id,
            updated_at=now,
        )
        db.add(row)
    else:
        row.cantidad = cantidad
        row.updated_by_id = usuario.id
        row.updated_at = now
    db.commit()
    db.refresh(row)
    return row


def clear_override(db: Session, *, inventory_id: str) -> bool:
    """Delete override row. Returns True when a row was removed."""
    row = db.get(GestionFullOverride, inventory_id)
    if row is None:
        return False
    db.delete(row)
    db.commit()
    return True
