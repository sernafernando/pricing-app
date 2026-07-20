"""
Productos - Color marking endpoints.

Handles color marking for productos (ML view and Tienda view),
both individual and batch operations. Colors are scoped per `equipo`
(team) via `producto_color`; when no `equipo_id` is given (or it resolves
to the global "U" team) the legacy `productos_pricing.color_marcado[_tienda]`
columns are also kept in sync so existing readers keep working until the
read-side migrates to `producto_color` (PR3).
"""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.equipo import ProductoColor
from app.models.producto import ProductoPricing
from app.models.usuario import Usuario
from app.api.deps import get_current_user
from app.api.endpoints.productos_shared import (
    ColorLoteRequest,
    color_slot,
    get_global_equipo_id,
    puede_escribir_layer,
)

router = APIRouter()

COLORES_VALIDOS = ["rojo", "naranja", "amarillo", "verde", "azul", "purpura", "gris", None]


def _validar_color(color: Optional[str]) -> None:
    if color not in COLORES_VALIDOS:
        raise HTTPException(status_code=400, detail=f"Color inválido: {color}. Válidos: {COLORES_VALIDOS}")


def _upsert_producto_color(
    db: Session, equipo_id: int, item_id: int, vista: Optional[str], color: Optional[str], user_id: int
) -> None:
    """Get-or-create style upsert (SQLite-safe, no ON CONFLICT) touching only the targeted slot."""
    row = db.query(ProductoColor).filter(ProductoColor.equipo_id == equipo_id, ProductoColor.item_id == item_id).first()
    if row is None:
        row = ProductoColor(equipo_id=equipo_id, item_id=item_id)
        db.add(row)

    slot_attr = color_slot(vista)
    setattr(row, slot_attr.key, color)
    row.updated_by = user_id


def _dual_write_legacy(db: Session, item_id: int, vista: Optional[str], color: Optional[str]) -> None:
    # TRANSITIONAL: dual-write to legacy column for U layer; remove in PR3 when reads migrate
    producto_pricing = db.query(ProductoPricing).filter(ProductoPricing.item_id == item_id).first()
    campo = "color_marcado_tienda" if vista == "tienda" else "color_marcado"

    if not producto_pricing:
        producto_pricing = ProductoPricing(item_id=item_id, **{campo: color})
        db.add(producto_pricing)
    else:
        setattr(producto_pricing, campo, color)


def _resolver_equipo_id(db: Session, equipo_id: Optional[int]) -> int:
    return equipo_id if equipo_id is not None else get_global_equipo_id(db)


@router.patch("/productos/{item_id}/color")
def actualizar_color_producto(
    item_id: int,
    request: dict,
    equipo_id: Optional[int] = None,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    """Actualiza el color de marcado (vista ML) de un producto para un equipo (default: global)."""
    color = request.get("color")
    _validar_color(color)

    equipo_id = _resolver_equipo_id(db, equipo_id)
    puede_escribir_layer(db, current_user, equipo_id)

    _upsert_producto_color(db, equipo_id, item_id, "ml", color, current_user.id)

    color_anterior = None
    if equipo_id == get_global_equipo_id(db):
        producto_pricing = db.query(ProductoPricing).filter(ProductoPricing.item_id == item_id).first()
        if producto_pricing:
            color_anterior = producto_pricing.color_marcado
        _dual_write_legacy(db, item_id, "ml", color)

    db.commit()

    return {"mensaje": "Color actualizado", "color_anterior": color_anterior, "color_nuevo": color}


@router.patch("/productos/{item_id}/color-tienda")
def actualizar_color_producto_tienda(
    item_id: int,
    request: dict,
    equipo_id: Optional[int] = None,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    """Actualiza el color de marcado de tienda de un producto para un equipo (default: global)."""
    color = request.get("color")
    _validar_color(color)

    equipo_id = _resolver_equipo_id(db, equipo_id)
    puede_escribir_layer(db, current_user, equipo_id)

    _upsert_producto_color(db, equipo_id, item_id, "tienda", color, current_user.id)

    color_anterior = None
    if equipo_id == get_global_equipo_id(db):
        producto_pricing = db.query(ProductoPricing).filter(ProductoPricing.item_id == item_id).first()
        if producto_pricing:
            color_anterior = producto_pricing.color_marcado_tienda
        _dual_write_legacy(db, item_id, "tienda", color)

    db.commit()

    return {"mensaje": "Color tienda actualizado", "color_anterior": color_anterior, "color_nuevo": color}


@router.post("/productos/actualizar-color-lote")
def actualizar_color_productos_lote(
    request: ColorLoteRequest, db: Session = Depends(get_db), current_user: Usuario = Depends(get_current_user)
):
    """Actualiza el color de marcado (vista ML) de múltiples productos para un equipo (default: global)."""
    if not request.item_ids:
        raise HTTPException(status_code=400, detail="Debe proporcionar al menos un item_id")

    _validar_color(request.color)

    equipo_id = _resolver_equipo_id(db, request.equipo_id)
    puede_escribir_layer(db, current_user, equipo_id)

    es_global = equipo_id == get_global_equipo_id(db)

    for item_id in request.item_ids:
        _upsert_producto_color(db, equipo_id, item_id, "ml", request.color, current_user.id)
        if es_global:
            _dual_write_legacy(db, item_id, "ml", request.color)

    db.commit()

    count = len(request.item_ids)
    return {"mensaje": f"{count} productos actualizados", "count": count}


@router.post("/productos/actualizar-color-tienda-lote")
def actualizar_color_productos_tienda_lote(
    request: ColorLoteRequest, db: Session = Depends(get_db), current_user: Usuario = Depends(get_current_user)
):
    """Actualiza el color de marcado tienda de múltiples productos para un equipo (default: global)."""
    if not request.item_ids:
        raise HTTPException(status_code=400, detail="Debe proporcionar al menos un item_id")

    _validar_color(request.color)

    equipo_id = _resolver_equipo_id(db, request.equipo_id)
    puede_escribir_layer(db, current_user, equipo_id)

    es_global = equipo_id == get_global_equipo_id(db)

    for item_id in request.item_ids:
        _upsert_producto_color(db, equipo_id, item_id, "tienda", request.color, current_user.id)
        if es_global:
            _dual_write_legacy(db, item_id, "tienda", request.color)

    db.commit()

    count = len(request.item_ids)
    return {"mensaje": f"{count} productos actualizados (tienda)", "count": count}
