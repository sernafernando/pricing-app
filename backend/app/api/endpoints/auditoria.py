from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import and_, or_
from typing import List, Optional 
from app.core.database import get_db
from app.api.deps import get_current_user
from app.models.usuario import Usuario
from app.models.auditoria_precio import AuditoriaPrecio
from app.models.auditoria import Auditoria, TipoAccion
from pydantic import BaseModel
from datetime import datetime

router = APIRouter()

class AuditoriaResponse(BaseModel):
    id: int
    producto_id: int
    usuario_nombre: str
    usuario_email: str
    precio_anterior: float
    precio_contado_anterior: float
    precio_nuevo: float
    precio_contado_nuevo: float
    fecha_cambio: datetime
    comentario: str = None
    
    class Config:
        from_attributes = True

@router.get("/productos/{producto_id}/auditoria", response_model=List[AuditoriaResponse])
async def obtener_auditoria_producto(
    producto_id: int,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user)
):
    """Obtiene el historial de cambios de precio de un producto"""
    
    # Buscar el producto_pricing por item_id
    from app.models.producto import ProductoPricing
    producto_pricing = db.query(ProductoPricing).filter(
        ProductoPricing.item_id == producto_id
    ).first()
    
    if not producto_pricing:
        return []  # Si no tiene pricing, no tiene auditoría
    
    # Buscar auditorías del producto_pricing
    auditorias = db.query(AuditoriaPrecio).filter(
        AuditoriaPrecio.producto_id == producto_pricing.id
    ).order_by(AuditoriaPrecio.fecha_cambio.desc()).all()
    
    resultado = []
    for aud in auditorias:
        resultado.append({
            "id": aud.id,
            "producto_id": aud.producto_id,
            "usuario_nombre": aud.usuario.nombre,
            "usuario_email": aud.usuario.email,
            "precio_anterior": float(aud.precio_anterior or 0),
            "precio_contado_anterior": float(aud.precio_contado_anterior or 0),
            "precio_nuevo": float(aud.precio_nuevo or 0),
            "precio_contado_nuevo": float(aud.precio_contado_nuevo or 0),
            "fecha_cambio": aud.fecha_cambio,
            "comentario": aud.comentario
        })
    
    return resultado

@router.get("/auditoria/ultimos-cambios", response_model=List[dict])
async def obtener_ultimos_cambios(
    limit: int = 50,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user)
):
    """Obtiene los últimos N cambios de precio de todos los productos"""
    
    from app.models.producto import ProductoPricing, ProductoERP
    
    auditorias = db.query(
        AuditoriaPrecio,
        ProductoPricing,
        ProductoERP
    ).join(
        ProductoPricing, AuditoriaPrecio.producto_id == ProductoPricing.id
    ).join(
        ProductoERP, ProductoPricing.item_id == ProductoERP.item_id
    ).order_by(
        AuditoriaPrecio.fecha_cambio.desc()
    ).limit(limit).all()
    
    resultado = []
    for aud, pricing, producto in auditorias:
        cambio = float(aud.precio_nuevo or 0) - float(aud.precio_anterior or 0)
        porcentaje = 0
        if aud.precio_anterior and aud.precio_anterior > 0:
            porcentaje = (cambio / float(aud.precio_anterior)) * 100
        
        resultado.append({
            "id": aud.id,
            "fecha_cambio": aud.fecha_cambio,
            "usuario_nombre": aud.usuario.nombre,
            "usuario_email": aud.usuario.email,
            "item_id": producto.item_id,
            "codigo": producto.codigo,
            "descripcion": producto.descripcion,
            "marca": producto.marca,
            "precio_anterior": float(aud.precio_anterior or 0),
            "precio_nuevo": float(aud.precio_nuevo or 0),
            "cambio": round(cambio, 2),
            "cambio_porcentaje": round(porcentaje, 2),
            "comentario": aud.comentario
        })
    
    return resultado


