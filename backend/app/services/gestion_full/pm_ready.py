"""PM ready / lock for Gestión Full (ERP + MLAU).

Marking ready freezes qty_pm = override ?? sugerido (capped by stock_erp) and
blocks further override edits until a gestor unlocks (row deleted).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.models.gestion_full_pm_ready import GestionFullPmReady
from app.models.usuario import Usuario
from app.services.gestion_full.listing import _sugerido

_ROW_FOR_READY_SQL = text(
    """
    WITH linked AS (
      SELECT DISTINCT ON (l.producto_item_id, i.user_product_id)
        l.producto_item_id,
        i.inventory_id,
        i.user_product_id
      FROM ml_item_product_links l
      JOIN ml_items i ON i.item_id = l.item_id
      WHERE l.producto_item_id = :producto_item_id
        AND i.user_product_id = :user_product_id
        AND l.variation_id = 0
        AND i.inventory_id IS NOT NULL
        AND i.user_product_id IS NOT NULL
        AND i.never_existed IS NOT TRUE
        AND i.gone_at IS NULL
      ORDER BY l.producto_item_id, i.user_product_id, i.inventory_id, i.item_id
      LIMIT 1
    )
    SELECT
      linked.inventory_id,
      linked.user_product_id,
      linked.producto_item_id,
      p.marca,
      p.categoria,
      p.stock AS stock_erp,
      st.full_quantity AS stock_full,
      inbound.cantidad AS target,
      o.cantidad AS override
    FROM linked
    JOIN productos_erp p ON p.item_id = linked.producto_item_id
    LEFT JOIN ml_user_product_stock st ON st.user_product_id = linked.user_product_id
    LEFT JOIN ml_fulfillment_last_inbound inbound ON inbound.inventory_id = linked.inventory_id
    LEFT JOIN gestion_full_override o ON o.inventory_id = linked.inventory_id
    """
)

_RESOLVE_KEY_BY_INVENTORY_SQL = text(
    """
    SELECT DISTINCT ON (i.inventory_id)
      l.producto_item_id,
      i.user_product_id,
      p.marca,
      p.categoria
    FROM ml_items i
    JOIN ml_item_product_links l
      ON l.item_id = i.item_id
     AND l.producto_item_id IS NOT NULL
     AND l.variation_id = 0
    JOIN productos_erp p ON p.item_id = l.producto_item_id
    WHERE i.inventory_id = :inventory_id
      AND i.user_product_id IS NOT NULL
      AND i.never_existed IS NOT TRUE
      AND i.gone_at IS NULL
    ORDER BY i.inventory_id, i.item_id
    LIMIT 1
    """
)


def compute_qty_pm(
    *,
    override: Optional[int],
    target: Optional[int],
    stock_full: Optional[int],
    stock_erp: Optional[int],
) -> Optional[int]:
    """Frozen send qty: override if set, else sugerido. Both capped by stock_erp.

    Returns None when neither override nor sugerido is available (cannot close).
    """
    stock_cap = max(0, int(stock_erp or 0))
    if override is not None:
        return min(max(0, int(override)), stock_cap)
    sugerido = _sugerido(target, stock_full, stock_erp)
    if sugerido is None:
        return None
    return sugerido


def get_pm_ready(
    db: Session,
    *,
    producto_item_id: int,
    user_product_id: str,
) -> Optional[GestionFullPmReady]:
    """Return ready row if the PM already closed this line."""
    return db.get(GestionFullPmReady, (producto_item_id, user_product_id))


def is_line_locked(
    db: Session,
    *,
    producto_item_id: int,
    user_product_id: str,
) -> bool:
    """True when PM ready row exists (override edits blocked)."""
    return (
        get_pm_ready(
            db,
            producto_item_id=producto_item_id,
            user_product_id=user_product_id,
        )
        is not None
    )


def load_row_for_ready(
    db: Session,
    *,
    producto_item_id: int,
    user_product_id: str,
) -> Optional[dict[str, Any]]:
    """Listing metrics + marca/categoria for one ERP+MLAU row, or None."""
    row = (
        db.execute(
            _ROW_FOR_READY_SQL,
            {
                "producto_item_id": producto_item_id,
                "user_product_id": user_product_id,
            },
        )
        .mappings()
        .first()
    )
    if row is None:
        return None
    return dict(row)


def resolve_ready_key_por_inventory_id(
    db: Session,
    inventory_id: str,
) -> Optional[dict[str, Any]]:
    """ERP + MLAU (+ marca/categoria) for an inventory_id, or None."""
    row = (
        db.execute(
            _RESOLVE_KEY_BY_INVENTORY_SQL,
            {"inventory_id": inventory_id},
        )
        .mappings()
        .first()
    )
    if row is None:
        return None
    return {
        "producto_item_id": row.producto_item_id,
        "user_product_id": row.user_product_id,
        "marca": row.marca,
        "categoria": row.categoria,
    }


def mark_pm_ready(
    db: Session,
    *,
    producto_item_id: int,
    user_product_id: str,
    usuario: Usuario,
) -> GestionFullPmReady:
    """Freeze qty_pm and lock the line. Idempotent when already ready."""
    existing = get_pm_ready(
        db,
        producto_item_id=producto_item_id,
        user_product_id=user_product_id,
    )
    if existing is not None:
        return existing

    row = load_row_for_ready(
        db,
        producto_item_id=producto_item_id,
        user_product_id=user_product_id,
    )
    if row is None:
        raise LookupError("fila Gestión Full no encontrada")

    qty = compute_qty_pm(
        override=row.get("override"),
        target=row.get("target"),
        stock_full=row.get("stock_full"),
        stock_erp=row.get("stock_erp"),
    )
    if qty is None:
        raise ValueError("sin cantidad decidida (override o sugerido)")

    ready = GestionFullPmReady(
        producto_item_id=producto_item_id,
        user_product_id=user_product_id,
        inventory_id=row["inventory_id"],
        qty_pm=qty,
        ready_by_id=usuario.id,
        ready_at=datetime.now(UTC),
    )
    db.add(ready)
    db.commit()
    db.refresh(ready)
    return ready


def unlock_pm_ready(
    db: Session,
    *,
    producto_item_id: int,
    user_product_id: str,
) -> bool:
    """Remove ready lock so the PM can edit again. Returns True if a row was removed."""
    row = get_pm_ready(
        db,
        producto_item_id=producto_item_id,
        user_product_id=user_product_id,
    )
    if row is None:
        return False
    db.delete(row)
    db.commit()
    return True
