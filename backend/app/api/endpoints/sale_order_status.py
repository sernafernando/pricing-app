"""
Endpoints para estados de pedidos (tb_sale_order_status)
"""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import or_
from typing import List
from pydantic import BaseModel

from app.core.database import get_db
from app.api.deps import get_current_user
from app.models.sale_order_status import SaleOrderStatus

router = APIRouter()


class SaleOrderStatusResponse(BaseModel):
    """Schema para respuesta de estado de pedido"""

    ssos_id: int
    ssos_name: str
    ssos_description: str | None
    ssos_is_active: bool | None
    ssos_category: str | None
    ssos_color: str | None
    ssos_order: int | None

    class Config:
        from_attributes = True


@router.get("/sale-order-status", response_model=List[SaleOrderStatusResponse])
async def obtener_estados_pedido(
    db: Session = Depends(get_db), only_active: bool = True, current_user=Depends(get_current_user)
):
    """
    Obtiene todos los estados de pedidos (ssos_id).

    Parámetros:
    - only_active: Solo estados activos (default: true)

    Retorna lista de estados con:
    - ssos_id: ID del estado
    - ssos_name: Nombre del estado
    - ssos_category: Categoría (pendiente, en_proceso, completado, etc)
    - ssos_color: Color para UI
    - ssos_order: Orden de visualización
    """
    query = db.query(SaleOrderStatus)

    if only_active:
        # Considerar NULL como activo (default en la migración)
        query = query.filter(or_(SaleOrderStatus.ssos_is_active == True, SaleOrderStatus.ssos_is_active.is_(None)))

    query = query.order_by(SaleOrderStatus.ssos_order)

    return query.all()


@router.get("/sale-order-status/by-category/{category}", response_model=List[SaleOrderStatusResponse])
async def obtener_estados_por_categoria(
    category: str, db: Session = Depends(get_db), current_user=Depends(get_current_user)
):
    """
    Obtiene estados de pedidos filtrados por categoría.

    Categorías disponibles:
    - pendiente: Estados pendientes (ej: 20 ForPreparation)
    - en_proceso: Estados en proceso (ej: 10 En Area Comercial)
    - completado: Estados completados (ej: 50 Ok Para Emisión)
    - cancelado: Estados cancelados
    - rma: Estados de RMA
    """
    estados = (
        db.query(SaleOrderStatus)
        .filter(SaleOrderStatus.ssos_category == category, SaleOrderStatus.ssos_is_active == True)
        .order_by(SaleOrderStatus.ssos_order)
        .all()
    )

    return estados
