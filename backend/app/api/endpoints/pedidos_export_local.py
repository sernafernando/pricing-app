"""
Endpoint para obtener pedidos DIRECTAMENTE desde la DB local.
Replica la lógica del Export 87 del ERP (WHERE ssos_id = 20)
SIN necesidad de llamar al gbp-parser.
"""
from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import and_, or_, func, text
from typing import List, Optional
from datetime import datetime

from app.core.database import get_db
from app.models.sale_order_header import SaleOrderHeader
from app.models.sale_order_detail import SaleOrderDetail
from app.models.tb_customer import TBCustomer
from app.models.tb_item import TBItem
from app.models.tb_user import TBUser
from app.models.tienda_nube_order import TiendaNubeOrder
from app.api.endpoints.pedidos_export_simple import PedidoDetallado, ItemPedidoDetalle

import logging

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/pedidos-local", response_model=List[PedidoDetallado])
async def obtener_pedidos_local(
    db: Session = Depends(get_db),
    ssos_id: Optional[int] = Query(None, description="Filtrar por estado ERP (20=Pendiente, 30=En Proceso, 40=Completado, etc)"),
    solo_tn: bool = Query(False),
    solo_ml: bool = Query(False),
    solo_sin_direccion: bool = Query(False),
    user_id: Optional[int] = Query(None),
    provincia: Optional[str] = Query(None),
    buscar: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0)
):
    """
    Obtiene pedidos DIRECTAMENTE desde la DB local.
    
    Replica la query del Export 87 del ERP:
    ```sql
    SELECT ... FROM tbSaleOrderHeader tsoh
    LEFT JOIN tbSaleOrderDetail tsod ON ...
    LEFT JOIN tbItem ti ON ...
    LEFT JOIN tbCustomer tc ON ...
    LEFT JOIN tbTiendaNube_Orders ttno ON ...
    WHERE tsoh.ssos_id = ? (opcional)
    ```
    
    Ventajas:
    - NO depende del gbp-parser (puerto 8002)
    - Más rápido (query directa a DB)
    - Datos siempre actualizados (no necesita sincronización)
    
    Parámetros:
    - ssos_id: (Opcional) Filtrar por estado en ERP
      - 20 = Pendiente de preparación
      - 30 = En proceso
      - 40 = Completado
      - etc.
    - Resto de filtros: igual que /pedidos-simple
    """
    # Query base
    query = db.query(
        SaleOrderHeader,
        TBCustomer.cust_name.label('nombre_cliente'),
        TBUser.user_name.label('user_name')
    ).outerjoin(
        TBCustomer,
        and_(
            SaleOrderHeader.cust_id == TBCustomer.cust_id,
            SaleOrderHeader.comp_id == TBCustomer.comp_id
        )
    ).outerjoin(
        TBUser,
        SaleOrderHeader.user_id == TBUser.user_id
    )
    
    # Filtro por estado ERP (opcional)
    if ssos_id is not None:
        query = query.filter(SaleOrderHeader.ssos_id == ssos_id)
    
    # Filtros adicionales
    if solo_tn:
        query = query.filter(
            and_(
                SaleOrderHeader.ws_internalid.isnot(None),
                SaleOrderHeader.ws_internalid != ''
            )
        )
    
    if solo_ml:
        query = query.filter(
            and_(
                SaleOrderHeader.soh_mlid.isnot(None),
                SaleOrderHeader.soh_mlid != ''
            )
        )
    
    if user_id:
        query = query.filter(SaleOrderHeader.user_id == user_id)
    
    if solo_sin_direccion:
        query = query.filter(
            and_(
                or_(
                    SaleOrderHeader.override_shipping_address.is_(None),
                    SaleOrderHeader.override_shipping_address == ''
                ),
                or_(
                    SaleOrderHeader.tiendanube_shipping_address.is_(None),
                    SaleOrderHeader.tiendanube_shipping_address == ''
                ),
                or_(
                    SaleOrderHeader.soh_deliveryaddress.is_(None),
                    SaleOrderHeader.soh_deliveryaddress == ''
                )
            )
        )
    
    if provincia:
        query = query.filter(
            or_(
                SaleOrderHeader.override_shipping_province.ilike(f'%{provincia}%'),
                SaleOrderHeader.tiendanube_shipping_province.ilike(f'%{provincia}%')
            )
        )
    
    if buscar:
        search_pattern = f'%{buscar}%'
        query = query.filter(
            or_(
                SaleOrderHeader.soh_id.cast(db.bind.dialect.type_descriptor(text('VARCHAR'))).ilike(search_pattern),
                SaleOrderHeader.ws_internalid.ilike(search_pattern),
                SaleOrderHeader.tiendanube_number.ilike(search_pattern),
                SaleOrderHeader.soh_mlid.ilike(search_pattern),
                TBCustomer.cust_name.ilike(search_pattern),
                SaleOrderHeader.override_shipping_address.ilike(search_pattern),
                SaleOrderHeader.tiendanube_shipping_address.ilike(search_pattern),
                SaleOrderHeader.soh_deliveryaddress.ilike(search_pattern),
                SaleOrderHeader.override_shipping_province.ilike(search_pattern),
                SaleOrderHeader.tiendanube_shipping_province.ilike(search_pattern),
                SaleOrderHeader.override_shipping_city.ilike(search_pattern),
                SaleOrderHeader.tiendanube_shipping_city.ilike(search_pattern),
                SaleOrderHeader.override_shipping_recipient.ilike(search_pattern),
                SaleOrderHeader.tiendanube_recipient_name.ilike(search_pattern),
                SaleOrderHeader.soh_observation1.ilike(search_pattern),
                SaleOrderHeader.soh_internalannotation.ilike(search_pattern)
            )
        )
    
    # Ordenar por fecha de creación descendente
    query = query.order_by(SaleOrderHeader.soh_cd.desc())
    
    # Paginación
    query = query.offset(offset).limit(limit)
    
    # Ejecutar query
    resultados = query.all()
    
    # Construir respuesta
    pedidos = []
    for pedido, nombre_cliente, user_name in resultados:
        # Obtener items del pedido (excluyendo 2953 y 2954)
        items_query = db.query(
            SaleOrderDetail.item_id,
            SaleOrderDetail.sod_qty,
            TBItem.item_desc,
            TBItem.item_code
        ).outerjoin(
            TBItem,
            and_(
                SaleOrderDetail.item_id == TBItem.item_id,
                SaleOrderDetail.comp_id == TBItem.comp_id
            )
        ).filter(
            and_(
                SaleOrderDetail.soh_id == pedido.soh_id,
                SaleOrderDetail.bra_id == pedido.bra_id,
                func.coalesce(SaleOrderDetail.item_id, SaleOrderDetail.sod_item_id_origin).notin_([2953, 2954])
            )
        )
        
        items = []
        total_items = 0
        for item_id, cantidad, item_desc, item_code in items_query.all():
            items.append(ItemPedidoDetalle(
                item_id=item_id,
                cantidad=cantidad,
                item_desc=item_desc,
                item_code=item_code
            ))
            total_items += int(cantidad) if cantidad else 0
        
        # Construir pedido detallado
        pedido_dict = {
            # IDs
            'soh_id': pedido.soh_id,
            'comp_id': pedido.comp_id,
            'bra_id': pedido.bra_id,
            'cust_id': pedido.cust_id,
            'user_id': pedido.user_id,
            
            # Cliente
            'nombre_cliente': nombre_cliente,
            
            # Usuario (canal)
            'user_name': user_name,
            
            # Fechas
            'soh_cd': pedido.soh_cd,
            'soh_deliverydate': pedido.soh_deliverydate,
            
            # Direcciones
            'soh_deliveryaddress': pedido.soh_deliveryaddress,
            'soh_observation2': pedido.soh_observation2,
            
            # Observaciones
            'soh_observation1': pedido.soh_observation1,
            'soh_internalannotation': pedido.soh_internalannotation,
            
            # TiendaNube
            'ws_internalid': pedido.ws_internalid,
            'tiendanube_number': pedido.tiendanube_number,
            'tiendanube_shipping_phone': pedido.tiendanube_shipping_phone,
            'tiendanube_shipping_address': pedido.tiendanube_shipping_address,
            'tiendanube_shipping_city': pedido.tiendanube_shipping_city,
            'tiendanube_shipping_province': pedido.tiendanube_shipping_province,
            'tiendanube_shipping_zipcode': pedido.tiendanube_shipping_zipcode,
            'tiendanube_recipient_name': pedido.tiendanube_recipient_name,
            
            # MercadoLibre
            'soh_mlid': pedido.soh_mlid,
            'mlshippingid': pedido.mlshippingid,
            
            # Override
            'override_shipping_address': pedido.override_shipping_address,
            'override_shipping_city': pedido.override_shipping_city,
            'override_shipping_province': pedido.override_shipping_province,
            'override_shipping_zipcode': pedido.override_shipping_zipcode,
            'override_shipping_phone': pedido.override_shipping_phone,
            'override_shipping_recipient': pedido.override_shipping_recipient,
            'override_notes': pedido.override_notes,
            'override_modified_at': pedido.override_modified_at,
            'override_num_bultos': pedido.override_num_bultos,
            'override_tipo_domicilio': pedido.override_tipo_domicilio,
            
            # Otros
            'soh_packagesqty': pedido.soh_packagesqty,
            'soh_total': pedido.soh_total,
            
            # Items
            'total_items': total_items,
            'items': items
        }
        
        pedidos.append(PedidoDetallado(**pedido_dict))
    
    return pedidos


