"""
Endpoint para gestión de pedidos en preparación
Usa directamente las tablas de MercadoLibre (mlo_status = 'ready_to_ship')
"""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import func, and_, or_, case
from typing import List, Optional
from datetime import datetime
from pydantic import BaseModel

from app.core.database import get_db
from app.models.mercadolibre_order_shipping import MercadoLibreOrderShipping
from app.models.mercadolibre_order_header import MercadoLibreOrderHeader
from app.models.mercadolibre_order_detail import MercadoLibreOrderDetail
from app.models.tb_item import TBItem
from app.models.tb_brand import TBBrand
from app.models.tb_category import TBCategory
from app.models.tb_item_association import TbItemAssociation
from app.api.deps import get_current_user

router = APIRouter()


# Schemas
class PedidoDetalleResponse(BaseModel):
    """Detalle de un pedido individual"""
    mlo_id: int
    ml_pack_id: Optional[str]
    ml_order_id: Optional[str]
    mlo_status: Optional[str]

    # Datos del producto
    item_id: Optional[int]
    item_code: Optional[str]
    item_desc: Optional[str]
    cantidad: float
    mlo_title: Optional[str]

    # Datos del envío
    logistic_type: str
    tracking_number: Optional[str]
    shipping_status: Optional[str]

    # Datos del cliente
    cliente_nombre: Optional[str]
    cliente_email: Optional[str]
    cliente_telefono: Optional[str]
    direccion: Optional[str]
    ciudad: Optional[str]
    provincia: Optional[str]
    codigo_postal: Optional[str]

    # Fechas
    fecha_creacion: Optional[datetime]
    fecha_limite_despacho: Optional[datetime]

    # Marca y categoría
    marca: Optional[str]
    categoria: Optional[str]

    class Config:
        from_attributes = True


class ResumenProductoResponse(BaseModel):
    """Resumen agrupado por producto"""
    item_id: Optional[int]
    item_code: Optional[str]
    item_desc: Optional[str]
    cantidad_total: float
    logistic_type: str
    cantidad_paquetes: int
    marca: Optional[str]
    categoria: Optional[str]

    class Config:
        from_attributes = True


class FiltrosResponse(BaseModel):
    """Opciones disponibles para filtros"""
    marcas: List[dict]
    categorias: List[dict]
    tipos_envio: List[str]
    estados_ml: List[str]


# Estados de ML que indican "en preparación" (no enviados, no cancelados)
ESTADOS_PREPARACION = ['ready_to_ship', 'paid']