class AuditoriaGeneralResponse(BaseModel):
    id: int
    item_id: Optional[int]
    usuario_id: int
    usuario_nombre: Optional[str]
    tipo_accion: str
    valores_anteriores: Optional[dict]
    valores_nuevos: Optional[dict]
    es_masivo: bool
    productos_afectados: Optional[int]
    comentario: Optional[str]
    fecha: datetime

    class Config:
        from_attributes = True

class AuditoriaListResponse(BaseModel):
    total: int
    page: int
    page_size: int
    registros: List[AuditoriaGeneralResponse]

@router.get("/auditoria", response_model=AuditoriaListResponse)
async def listar_auditoria_general(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
    usuarios: Optional[str] = None,
    tipos_accion: Optional[str] = None,
    fecha_desde: Optional[str] = None,
    fecha_hasta: Optional[str] = None,
    item_id: Optional[int] = None,
    es_masivo: Optional[bool] = None,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user)
):
    """Lista registros de auditoría general con filtros"""
    
    query = db.query(Auditoria, Usuario).join(
        Usuario, Auditoria.usuario_id == Usuario.id
    )
    
    if usuarios:
        usuarios_ids = [int(u) for u in usuarios.split(',')]
        query = query.filter(Auditoria.usuario_id.in_(usuarios_ids))
    
    if tipos_accion:
        tipos_list = tipos_accion.split(',')
        query = query.filter(Auditoria.tipo_accion.in_(tipos_list))
    
    if fecha_desde:
        try:
            fecha_desde_dt = datetime.strptime(fecha_desde, '%Y-%m-%d %H:%M:%S')
        except ValueError:
            fecha_desde_dt = datetime.strptime(fecha_desde, '%Y-%m-%d')
        query = query.filter(Auditoria.fecha >= fecha_desde_dt)
    
    if fecha_hasta:
        try:
            fecha_hasta_dt = datetime.strptime(fecha_hasta, '%Y-%m-%d %H:%M:%S')
        except ValueError:
            fecha_hasta_dt = datetime.strptime(fecha_hasta, '%Y-%m-%d')
            fecha_hasta_dt = fecha_hasta_dt.replace(hour=23, minute=59, second=59)
        query = query.filter(Auditoria.fecha <= fecha_hasta_dt)
    
    if item_id:
        query = query.filter(Auditoria.item_id == item_id)
    
    if es_masivo is not None:
        query = query.filter(Auditoria.es_masivo == es_masivo)
    
    query = query.order_by(Auditoria.fecha.desc())
    
    total = query.count()
    offset = (page - 1) * page_size
    results = query.offset(offset).limit(page_size).all()
    
    registros = [
        AuditoriaGeneralResponse(
            id=auditoria.id,
            item_id=auditoria.item_id,
            usuario_id=auditoria.usuario_id,
            usuario_nombre=usuario.nombre,
            tipo_accion=auditoria.tipo_accion,
            valores_anteriores=auditoria.valores_anteriores,
            valores_nuevos=auditoria.valores_nuevos,
            es_masivo=auditoria.es_masivo,
            productos_afectados=auditoria.productos_afectados,
            comentario=auditoria.comentario,
            fecha=auditoria.fecha
        )
        for auditoria, usuario in results
    ]
    
    return AuditoriaListResponse(
        total=total,
        page=page,
        page_size=page_size,
        registros=registros
    )

@router.get("/auditoria/tipos-accion")
async def listar_tipos_accion(
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user)
):
    """Lista todos los tipos de acción disponibles"""
    return {
        "tipos": [tipo.value for tipo in TipoAccion]
    }

@router.get("/auditoria/usuarios")
async def listar_usuarios_auditoria(
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user)
):
    """Lista usuarios que han realizado modificaciones"""
    usuarios = db.query(Usuario).join(
        Auditoria, Usuario.id == Auditoria.usuario_id
    ).distinct().all()
    
    return {
        "usuarios": [
            {"id": u.id, "nombre": u.nombre, "email": u.email}
            for u in usuarios
        ]
    }