@router.get("/pedidos-local/estadisticas")
async def obtener_estadisticas_local(
    db: Session = Depends(get_db),
    ssos_id: Optional[int] = Query(None, description="Filtrar estadísticas por estado ERP (20=Pendiente)")
):
    """
    Estadísticas de pedidos en la DB local.
    Si se proporciona ssos_id, filtra por ese estado (ej: 20 para pendientes).
    """
    # Base query
    base_filter = []
    if ssos_id is not None:
        base_filter.append(SaleOrderHeader.ssos_id == ssos_id)
    
    # Total de pedidos
    query = db.query(func.count(SaleOrderHeader.soh_id))
    if base_filter:
        query = query.filter(and_(*base_filter))
    total_pedidos = query.scalar()
    
    # Total de items
    query = db.query(func.sum(SaleOrderDetail.sod_qty)).join(
        SaleOrderHeader,
        and_(
            SaleOrderDetail.soh_id == SaleOrderHeader.soh_id,
            SaleOrderDetail.bra_id == SaleOrderHeader.bra_id
        )
    ).filter(
        func.coalesce(SaleOrderDetail.item_id, SaleOrderDetail.sod_item_id_origin).notin_([2953, 2954])
    )
    if base_filter:
        query = query.filter(and_(*base_filter))
    total_items = query.scalar() or 0
    
    # Con TiendaNube
    query = db.query(func.count(SaleOrderHeader.soh_id)).filter(
        and_(
            SaleOrderHeader.ws_internalid.isnot(None),
            SaleOrderHeader.ws_internalid != ''
        )
    )
    if base_filter:
        query = query.filter(and_(*base_filter))
    con_tiendanube = query.scalar()
    
    # Con MercadoLibre
    query = db.query(func.count(SaleOrderHeader.soh_id)).filter(
        and_(
            SaleOrderHeader.soh_mlid.isnot(None),
            SaleOrderHeader.soh_mlid != ''
        )
    )
    if base_filter:
        query = query.filter(and_(*base_filter))
    con_mercadolibre = query.scalar()
    
    # Sin dirección
    query = db.query(func.count(SaleOrderHeader.soh_id)).filter(
        and_(
            or_(
                SaleOrderHeader.override_shipping_address.is_(None),
                SaleOrderHeader.override_shipping_address == ''
            ),
            or_(
                SaleOrderHeader.tiendanube_shipping_address.is_(None),
                SaleOrderHeader.tiendanube_shipping_address == ''
            ),
            or_(
                SaleOrderHeader.soh_deliveryaddress.is_(None),
                SaleOrderHeader.soh_deliveryaddress == ''
            )
        )
    )
    if base_filter:
        query = query.filter(and_(*base_filter))
    sin_direccion = query.scalar()
    
    return {
        "total_pedidos": total_pedidos,
        "total_items": int(total_items),
        "con_tiendanube": con_tiendanube,
        "con_mercadolibre": con_mercadolibre,
        "sin_direccion": sin_direccion,
        "ultima_sync": None  # No aplica en modo local
    }


