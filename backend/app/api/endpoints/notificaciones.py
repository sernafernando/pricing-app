from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import desc, func
from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime
from app.api.deps import get_current_user
from app.core.database import get_db
from app.models.usuario import Usuario
from app.models.notificacion import Notificacion

router = APIRouter()

class NotificacionResponse(BaseModel):
    id: int
    tipo: str
    item_id: Optional[int]
    id_operacion: Optional[int]
    ml_id: Optional[str]
    pack_id: Optional[int]
    codigo_producto: Optional[str]
    descripcion_producto: Optional[str]
    mensaje: str
    markup_real: Optional[float]
    markup_objetivo: Optional[float]
    monto_venta: Optional[float]
    fecha_venta: Optional[datetime]
    leida: bool
    fecha_creacion: datetime
    fecha_lectura: Optional[datetime]

    class Config:
        from_attributes = True

class NotificacionStats(BaseModel):
    total: int
    no_leidas: int
    por_tipo: dict

@router.get("/notificaciones", response_model=List[NotificacionResponse])
async def listar_notificaciones(
    limit: int = 50,
    offset: int = 0,
    solo_no_leidas: bool = False,
    tipo: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user)
):
    """
    Lista las notificaciones del usuario actual ordenadas por fecha de creación (más recientes primero)
    """
    query = db.query(Notificacion).filter(Notificacion.user_id == current_user.id)

    if solo_no_leidas:
        query = query.filter(Notificacion.leida == False)

    if tipo:
        query = query.filter(Notificacion.tipo == tipo)

    notificaciones = query.order_by(desc(Notificacion.fecha_creacion)).offset(offset).limit(limit).all()

    return notificaciones

@router.get("/notificaciones/stats", response_model=NotificacionStats)
async def obtener_estadisticas_notificaciones(
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user)
):
    """
    Obtiene estadísticas de las notificaciones del usuario actual
    """
    total = db.query(Notificacion).filter(Notificacion.user_id == current_user.id).count()
    no_leidas = db.query(Notificacion).filter(
        Notificacion.user_id == current_user.id,
        Notificacion.leida == False
    ).count()

    # Contar por tipo
    tipos_query = db.query(
        Notificacion.tipo,
        func.count(Notificacion.id).label('count')
    ).filter(
        Notificacion.user_id == current_user.id,
        Notificacion.leida == False
    ).group_by(Notificacion.tipo).all()

    por_tipo = {tipo: count for tipo, count in tipos_query}

    return {
        "total": total,
        "no_leidas": no_leidas,
        "por_tipo": por_tipo
    }

@router.patch("/notificaciones/{notificacion_id}/marcar-leida")
async def marcar_notificacion_leida(
    notificacion_id: int,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user)
):
    """
    Marca una notificación como leída (solo la del usuario actual)
    """
    notificacion = db.query(Notificacion).filter(
        Notificacion.id == notificacion_id,
        Notificacion.user_id == current_user.id
    ).first()

    if not notificacion:
        raise HTTPException(404, "Notificación no encontrada")

    if not notificacion.leida:
        notificacion.leida = True
        notificacion.fecha_lectura = datetime.now()
        db.commit()

    return {"mensaje": "Notificación marcada como leída"}

@router.post("/notificaciones/marcar-todas-leidas")
async def marcar_todas_leidas(
    tipo: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user)
):
    """
    Marca todas las notificaciones del usuario actual como leídas (opcionalmente filtradas por tipo)
    """
    query = db.query(Notificacion).filter(
        Notificacion.user_id == current_user.id,
        Notificacion.leida == False
    )

    if tipo:
        query = query.filter(Notificacion.tipo == tipo)

    count = query.update({
        "leida": True,
        "fecha_lectura": datetime.now()
    })

    db.commit()

    return {"mensaje": f"{count} notificaciones marcadas como leídas"}

@router.delete("/notificaciones/{notificacion_id}")
async def eliminar_notificacion(
    notificacion_id: int,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user)
):
    """
    Elimina una notificación del usuario actual
    """
    notificacion = db.query(Notificacion).filter(
        Notificacion.id == notificacion_id,
        Notificacion.user_id == current_user.id
    ).first()

    if not notificacion:
        raise HTTPException(404, "Notificación no encontrada")

    db.delete(notificacion)
    db.commit()

    return {"mensaje": "Notificación eliminada"}

@router.delete("/notificaciones/limpiar")
async def limpiar_notificaciones_leidas(
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user)
):
    """
    Elimina todas las notificaciones leídas del usuario actual
    """
    count = db.query(Notificacion).filter(
        Notificacion.user_id == current_user.id,
        Notificacion.leida == True
    ).delete()
    db.commit()

    return {"mensaje": f"{count} notificaciones leídas eliminadas"}
