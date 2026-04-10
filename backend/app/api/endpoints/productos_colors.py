"""
Productos - Color marking endpoints.

Handles color marking for productos (ML view and Tienda view),
both individual and batch operations.
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List
from app.core.database import get_db
from app.models.producto import ProductoPricing
from app.models.usuario import Usuario
from app.api.deps import get_current_user
from app.api.endpoints.productos_shared import ColorLoteRequest

router = APIRouter()


@router.patch("/productos/{item_id}/color")
def actualizar_color_producto(
    item_id: int, request: dict, db: Session = Depends(get_db), current_user: Usuario = Depends(get_current_user)
):
    """Actualiza el color de marcado de un producto"""
    from app.services.permisos_service import verificar_permiso

    if not verificar_permiso(db, current_user, "productos.marcar_color"):
        raise HTTPException(status_code=403, detail="No tienes permiso para marcar colores")

    color = request.get("color")

    # Validar color
    colores_validos = ["rojo", "naranja", "amarillo", "verde", "azul", "purpura", "gris", None]
    if color not in colores_validos:
        raise HTTPException(status_code=400, detail=f"Color inválido: {color}. Válidos: {colores_validos}")

    # Buscar producto pricing, crear si no existe
    producto_pricing = db.query(ProductoPricing).filter(ProductoPricing.item_id == item_id).first()

    if not producto_pricing:
        producto_pricing = ProductoPricing(item_id=item_id, color_marcado=color)
        db.add(producto_pricing)
        db.commit()
        return {"mensaje": "Color actualizado", "color_anterior": None, "color_nuevo": color}

    color_anterior = producto_pricing.color_marcado
    producto_pricing.color_marcado = color
    db.commit()

    return {"mensaje": "Color actualizado", "color_anterior": color_anterior, "color_nuevo": color}


@router.patch("/productos/{item_id}/color-tienda")
def actualizar_color_producto_tienda(
    item_id: int, request: dict, db: Session = Depends(get_db), current_user: Usuario = Depends(get_current_user)
):
    """Actualiza el color de marcado de tienda de un producto"""
    from app.services.permisos_service import verificar_permiso

    if not verificar_permiso(db, current_user, "productos.marcar_color"):
        raise HTTPException(status_code=403, detail="No tienes permiso para marcar colores")

    color = request.get("color")

    # Validar color
    colores_validos = ["rojo", "naranja", "amarillo", "verde", "azul", "purpura", "gris", None]
    if color not in colores_validos:
        raise HTTPException(status_code=400, detail=f"Color inválido: {color}. Válidos: {colores_validos}")

    # Buscar producto pricing, crear si no existe
    producto_pricing = db.query(ProductoPricing).filter(ProductoPricing.item_id == item_id).first()

    if not producto_pricing:
        producto_pricing = ProductoPricing(item_id=item_id, color_marcado_tienda=color)
        db.add(producto_pricing)
        db.commit()
        return {"mensaje": "Color tienda actualizado", "color_anterior": None, "color_nuevo": color}

    color_anterior = producto_pricing.color_marcado_tienda
    producto_pricing.color_marcado_tienda = color
    db.commit()

    return {"mensaje": "Color tienda actualizado", "color_anterior": color_anterior, "color_nuevo": color}


@router.post("/productos/actualizar-color-lote")
def actualizar_color_productos_lote(
    request: ColorLoteRequest, db: Session = Depends(get_db), current_user: Usuario = Depends(get_current_user)
):
    """Actualiza el color de marcado de múltiples productos"""

    if not request.item_ids:
        raise HTTPException(status_code=400, detail="Debe proporcionar al menos un item_id")

    colores_validos = ["rojo", "naranja", "amarillo", "verde", "azul", "purpura", "gris", None]
    if request.color not in colores_validos:
        raise HTTPException(status_code=400, detail="Color inválido")

    count = (
        db.query(ProductoPricing)
        .filter(ProductoPricing.item_id.in_(request.item_ids))
        .update({"color_marcado": request.color}, synchronize_session=False)
    )

    db.commit()

    return {"mensaje": f"{count} productos actualizados", "count": count}


@router.post("/productos/actualizar-color-tienda-lote")
def actualizar_color_productos_tienda_lote(
    request: ColorLoteRequest, db: Session = Depends(get_db), current_user: Usuario = Depends(get_current_user)
):
    """Actualiza el color de marcado tienda de múltiples productos"""

    if not request.item_ids:
        raise HTTPException(status_code=400, detail="Debe proporcionar al menos un item_id")

    colores_validos = ["rojo", "naranja", "amarillo", "verde", "azul", "purpura", "gris", None]
    if request.color not in colores_validos:
        raise HTTPException(status_code=400, detail="Color inválido")

    count = (
        db.query(ProductoPricing)
        .filter(ProductoPricing.item_id.in_(request.item_ids))
        .update({"color_marcado_tienda": request.color}, synchronize_session=False)
    )

    db.commit()

    return {"mensaje": f"{count} productos actualizados (tienda)", "count": count}