@router.post("/pedidos-local/sincronizar")
async def sincronizar_pedidos_local(db: Session = Depends(get_db)):
    """
    Sincroniza las tablas de pedidos desde el ERP y limpia registros archivados.
    
    Pasos:
    1. Sincroniza tb_sale_order_header desde ERP
    2. Sincroniza tb_sale_order_detail desde ERP
    3. Sincroniza tb_tiendanube_orders desde TiendaNube
    4. Limpia pedidos archivados (ejecuta sync_archived_orders.py)
    
    Este endpoint reemplaza la sincronización vía export_id=80 que incluía pedidos archivados.
    """
    from app.scripts.sync_archived_orders import sync_archived_headers, sync_archived_details
    
    logger.info("🔄 Iniciando sincronización de pedidos local...")
    
    try:
        # Limpiar headers archivados
        logger.info("📋 Limpiando headers archivados...")
        result_headers = sync_archived_headers()
        headers_borrados = result_headers.get('headers_borrados', 0)
        
        if 'error' in result_headers:
            logger.error(f"❌ Error en headers: {result_headers['error']}")
            raise HTTPException(500, f"Error limpiando headers: {result_headers['error']}")
        
        # Limpiar details archivados
        logger.info("📋 Limpiando details archivados...")
        result_details = sync_archived_details()
        details_borrados = result_details.get('details_borrados', 0)
        
        if 'error' in result_details:
            logger.error(f"❌ Error en details: {result_details['error']}")
            raise HTTPException(500, f"Error limpiando details: {result_details['error']}")
        
        logger.info(f"✅ Sincronización completada: {headers_borrados} headers y {details_borrados} details limpiados")
        
        return {
            "mensaje": "Sincronización completada exitosamente",
            "headers_archivados_limpiados": headers_borrados,
            "details_archivados_limpiados": details_borrados,
            "detalle": "Los pedidos archivados han sido removidos de las tablas locales"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Error inesperado: {e}", exc_info=True)
        raise HTTPException(500, f"Error inesperado: {str(e)}")
