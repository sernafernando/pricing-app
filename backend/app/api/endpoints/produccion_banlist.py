"""
Endpoints para gestión de banlist y pre-armado en Producción - Preparación
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import and_
from typing import List
from pydantic import BaseModel, ConfigDict
from datetime import datetime

from app.core.database import get_db
from app.models.produccion_banlist import ProduccionBanlist, ProduccionPrearmado
from app.models.producto import ProductoERP
from app.api.deps import get_current_user, get_current_admin

router = APIRouter()


# Schemas
class BanlistItemRequest(BaseModel):
    item_id: int
    motivo: str | None = None


class BanlistItemResponse(BaseModel):
    id: int
    item_id: int
    motivo: str | None
    usuario_id: int
    fecha_creacion: datetime

    model_config = ConfigDict(from_attributes=True)


class PrearmadoItemResponse(BaseModel):
    id: int
    item_id: int
    cantidad: int
    usuario_id: int
    fecha_creacion: datetime

    model_config = ConfigDict(from_attributes=True)


class PrearmadoRequest(BaseModel):
    cantidad: int = 1


# ========================================================================
# BANLIST DE PRODUCCIÓN
# ========================================================================

@router.get("/produccion-banlist", response_model=List[BanlistItemResponse])
async def obtener_banlist(
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """Obtiene todos los items en el banlist de producción"""
    items = db.query(ProduccionBanlist).order_by(ProduccionBanlist.fecha_creacion.desc()).all()
    return items


@router.post("/produccion-banlist", response_model=BanlistItemResponse)
async def agregar_a_banlist(
    request: BanlistItemRequest,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_admin)
):
    """Agrega un item al banlist de producción (solo admin)"""
    
    # Verificar que el producto existe
    producto = db.query(ProductoERP).filter(ProductoERP.item_id == request.item_id).first()
    if not producto:
        raise HTTPException(404, "Producto no encontrado")
    
    # Verificar si ya está en el banlist
    existe = db.query(ProduccionBanlist).filter(ProduccionBanlist.item_id == request.item_id).first()
    if existe:
        raise HTTPException(400, "El producto ya está en el banlist")
    
    # Crear registro
    banlist_item = ProduccionBanlist(
        item_id=request.item_id,
        motivo=request.motivo,
        usuario_id=current_user.id
    )
    
    db.add(banlist_item)
    db.commit()
    db.refresh(banlist_item)
    
    return banlist_item


@router.delete("/produccion-banlist/{item_id}")
async def quitar_de_banlist(
    item_id: int,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_admin)
):
    """Quita un item del banlist de producción (solo admin)"""
    
    banlist_item = db.query(ProduccionBanlist).filter(ProduccionBanlist.item_id == item_id).first()
    if not banlist_item:
        raise HTTPException(404, "El producto no está en el banlist")
    
    db.delete(banlist_item)
    db.commit()
    
    return {"message": "Producto removido del banlist", "item_id": item_id}


# ========================================================================
# PRE-ARMADO
# ========================================================================

@router.get("/produccion-prearmado", response_model=List[PrearmadoItemResponse])
async def obtener_prearmados(
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """Obtiene todos los items marcados como pre-armados"""
    items = db.query(ProduccionPrearmado).order_by(ProduccionPrearmado.fecha_creacion.desc()).all()
    return items


@router.post("/produccion-prearmado/{item_id}", response_model=PrearmadoItemResponse)
async def marcar_prearmado(
    item_id: int,
    request: PrearmadoRequest,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """Marca un item como pre-armado con cantidad específica"""
    
    # Verificar que el producto existe
    producto = db.query(ProductoERP).filter(ProductoERP.item_id == item_id).first()
    if not producto:
        raise HTTPException(404, "Producto no encontrado")
    
    # Verificar si ya está marcado
    existe = db.query(ProduccionPrearmado).filter(ProduccionPrearmado.item_id == item_id).first()
    if existe:
        # Si ya existe, actualizar la cantidad
        existe.cantidad = request.cantidad
        existe.usuario_id = current_user.id
        db.commit()
        db.refresh(existe)
        return existe
    
    # Crear registro nuevo
    prearmado_item = ProduccionPrearmado(
        item_id=item_id,
        cantidad=request.cantidad,
        usuario_id=current_user.id
    )
    
    db.add(prearmado_item)
    db.commit()
    db.refresh(prearmado_item)
    
    return prearmado_item


@router.delete("/produccion-prearmado/{item_id}")
async def desmarcar_prearmado(
    item_id: int,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """Desmarca un item como pre-armado"""
    
    prearmado_item = db.query(ProduccionPrearmado).filter(ProduccionPrearmado.item_id == item_id).first()
    if not prearmado_item:
        raise HTTPException(404, "El producto no está marcado como pre-armado")
    
    db.delete(prearmado_item)
    db.commit()
    
    return {"message": "Marca de pre-armado removida", "item_id": item_id}


@router.post("/produccion-prearmado/limpiar-desaparecidos")
async def limpiar_prearmados_desaparecidos(
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """
    Limpia marcas de pre-armado de productos que ya no existen en el ERP.
    Esto se ejecuta automáticamente o manualmente.
    """
    # Obtener todos los prearmados
    prearmados = db.query(ProduccionPrearmado).all()
    
    eliminados = []
    for prearmado in prearmados:
        # Verificar si el producto existe en ERP
        producto = db.query(ProductoERP).filter(ProductoERP.item_id == prearmado.item_id).first()
        if not producto:
            eliminados.append(prearmado.item_id)
            db.delete(prearmado)
    
    db.commit()
    
    return {
        "message": f"Limpieza completada: {len(eliminados)} productos pre-armados eliminados",
        "eliminados": eliminados,
        "total_revisados": len(prearmados)
    }
