"""Persist and authorize Gestión Full overrides (per inventory_id)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.models.auditoria import TipoAccion
from app.models.gestion_full_override import GestionFullOverride
from app.models.usuario import Usuario
from app.services.gestion_full.audit import registrar
from app.services.gestion_full.inventory_keys import (
    is_synthetic_inventory_id,
    synthetic_inventory_id,
    user_product_id_from_synthetic,
)
from app.services.pm_scope import get_pares_marca_categoria_usuario

_RESOLVE_MLAU_BY_INVENTORY_SQL = text(
    """
    SELECT user_product_id
    FROM ml_items
    WHERE inventory_id = :inventory_id
      AND never_existed IS NOT TRUE
      AND gone_at IS NULL
      AND user_product_id IS NOT NULL
    ORDER BY item_id
    LIMIT 1
    """
)

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

_RESOLVE_PRODUCT_BY_MLAU_SQL = text(
    """
    SELECT DISTINCT ON (i.user_product_id)
      l.producto_item_id,
      p.marca,
      p.categoria
    FROM ml_items i
    JOIN ml_item_product_links l
      ON l.item_id = i.item_id
     AND l.producto_item_id IS NOT NULL
     AND l.variation_id = 0
    JOIN productos_erp p ON p.item_id = l.producto_item_id
    WHERE i.user_product_id = :user_product_id
      AND i.never_existed IS NOT TRUE
      AND i.gone_at IS NULL
    ORDER BY i.user_product_id, (i.inventory_id IS NULL), i.inventory_id, i.item_id
    LIMIT 1
    """
)


def puede_editar_con_pares(
    pares: Optional[list],
    marca: Optional[str],
    categoria: Optional[str],
) -> bool:
    """True when preloaded ``pares`` allows writing an override for marca/categoria.

    ``pares`` is the return of ``get_pares_marca_categoria_usuario`` (``None`` = full view).
    """
    if pares is None:
        return True
    if not pares:
        return False
    key = ((marca or "").upper(), (categoria or "").upper())
    return key in {(m.upper(), c.upper()) for m, c in pares}


def puede_editar_override_para(
    usuario: Usuario,
    db: Session,
    marca: Optional[str],
    categoria: Optional[str],
) -> bool:
    """True when the user may write an override for a product with this marca/categoria."""
    return puede_editar_con_pares(
        get_pares_marca_categoria_usuario(db, usuario),
        marca,
        categoria,
    )


def usuario_puede_editar_algun_override(usuario: Usuario, db: Session) -> bool:
    """True when the user has full-view or at least one PM/sub-PM pair."""
    pares = get_pares_marca_categoria_usuario(db, usuario)
    if pares is None:
        return True
    return bool(pares)


def resolve_producto_por_inventory_id(db: Session, inventory_id: str) -> Optional[dict[str, Any]]:
    """ERP product linked to this Full inventory_id (or NOINV:{MLAU}), or None."""
    mlau = user_product_id_from_synthetic(inventory_id)
    if mlau is not None:
        row = (
            db.execute(
                _RESOLVE_PRODUCT_BY_MLAU_SQL,
                {"user_product_id": mlau},
            )
            .mappings()
            .first()
        )
    else:
        row = db.execute(_RESOLVE_PRODUCT_SQL, {"inventory_id": inventory_id}).mappings().first()
    if row is None:
        return None
    return {
        "producto_item_id": row.producto_item_id,
        "marca": row.marca,
        "categoria": row.categoria,
    }


def _legacy_noinv_key_for_real(db: Session, inventory_id: str) -> Optional[str]:
    """NOINV:{MLAU} twin when ``inventory_id`` is a real Código ML, else None."""
    if is_synthetic_inventory_id(inventory_id):
        return None
    row = (
        db.execute(
            _RESOLVE_MLAU_BY_INVENTORY_SQL,
            {"inventory_id": inventory_id},
        )
        .mappings()
        .first()
    )
    if row is None or not row.user_product_id:
        return None
    return synthetic_inventory_id(str(row.user_product_id))


def _delete_override_row(
    db: Session,
    *,
    inventory_id: str,
    usuario: Usuario,
    cantidad_antes: Optional[int],
) -> None:
    registrar(
        db,
        tipo=TipoAccion.GESTION_FULL_OVERRIDE,
        usuario_id=int(usuario.id),
        antes=(None if cantidad_antes is None else {"inventory_id": inventory_id, "cantidad": int(cantidad_antes)}),
        despues={"inventory_id": inventory_id, "cantidad": None},
    )


def upsert_override(
    db: Session,
    *,
    inventory_id: str,
    cantidad: int,
    usuario: Usuario,
) -> GestionFullOverride:
    """Create or update the override qty for inventory_id.

    When writing under a real Código ML, drop any leftover ``NOINV:{MLAU}`` twin
    so the listing LATERAL join cannot resurrect a stale synthetic override.
    """
    row = db.get(GestionFullOverride, inventory_id)
    now = datetime.now(UTC)
    antes = None if row is None else {"inventory_id": inventory_id, "cantidad": int(row.cantidad)}
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
    registrar(
        db,
        tipo=TipoAccion.GESTION_FULL_OVERRIDE,
        usuario_id=int(usuario.id),
        despues={"inventory_id": inventory_id, "cantidad": int(cantidad)},
        antes=antes,
    )
    legacy = _legacy_noinv_key_for_real(db, inventory_id)
    if legacy is not None and legacy != inventory_id:
        twin = db.get(GestionFullOverride, legacy)
        if twin is not None:
            cantidad_antes = int(twin.cantidad)
            db.delete(twin)
            _delete_override_row(
                db,
                inventory_id=legacy,
                usuario=usuario,
                cantidad_antes=cantidad_antes,
            )
    db.commit()
    db.refresh(row)
    return row


def clear_override(db: Session, *, inventory_id: str, usuario: Usuario) -> bool:
    """Delete override row(s). Returns True when at least one row was removed.

    Clearing by real Código ML also removes ``NOINV:{MLAU}`` for that MLAU, so a
    pre-Full override cannot stick after Melí assigns inventory_id.
    """
    removed = False
    keys = [inventory_id]
    legacy = _legacy_noinv_key_for_real(db, inventory_id)
    if legacy is not None and legacy not in keys:
        keys.append(legacy)

    for key in keys:
        row = db.get(GestionFullOverride, key)
        if row is None:
            continue
        cantidad_antes = int(row.cantidad)
        db.delete(row)
        _delete_override_row(
            db,
            inventory_id=key,
            usuario=usuario,
            cantidad_antes=cantidad_antes,
        )
        removed = True

    if removed:
        db.commit()
    return removed