@router.get("/pedidos-preparacion/filtros", response_model=FiltrosResponse)
async def obtener_filtros(
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """
    Obtiene las opciones disponibles para los filtros
    Basado en órdenes de MercadoLibre con status ready_to_ship o paid (no canceladas, no enviadas)
    """
    # Marcas que tienen pedidos en preparación
    marcas_query = db.query(
        TBBrand.brand_id,
        TBBrand.brand_desc
    ).join(
        TBItem, and_(
            TBItem.brand_id == TBBrand.brand_id,
            TBItem.comp_id == TBBrand.comp_id
        )
    ).join(
        MercadoLibreOrderDetail, MercadoLibreOrderDetail.item_id == TBItem.item_id
    ).join(
        MercadoLibreOrderHeader, and_(
            MercadoLibreOrderHeader.mlo_id == MercadoLibreOrderDetail.mlo_id,
            MercadoLibreOrderHeader.comp_id == MercadoLibreOrderDetail.comp_id
        )
    ).filter(
        MercadoLibreOrderHeader.mlo_status.in_(ESTADOS_PREPARACION),
        MercadoLibreOrderHeader.mlo_isdelivered == False
    ).distinct().all()

    # Categorías que tienen pedidos en preparación
    categorias_query = db.query(
        TBCategory.cat_id,
        TBCategory.cat_desc
    ).join(
        TBItem, and_(
            TBItem.cat_id == TBCategory.cat_id,
            TBItem.comp_id == TBCategory.comp_id
        )
    ).join(
        MercadoLibreOrderDetail, MercadoLibreOrderDetail.item_id == TBItem.item_id
    ).join(
        MercadoLibreOrderHeader, and_(
            MercadoLibreOrderHeader.mlo_id == MercadoLibreOrderDetail.mlo_id,
            MercadoLibreOrderHeader.comp_id == MercadoLibreOrderDetail.comp_id
        )
    ).filter(
        MercadoLibreOrderHeader.mlo_status.in_(ESTADOS_PREPARACION),
        MercadoLibreOrderHeader.mlo_isdelivered == False
    ).distinct().all()

    # Tipos de envío disponibles
    tipos_query = db.query(
        MercadoLibreOrderShipping.ml_logistic_type
    ).join(
        MercadoLibreOrderHeader, and_(
            MercadoLibreOrderHeader.mlo_id == MercadoLibreOrderShipping.mlo_id,
            MercadoLibreOrderHeader.comp_id == MercadoLibreOrderShipping.comp_id
        )
    ).filter(
        MercadoLibreOrderHeader.mlo_status.in_(ESTADOS_PREPARACION),
        MercadoLibreOrderHeader.mlo_isdelivered == False,
        MercadoLibreOrderShipping.ml_logistic_type.isnot(None)
    ).distinct().all()

    # Estados ML disponibles
    estados_query = db.query(
        MercadoLibreOrderHeader.mlo_status
    ).filter(
        MercadoLibreOrderHeader.mlo_status.isnot(None),
        MercadoLibreOrderHeader.mlo_isdelivered == False,
        MercadoLibreOrderHeader.mlo_status != 'cancelled'
    ).distinct().all()

    return {
        "marcas": [{"id": m.brand_id, "nombre": m.brand_desc} for m in marcas_query],
        "categorias": [{"id": c.cat_id, "nombre": c.cat_desc} for c in categorias_query],
        "tipos_envio": [t[0] for t in tipos_query if t[0]],
        "estados_ml": [e[0] for e in estados_query if e[0]]
    }


@router.get("/pedidos-preparacion/detalle", response_model=List[PedidoDetalleResponse])
async def obtener_pedidos_detalle(
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
    marca_ids: Optional[str] = Query(None, description="IDs de marcas separados por coma"),
    categoria_ids: Optional[str] = Query(None, description="IDs de categorías separados por coma"),
    item_ids: Optional[str] = Query(None, description="IDs de items separados por coma"),
    logistic_type: Optional[str] = Query(None, description="Filtrar por tipo de envío"),
    search: Optional[str] = Query(None, description="Buscar por código, descripción o nombre cliente"),
    solo_combos: bool = Query(False, description="Solo mostrar items que son combos"),
    estado_ml: Optional[str] = Query(None, description="Filtrar por estado ML específico"),
    limit: int = Query(500, ge=1, le=2000),
    offset: int = Query(0, ge=0)
):
    """
    Obtiene el detalle de pedidos en preparación.
    Usa directamente mlo_status de MercadoLibre (ready_to_ship, paid).
    """

    # Construir query base desde MercadoLibreOrderHeader
    logistic_type_case = case(
        (MercadoLibreOrderShipping.mlshipping_method_id == '515282', 'Turbo'),
        else_=MercadoLibreOrderShipping.ml_logistic_type
    )

    query = db.query(
        MercadoLibreOrderHeader.mlo_id,
        MercadoLibreOrderHeader.ml_pack_id,
        MercadoLibreOrderHeader.mlorder_id.label('ml_order_id'),
        MercadoLibreOrderHeader.mlo_status,
        MercadoLibreOrderDetail.item_id,
        TBItem.item_code,
        TBItem.item_desc,
        MercadoLibreOrderDetail.mlo_quantity.label('cantidad'),
        MercadoLibreOrderDetail.mlo_title,
        logistic_type_case.label('logistic_type'),
        MercadoLibreOrderShipping.mltracking_number.label('tracking_number'),
        MercadoLibreOrderShipping.mlstatus.label('shipping_status'),
        MercadoLibreOrderShipping.mlreceiver_name.label('cliente_nombre'),
        MercadoLibreOrderHeader.mlo_email.label('cliente_email'),
        MercadoLibreOrderShipping.mlreceiver_phone.label('cliente_telefono'),
        MercadoLibreOrderShipping.mlstreet_name.label('direccion'),
        MercadoLibreOrderShipping.mlcity_name.label('ciudad'),
        MercadoLibreOrderShipping.mlstate_name.label('provincia'),
        MercadoLibreOrderShipping.mlzip_code.label('codigo_postal'),
        MercadoLibreOrderHeader.ml_date_created.label('fecha_creacion'),
        MercadoLibreOrderShipping.mlestimated_handling_limit.label('fecha_limite_despacho'),
        TBBrand.brand_desc.label('marca'),
        TBCategory.cat_desc.label('categoria')
    ).select_from(
        MercadoLibreOrderHeader
    ).outerjoin(
        MercadoLibreOrderShipping, and_(
            MercadoLibreOrderShipping.mlo_id == MercadoLibreOrderHeader.mlo_id,
            MercadoLibreOrderShipping.comp_id == MercadoLibreOrderHeader.comp_id
        )
    ).outerjoin(
        MercadoLibreOrderDetail, and_(
            MercadoLibreOrderDetail.mlo_id == MercadoLibreOrderHeader.mlo_id,
            MercadoLibreOrderDetail.comp_id == MercadoLibreOrderHeader.comp_id
        )
    ).outerjoin(
        TBItem, and_(
            TBItem.item_id == MercadoLibreOrderDetail.item_id,
            TBItem.comp_id == MercadoLibreOrderDetail.comp_id
        )
    ).outerjoin(
        TBBrand, and_(
            TBBrand.brand_id == TBItem.brand_id,
            TBBrand.comp_id == TBItem.comp_id
        )
    ).outerjoin(
        TBCategory, and_(
            TBCategory.cat_id == TBItem.cat_id,
            TBCategory.comp_id == TBItem.comp_id
        )
    )

    # Filtro principal: órdenes ready_to_ship o paid, no entregadas
    if estado_ml:
        query = query.filter(MercadoLibreOrderHeader.mlo_status == estado_ml)
    else:
        query = query.filter(MercadoLibreOrderHeader.mlo_status.in_(ESTADOS_PREPARACION))

    query = query.filter(MercadoLibreOrderHeader.mlo_isdelivered == False)

    # Aplicar filtros múltiples
    if marca_ids:
        ids = [int(x.strip()) for x in marca_ids.split(',') if x.strip().isdigit()]
        if ids:
            query = query.filter(TBItem.brand_id.in_(ids))

    if categoria_ids:
        ids = [int(x.strip()) for x in categoria_ids.split(',') if x.strip().isdigit()]
        if ids:
            query = query.filter(TBItem.cat_id.in_(ids))

    if item_ids:
        ids = [int(x.strip()) for x in item_ids.split(',') if x.strip().isdigit()]
        if ids:
            query = query.filter(MercadoLibreOrderDetail.item_id.in_(ids))

    if logistic_type:
        if logistic_type.lower() == 'turbo':
            query = query.filter(MercadoLibreOrderShipping.mlshipping_method_id == '515282')
        else:
            query = query.filter(MercadoLibreOrderShipping.ml_logistic_type == logistic_type)

    if search:
        search_filter = f"%{search}%"
        query = query.filter(
            or_(
                TBItem.item_code.ilike(search_filter),
                TBItem.item_desc.ilike(search_filter),
                MercadoLibreOrderShipping.mlreceiver_name.ilike(search_filter),
                MercadoLibreOrderDetail.mlo_title.ilike(search_filter)
            )
        )

    # Filtro de combos: items que tienen asociaciones
    if solo_combos:
        combo_items_subq = db.query(TbItemAssociation.item_id).distinct().subquery()
        query = query.filter(MercadoLibreOrderDetail.item_id.in_(combo_items_subq))

    # Ordenar por fecha límite de despacho (más urgentes primero)
    query = query.order_by(MercadoLibreOrderShipping.mlestimated_handling_limit.asc())

    # Aplicar límite y offset
    results = query.offset(offset).limit(limit).all()

    return [
        PedidoDetalleResponse(
            mlo_id=r.mlo_id,
            ml_pack_id=r.ml_pack_id,
            ml_order_id=r.ml_order_id,
            mlo_status=r.mlo_status,
            item_id=r.item_id,
            item_code=r.item_code,
            item_desc=r.item_desc,
            cantidad=float(r.cantidad) if r.cantidad else 0,
            mlo_title=r.mlo_title,
            logistic_type=r.logistic_type or 'N/A',
            tracking_number=r.tracking_number,
            shipping_status=r.shipping_status,
            cliente_nombre=r.cliente_nombre,
            cliente_email=r.cliente_email,
            cliente_telefono=r.cliente_telefono,
            direccion=r.direccion,
            ciudad=r.ciudad,
            provincia=r.provincia,
            codigo_postal=r.codigo_postal,
            fecha_creacion=r.fecha_creacion,
            fecha_limite_despacho=r.fecha_limite_despacho,
            marca=r.marca,
            categoria=r.categoria
        )
        for r in results
    ]


@router.get("/pedidos-preparacion/resumen", response_model=List[ResumenProductoResponse])
async def obtener_resumen_productos(
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
    marca_ids: Optional[str] = Query(None, description="IDs de marcas separados por coma"),
    categoria_ids: Optional[str] = Query(None, description="IDs de categorías separados por coma"),
    item_ids: Optional[str] = Query(None, description="IDs de items separados por coma"),
    logistic_type: Optional[str] = Query(None, description="Filtrar por tipo de envío"),
    search: Optional[str] = Query(None, description="Buscar por código o descripción"),
    solo_combos: bool = Query(False, description="Solo mostrar items que son combos"),
    estado_ml: Optional[str] = Query(None, description="Filtrar por estado ML específico")
):
    """
    Obtiene resumen agrupado por producto de pedidos en preparación.
    """

    logistic_type_case = case(
        (MercadoLibreOrderShipping.mlshipping_method_id == '515282', 'Turbo'),
        else_=MercadoLibreOrderShipping.ml_logistic_type
    )

    query = db.query(
        MercadoLibreOrderDetail.item_id,
        TBItem.item_code,
        TBItem.item_desc,
        func.sum(MercadoLibreOrderDetail.mlo_quantity).label('cantidad_total'),
        logistic_type_case.label('logistic_type'),
        func.count(func.distinct(MercadoLibreOrderHeader.mlo_id)).label('cantidad_paquetes'),
        TBBrand.brand_desc.label('marca'),
        TBCategory.cat_desc.label('categoria')
    ).select_from(
        MercadoLibreOrderHeader
    ).outerjoin(
        MercadoLibreOrderShipping, and_(
            MercadoLibreOrderShipping.mlo_id == MercadoLibreOrderHeader.mlo_id,
            MercadoLibreOrderShipping.comp_id == MercadoLibreOrderHeader.comp_id
        )
    ).outerjoin(
        MercadoLibreOrderDetail, and_(
            MercadoLibreOrderDetail.mlo_id == MercadoLibreOrderHeader.mlo_id,
            MercadoLibreOrderDetail.comp_id == MercadoLibreOrderHeader.comp_id
        )
    ).outerjoin(
        TBItem, and_(
            TBItem.item_id == MercadoLibreOrderDetail.item_id,
            TBItem.comp_id == MercadoLibreOrderDetail.comp_id
        )
    ).outerjoin(
        TBBrand, and_(
            TBBrand.brand_id == TBItem.brand_id,
            TBBrand.comp_id == TBItem.comp_id
        )
    ).outerjoin(
        TBCategory, and_(
            TBCategory.cat_id == TBItem.cat_id,
            TBCategory.comp_id == TBItem.comp_id
        )
    )

    # Filtro principal
    if estado_ml:
        query = query.filter(MercadoLibreOrderHeader.mlo_status == estado_ml)
    else:
        query = query.filter(MercadoLibreOrderHeader.mlo_status.in_(ESTADOS_PREPARACION))

    query = query.filter(MercadoLibreOrderHeader.mlo_isdelivered == False)

    # Aplicar filtros múltiples
    if marca_ids:
        ids = [int(x.strip()) for x in marca_ids.split(',') if x.strip().isdigit()]
        if ids:
            query = query.filter(TBItem.brand_id.in_(ids))

    if categoria_ids:
        ids = [int(x.strip()) for x in categoria_ids.split(',') if x.strip().isdigit()]
        if ids:
            query = query.filter(TBItem.cat_id.in_(ids))

    if item_ids:
        ids = [int(x.strip()) for x in item_ids.split(',') if x.strip().isdigit()]
        if ids:
            query = query.filter(MercadoLibreOrderDetail.item_id.in_(ids))

    if logistic_type:
        if logistic_type.lower() == 'turbo':
            query = query.filter(MercadoLibreOrderShipping.mlshipping_method_id == '515282')
        else:
            query = query.filter(MercadoLibreOrderShipping.ml_logistic_type == logistic_type)

    if search:
        search_filter = f"%{search}%"
        query = query.filter(
            or_(
                TBItem.item_code.ilike(search_filter),
                TBItem.item_desc.ilike(search_filter)
            )
        )

    # Filtro de combos
    if solo_combos:
        combo_items_subq = db.query(TbItemAssociation.item_id).distinct().subquery()
        query = query.filter(MercadoLibreOrderDetail.item_id.in_(combo_items_subq))

    # Agrupar
    query = query.group_by(
        MercadoLibreOrderDetail.item_id,
        TBItem.item_code,
        TBItem.item_desc,
        logistic_type_case,
        TBBrand.brand_desc,
        TBCategory.cat_desc
    ).order_by(
        func.sum(MercadoLibreOrderDetail.mlo_quantity).desc()
    )

    results = query.all()

    return [
        ResumenProductoResponse(
            item_id=r.item_id,
            item_code=r.item_code,
            item_desc=r.item_desc,
            cantidad_total=float(r.cantidad_total) if r.cantidad_total else 0,
            logistic_type=r.logistic_type or 'N/A',
            cantidad_paquetes=r.cantidad_paquetes or 0,
            marca=r.marca,
            categoria=r.categoria
        )
        for r in results
    ]


@router.get("/pedidos-preparacion/estadisticas")
async def obtener_estadisticas(
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """
    Obtiene estadísticas generales de pedidos en preparación
    Basado en órdenes de MercadoLibre (mlo_status ready_to_ship/paid, no entregadas)
    """

    # Total de pedidos
    total_pedidos = db.query(
        func.count(func.distinct(MercadoLibreOrderHeader.mlo_id))
    ).filter(
        MercadoLibreOrderHeader.mlo_status.in_(ESTADOS_PREPARACION),
        MercadoLibreOrderHeader.mlo_isdelivered == False
    ).scalar() or 0

    # Total de unidades
    total_unidades = db.query(
        func.sum(MercadoLibreOrderDetail.mlo_quantity)
    ).select_from(
        MercadoLibreOrderHeader
    ).outerjoin(
        MercadoLibreOrderDetail, and_(
            MercadoLibreOrderDetail.mlo_id == MercadoLibreOrderHeader.mlo_id,
            MercadoLibreOrderDetail.comp_id == MercadoLibreOrderHeader.comp_id
        )
    ).filter(
        MercadoLibreOrderHeader.mlo_status.in_(ESTADOS_PREPARACION),
        MercadoLibreOrderHeader.mlo_isdelivered == False
    ).scalar() or 0

    # Por estado ML
    por_estado = db.query(
        MercadoLibreOrderHeader.mlo_status.label('estado'),
        func.count(func.distinct(MercadoLibreOrderHeader.mlo_id)).label('pedidos'),
        func.sum(MercadoLibreOrderDetail.mlo_quantity).label('unidades')
    ).outerjoin(
        MercadoLibreOrderDetail, and_(
            MercadoLibreOrderDetail.mlo_id == MercadoLibreOrderHeader.mlo_id,
            MercadoLibreOrderDetail.comp_id == MercadoLibreOrderHeader.comp_id
        )
    ).filter(
        MercadoLibreOrderHeader.mlo_status.in_(ESTADOS_PREPARACION),
        MercadoLibreOrderHeader.mlo_isdelivered == False
    ).group_by(
        MercadoLibreOrderHeader.mlo_status
    ).all()

    # Por tipo de envío
    logistic_type_case = case(
        (MercadoLibreOrderShipping.mlshipping_method_id == '515282', 'Turbo'),
        else_=MercadoLibreOrderShipping.ml_logistic_type
    )

    por_tipo = db.query(
        logistic_type_case.label('tipo'),
        func.count(func.distinct(MercadoLibreOrderHeader.mlo_id)).label('pedidos'),
        func.sum(MercadoLibreOrderDetail.mlo_quantity).label('unidades')
    ).select_from(
        MercadoLibreOrderHeader
    ).outerjoin(
        MercadoLibreOrderShipping, and_(
            MercadoLibreOrderShipping.mlo_id == MercadoLibreOrderHeader.mlo_id,
            MercadoLibreOrderShipping.comp_id == MercadoLibreOrderHeader.comp_id
        )
    ).outerjoin(
        MercadoLibreOrderDetail, and_(
            MercadoLibreOrderDetail.mlo_id == MercadoLibreOrderHeader.mlo_id,
            MercadoLibreOrderDetail.comp_id == MercadoLibreOrderHeader.comp_id
        )
    ).filter(
        MercadoLibreOrderHeader.mlo_status.in_(ESTADOS_PREPARACION),
        MercadoLibreOrderHeader.mlo_isdelivered == False
    ).group_by(
        logistic_type_case
    ).all()

    return {
        "total_pedidos": total_pedidos,
        "total_unidades": float(total_unidades) if total_unidades else 0,
        "por_estado_ml": [
            {
                "estado": e.estado or 'N/A',
                "pedidos": e.pedidos,
                "unidades": float(e.unidades) if e.unidades else 0
            }
            for e in por_estado
        ],
        "por_tipo_envio": [
            {
                "tipo": t.tipo or 'N/A',
                "pedidos": t.pedidos,
                "unidades": float(t.unidades) if t.unidades else 0
            }
            for t in por_tipo
        ]
    }
