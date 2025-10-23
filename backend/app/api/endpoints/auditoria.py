from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List
from app.core.database import get_db
from app.api.deps import get_current_user
from app.models.usuario import Usuario
from app.models.auditoria_precio import AuditoriaPrecio
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
