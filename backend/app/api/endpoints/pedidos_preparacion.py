"""
Endpoint para gestión de pedidos en preparación.
Lee datos de la tabla cache pedido_preparacion_cache que se actualiza cada 5 min
desde la query 67 del ERP via gbp-parser.
"""
from fastapi import APIRouter, Depends, Query, BackgroundTasks
from sqlalchemy.orm import Session
from sqlalchemy import func
from typing import List, Optional
from datetime import datetime
from pydantic import BaseModel

from app.core.database import get_db
from app.models.pedido_preparacion_cache import PedidoPreparacionCache
from app.api.deps import get_current_user

router = APIRouter()


# Schemas
class ResumenProductoResponse(BaseModel):
    """Resumen de producto en preparación"""
    id: int
    item_id: Optional[int]
    item_code: Optional[str]
    item_desc: Optional[str]
    cantidad: float
    ml_logistic_type: Optional[str]
    prepara_paquete: int
    updated_at: Optional[datetime]

    class Config:
        from_attributes = True


class EstadisticasResponse(BaseModel):
    """Estadísticas de pedidos en preparación"""
    total_items: int
    total_unidades: float
    total_paquetes: int
    por_tipo_envio: List[dict]
    ultima_actualizacion: Optional[datetime]


class SyncResponse(BaseModel):
    """Respuesta de sincronización"""
    status: str
    message: str
    count: int
    timestamp: str


@router.get("/pedidos-preparacion/resumen", response_model=List[ResumenProductoResponse])
async def obtener_resumen(
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
    logistic_type: Optional[str] = Query(None, description="Filtrar por tipo de envío"),
    search: Optional[str] = Query(None, description="Buscar por código o descripción"),
    limit: int = Query(500, ge=1, le=2000),
    offset: int = Query(0, ge=0)
):
    """
    Obtiene el resumen de pedidos en preparación desde la tabla cache.
    """
    query = db.query(PedidoPreparacionCache)

    # Filtro por tipo de envío
    if logistic_type:
        query = query.filter(PedidoPreparacionCache.ml_logistic_type == logistic_type)

    # Búsqueda
    if search:
        search_filter = f"%{search}%"
        query = query.filter(
            (PedidoPreparacionCache.item_code.ilike(search_filter)) |
            (PedidoPreparacionCache.item_desc.ilike(search_filter))
        )

    # Ordenar por cantidad descendente
    query = query.order_by(PedidoPreparacionCache.cantidad.desc())

    results = query.offset(offset).limit(limit).all()

    return [
        ResumenProductoResponse(
            id=r.id,
            item_id=r.item_id,
            item_code=r.item_code,
            item_desc=r.item_desc,
            cantidad=float(r.cantidad) if r.cantidad else 0,
            ml_logistic_type=r.ml_logistic_type,
            prepara_paquete=r.prepara_paquete or 0,
            updated_at=r.updated_at
        )
        for r in results
    ]


@router.get("/pedidos-preparacion/estadisticas", response_model=EstadisticasResponse)
async def obtener_estadisticas(
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """
    Obtiene estadísticas de pedidos en preparación.
    """
    # Total de items distintos
    total_items = db.query(func.count(PedidoPreparacionCache.id)).scalar() or 0

    # Total de unidades
    total_unidades = db.query(func.sum(PedidoPreparacionCache.cantidad)).scalar() or 0

    # Total de paquetes
    total_paquetes = db.query(func.sum(PedidoPreparacionCache.prepara_paquete)).scalar() or 0

    # Por tipo de envío
    por_tipo = db.query(
        PedidoPreparacionCache.ml_logistic_type.label('tipo'),
        func.count(PedidoPreparacionCache.id).label('items'),
        func.sum(PedidoPreparacionCache.cantidad).label('unidades'),
        func.sum(PedidoPreparacionCache.prepara_paquete).label('paquetes')
    ).group_by(
        PedidoPreparacionCache.ml_logistic_type
    ).all()

    # Última actualización
    ultima_actualizacion = db.query(func.max(PedidoPreparacionCache.updated_at)).scalar()

    return EstadisticasResponse(
        total_items=total_items,
        total_unidades=float(total_unidades) if total_unidades else 0,
        total_paquetes=int(total_paquetes) if total_paquetes else 0,
        por_tipo_envio=[
            {
                "tipo": t.tipo or 'N/A',
                "items": t.items,
                "unidades": float(t.unidades) if t.unidades else 0,
                "paquetes": int(t.paquetes) if t.paquetes else 0
            }
            for t in por_tipo
        ],
        ultima_actualizacion=ultima_actualizacion
    )


@router.get("/pedidos-preparacion/tipos-envio")
async def obtener_tipos_envio(
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """
    Obtiene los tipos de envío disponibles.
    """
    tipos = db.query(
        PedidoPreparacionCache.ml_logistic_type
    ).distinct().all()

    return [t.ml_logistic_type for t in tipos if t.ml_logistic_type]


@router.post("/pedidos-preparacion/sync", response_model=SyncResponse)
async def sincronizar_pedidos(
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """
    Fuerza una sincronización manual de pedidos en preparación.
    """
    from app.scripts.sync_pedidos_preparacion import sync_pedidos_preparacion
    import asyncio

    try:
        # Ejecutar sincronización
        result = await sync_pedidos_preparacion(db)

        return SyncResponse(
            status=result.get("status", "unknown"),
            message=result.get("message", "Sincronización completada"),
            count=result.get("count", 0),
            timestamp=result.get("timestamp", datetime.now().isoformat())
        )
    except Exception as e:
        return SyncResponse(
            status="error",
            message=str(e),
            count=0,
            timestamp=datetime.now().isoformat()
        )
