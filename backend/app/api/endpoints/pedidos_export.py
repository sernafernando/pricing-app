"""
Endpoint para visualización de pedidos de exportación.
Integración del visualizador-pedidos en la pricing-app.
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import func, and_, or_, desc
from typing import List, Optional
from datetime import datetime, date
from pydantic import BaseModel

from app.core.database import get_db
from app.models.sale_order_header import SaleOrderHeader
from app.models.sale_order_detail import SaleOrderDetail
from app.api.deps import get_current_user

router = APIRouter()


# Schemas
class PedidoExportItem(BaseModel):
    """Item/producto dentro de un pedido"""
    item_id: Optional[int]
    item_code: Optional[str]
    item_desc: Optional[str]
    cantidad: float
    precio_unitario: Optional[float]
    
    class Config:
        from_attributes = True


class PedidoExportResponse(BaseModel):
    """Pedido de exportación para el visualizador"""
    # Identificadores
    soh_id: int
    comp_id: int
    bra_id: int
    
    # Fechas
    fecha_pedido: Optional[datetime]
    fecha_entrega: Optional[datetime]
    
    # Cliente y dirección
    cust_id: Optional[int]
    nombre_cliente: Optional[str]
    direccion_entrega: Optional[str]
    
    # Observaciones y notas
    observacion: Optional[str]
    nota_interna: Optional[str]
    
    # ML y Tienda Nube
    ml_order_id: Optional[str]
    ml_shipping_id: Optional[int]
    tiendanube_order_id: Optional[str]
    
    # Envío
    codigo_envio_interno: Optional[str]
    tipo_envio: Optional[str]
    bultos: Optional[int]
    
    # Estado
    estado: Optional[int]
    total: Optional[float]
    
    # Items del pedido
    items: List[PedidoExportItem] = []
    
    class Config:
        from_attributes = True


class EstadisticasExportResponse(BaseModel):
    """Estadísticas de pedidos de exportación"""
    total_pedidos: int
    total_bultos: int
    pendientes_etiqueta: int
    con_ml: int
    con_tiendanube: int
    ultima_actualizacion: Optional[datetime]


@router.get("/pedidos-export/por-export/{export_id}", response_model=List[PedidoExportResponse])
async def obtener_pedidos_por_export(
    export_id: int,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0)
):
    """
    Obtiene pedidos filtrados por export_id del ERP.
    Export ID 80 típicamente corresponde a pedidos pendientes de preparación.
    """
    # Query principal
    query = db.query(SaleOrderHeader).filter(
        SaleOrderHeader.export_id == export_id
    )
    
    # Ordenar por fecha descendente
    query = query.order_by(desc(SaleOrderHeader.soh_cd))
    
    pedidos = query.offset(offset).limit(limit).all()
    
    # Transformar a response (sin items por ahora, los agregamos después)
    result = []
    for pedido in pedidos:
        result.append(PedidoExportResponse(
            soh_id=pedido.soh_id,
            comp_id=pedido.comp_id,
            bra_id=pedido.bra_id,
            fecha_pedido=pedido.soh_cd,
            fecha_entrega=pedido.soh_deliverydate,
            cust_id=pedido.cust_id,
            nombre_cliente=None,  # TODO: Join con tabla clientes
            direccion_entrega=pedido.soh_deliveryaddress,
            observacion=pedido.soh_observation1,
            nota_interna=pedido.soh_internalannotation,
            ml_order_id=pedido.soh_mlid,
            ml_shipping_id=pedido.mlshippingid,
            tiendanube_order_id=pedido.ws_internalid,
            codigo_envio_interno=pedido.codigo_envio_interno,
            tipo_envio=None,  # TODO: Derivar de campos ML/TN
            bultos=pedido.soh_packagesqty,
            estado=pedido.soh_statusof,
            total=float(pedido.soh_total) if pedido.soh_total else None,
            items=[]  # TODO: Cargar items en endpoint separado
        ))
    
    return result


@router.get("/pedidos-export/estadisticas/{export_id}", response_model=EstadisticasExportResponse)
async def obtener_estadisticas_export(
    export_id: int,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """Obtiene estadísticas de pedidos de un export específico"""
    
    # Total de pedidos
    total_pedidos = db.query(func.count(SaleOrderHeader.soh_id)).filter(
        SaleOrderHeader.export_id == export_id
    ).scalar() or 0
    
    # Total de bultos
    total_bultos = db.query(func.sum(SaleOrderHeader.soh_packagesqty)).filter(
        SaleOrderHeader.export_id == export_id
    ).scalar() or 0
    
    # Pendientes de etiqueta (sin codigo_envio_interno)
    pendientes_etiqueta = db.query(func.count(SaleOrderHeader.soh_id)).filter(
        and_(
            SaleOrderHeader.export_id == export_id,
            SaleOrderHeader.codigo_envio_interno.is_(None)
        )
    ).scalar() or 0
    
    # Con ML
    con_ml = db.query(func.count(SaleOrderHeader.soh_id)).filter(
        and_(
            SaleOrderHeader.export_id == export_id,
            SaleOrderHeader.mlo_id.isnot(None)
        )
    ).scalar() or 0
    
    # Con TiendaNube
    con_tiendanube = db.query(func.count(SaleOrderHeader.soh_id)).filter(
        and_(
            SaleOrderHeader.export_id == export_id,
            SaleOrderHeader.ws_internalid.isnot(None)
        )
    ).scalar() or 0
    
    # Última actualización
    ultima_actualizacion = db.query(func.max(SaleOrderHeader.soh_lastupdate)).filter(
        SaleOrderHeader.export_id == export_id
    ).scalar()
    
    return EstadisticasExportResponse(
        total_pedidos=total_pedidos,
        total_bultos=int(total_bultos),
        pendientes_etiqueta=pendientes_etiqueta,
        con_ml=con_ml,
        con_tiendanube=con_tiendanube,
        ultima_actualizacion=ultima_actualizacion
    )


@router.post("/pedidos-export/asignar-codigo-envio/{soh_id}")
async def asignar_codigo_envio(
    soh_id: int,
    codigo: str,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """Asigna un código de envío interno a un pedido (para QR en etiqueta)"""
    
    pedido = db.query(SaleOrderHeader).filter(
        SaleOrderHeader.soh_id == soh_id
    ).first()
    
    if not pedido:
        raise HTTPException(404, "Pedido no encontrado")
    
    # Verificar que el código no esté en uso
    existe = db.query(SaleOrderHeader).filter(
        and_(
            SaleOrderHeader.codigo_envio_interno == codigo,
            SaleOrderHeader.soh_id != soh_id
        )
    ).first()
    
    if existe:
        raise HTTPException(400, f"El código {codigo} ya está asignado al pedido {existe.soh_id}")
    
    pedido.codigo_envio_interno = codigo
    db.commit()
    
    return {"mensaje": "Código asignado correctamente", "soh_id": soh_id, "codigo": codigo}


@router.get("/pedidos-export/todos", response_model=List[PedidoExportResponse])
async def obtener_todos_pedidos_export(
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
    export_id: Optional[int] = Query(None, description="Filtrar por export_id"),
    fecha_desde: Optional[date] = Query(None, description="Fecha desde (YYYY-MM-DD)"),
    fecha_hasta: Optional[date] = Query(None, description="Fecha hasta (YYYY-MM-DD)"),
    solo_sin_codigo: bool = Query(False, description="Solo pedidos sin código de envío"),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0)
):
    """
    Obtiene todos los pedidos de exportación con filtros opcionales.
    """
    query = db.query(SaleOrderHeader)
    
    # Filtros
    if export_id:
        query = query.filter(SaleOrderHeader.export_id == export_id)
    
    if fecha_desde:
        query = query.filter(SaleOrderHeader.soh_cd >= fecha_desde)
    
    if fecha_hasta:
        query = query.filter(SaleOrderHeader.soh_cd <= fecha_hasta)
    
    if solo_sin_codigo:
        query = query.filter(SaleOrderHeader.codigo_envio_interno.is_(None))
    
    # Ordenar y paginar
    query = query.order_by(desc(SaleOrderHeader.soh_cd))
    pedidos = query.offset(offset).limit(limit).all()
    
    # Transformar
    result = []
    for pedido in pedidos:
        result.append(PedidoExportResponse(
            soh_id=pedido.soh_id,
            comp_id=pedido.comp_id,
            bra_id=pedido.bra_id,
            fecha_pedido=pedido.soh_cd,
            fecha_entrega=pedido.soh_deliverydate,
            cust_id=pedido.cust_id,
            nombre_cliente=None,
            direccion_entrega=pedido.soh_deliveryaddress,
            observacion=pedido.soh_observation1,
            nota_interna=pedido.soh_internalannotation,
            ml_order_id=pedido.soh_mlid,
            ml_shipping_id=pedido.mlshippingid,
            tiendanube_order_id=pedido.ws_internalid,
            codigo_envio_interno=pedido.codigo_envio_interno,
            tipo_envio=None,
            bultos=pedido.soh_packagesqty,
            estado=pedido.soh_statusof,
            total=float(pedido.soh_total) if pedido.soh_total else None,
            items=[]
        ))
    
    return result
