"""
Endpoint para obtener pedidos DIRECTAMENTE desde la DB local.
Replica la lógica del Export 87 del ERP (WHERE ssos_id = 20)
SIN necesidad de llamar al gbp-parser.
"""
from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import and_, or_, func, text
from typing import List, Optional
from datetime import datetime, timedelta
import json

from app.core.database import get_db
from app.api.deps import get_current_user
from app.models.usuario import Usuario
from app.models.sale_order_header import SaleOrderHeader
from app.models.sale_order_detail import SaleOrderDetail
from app.models.sale_order_times import SaleOrderTimes
from app.models.tb_customer import TBCustomer
from app.models.tb_item import TBItem
from app.models.tb_user import TBUser
from app.models.tienda_nube_order import TiendaNubeOrder
from app.api.endpoints.pedidos_export_simple import PedidoDetallado, ItemPedidoDetalle
from app.services.tienda_nube_order_client import TiendaNubeOrderClient

import logging

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/pedidos-local", response_model=List[PedidoDetallado])
async def obtener_pedidos_local(
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
    ssos_id: Optional[int] = Query(None, description="Filtrar por estado ERP (20=Pendiente, 30=En Proceso, 40=Completado, etc)"),
    solo_tn: bool = Query(False),
    solo_ml: bool = Query(False),
    solo_sin_direccion: bool = Query(False),
    user_id: Optional[int] = Query(None),
    provincia: Optional[str] = Query(None),
    buscar: Optional[str] = Query(None),
    dias_atras: int = Query(60, ge=1, le=365, description="Mostrar solo pedidos de los últimos N días (default: 60)"),
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
        TBUser.user_name.label('user_name'),
        TiendaNubeOrder.tno_orderid.label('tn_orderid'),
        TiendaNubeOrder.tno_json.label('tn_json')
    ).outerjoin(
        TBCustomer,
        and_(
            SaleOrderHeader.cust_id == TBCustomer.cust_id,
            SaleOrderHeader.comp_id == TBCustomer.comp_id
        )
    ).outerjoin(
        TBUser,
        SaleOrderHeader.user_id == TBUser.user_id
    ).outerjoin(
        TiendaNubeOrder,
        and_(
            SaleOrderHeader.soh_id == TiendaNubeOrder.soh_id,
            SaleOrderHeader.bra_id == TiendaNubeOrder.bra_id
        )
    )
    
    # EXCLUIR pedidos cerrados (ssot_id = 40 en tb_sale_order_times)
    # Subquery para obtener soh_ids con ssot_id = 40
    subquery_cerrados = db.query(SaleOrderTimes.soh_id).filter(
        SaleOrderTimes.ssot_id == 40
    ).distinct()
    
    query = query.filter(
        ~SaleOrderHeader.soh_id.in_(subquery_cerrados)
    )
    
    # FILTRO POR FECHA: Solo pedidos de los últimos N días (desde las 00:00:00 del día inicial)
    fecha_limite = datetime.combine(datetime.now().date() - timedelta(days=dias_atras), datetime.min.time())
    query = query.filter(SaleOrderHeader.soh_cd >= fecha_limite)
    
    # Filtro por estado ERP (opcional)
    if ssos_id is not None:
        query = query.filter(SaleOrderHeader.ssos_id == ssos_id)
    
    # Filtros adicionales
    if solo_tn:
        # Filtrar por pedidos que tengan registro en tb_tiendanube_orders
        query = query.filter(TiendaNubeOrder.tno_orderid.isnot(None))
    
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
        
        # Construir lista de filtros
        search_filters = [
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
        ]
        
        # Si es un número, buscar por soh_id
        if buscar.strip().isdigit():
            search_filters.append(SaleOrderHeader.soh_id == int(buscar.strip()))
        
        query = query.filter(or_(*search_filters))
    
    # Ordenar por fecha de creación descendente
    query = query.order_by(SaleOrderHeader.soh_cd.desc())
    
    # Paginación
    query = query.offset(offset).limit(limit)
    
    # Ejecutar query
    resultados = query.all()
    
    # Construir respuesta
    pedidos = []
    for pedido, nombre_cliente, user_name, tn_orderid, tn_json in resultados:
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
                or_(
                    func.coalesce(SaleOrderDetail.item_id, SaleOrderDetail.sod_item_id_origin).is_(None),
                    func.coalesce(SaleOrderDetail.item_id, SaleOrderDetail.sod_item_id_origin).notin_([2953, 2954])
                )
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
        
        # Excluir pedidos sin items (después de filtrar 2953/2954)
        if total_items == 0:
            continue
        
        # Parsear datos de TiendaNube desde JSON si existe
        tn_data = {}
        tn_json_has_shipping = False
        
        if tn_json:
            try:
                tn_parsed = json.loads(tn_json)
                shipping_addr = tn_parsed.get('shipping_address', {})
                
                # Verificar si el JSON tiene datos de shipping
                if shipping_addr and shipping_addr.get('address'):
                    tn_json_has_shipping = True
                    
                    # Construir dirección completa concatenando campos
                    address_parts = [shipping_addr.get('address', '')]
                    if shipping_addr.get('number'):
                        address_parts.append(shipping_addr.get('number'))
                    if shipping_addr.get('floor'):
                        address_parts.append(shipping_addr.get('floor'))
                    
                    # Agregar localidad si es diferente de city
                    locality = shipping_addr.get('locality', '')
                    city = shipping_addr.get('city', '')
                    if locality and locality != city:
                        address_parts.append(locality)
                    
                    full_address = ' '.join(filter(None, address_parts))
                    
                    tn_data = {
                        'ws_internalid': str(tn_orderid) if tn_orderid else pedido.ws_internalid,
                        'tiendanube_number': str(tn_parsed.get('number', '')) if tn_parsed.get('number') else pedido.tiendanube_number,
                        'tiendanube_shipping_address': full_address,
                        'tiendanube_shipping_city': city,
                        'tiendanube_shipping_province': shipping_addr.get('province', ''),
                        'tiendanube_shipping_zipcode': shipping_addr.get('zipcode', ''),
                        'tiendanube_shipping_phone': shipping_addr.get('phone', ''),
                        'tiendanube_recipient_name': shipping_addr.get('name', ''),
                    }
            except (json.JSONDecodeError, KeyError, AttributeError) as e:
                logger.warning(f"Error parsing TN JSON for soh_id {pedido.soh_id}: {e}")
        
        # Si no hay datos de shipping en el JSON, intentar fallback a API de TN
        if not tn_json_has_shipping and tn_orderid:
            logger.info(f"JSON vacío para pedido {pedido.soh_id}, intentando fallback a API TN para order {tn_orderid}")
            try:
                tn_client = TiendaNubeOrderClient()
                tn_api_data = await tn_client.get_order_details(tn_orderid)
                
                if tn_api_data:
                    shipping_addr = tn_api_data.get('shipping_address', {})
                    if shipping_addr and shipping_addr.get('address'):
                        logger.info(f"✅ Datos obtenidos desde API TN para order {tn_orderid}")
                        
                        # Construir dirección completa concatenando campos
                        address_parts = [shipping_addr.get('address', '')]
                        if shipping_addr.get('number'):
                            address_parts.append(shipping_addr.get('number'))
                        if shipping_addr.get('floor'):
                            address_parts.append(shipping_addr.get('floor'))
                        
                        locality = shipping_addr.get('locality', '')
                        city = shipping_addr.get('city', '')
                        if locality and locality != city:
                            address_parts.append(locality)
                        
                        full_address = ' '.join(filter(None, address_parts))
                        
                        tn_data = {
                            'ws_internalid': str(tn_orderid),
                            'tiendanube_number': str(tn_api_data.get('number', '')),
                            'tiendanube_shipping_address': full_address,
                            'tiendanube_shipping_city': city,
                            'tiendanube_shipping_province': shipping_addr.get('province', ''),
                            'tiendanube_shipping_zipcode': shipping_addr.get('zipcode', ''),
                            'tiendanube_shipping_phone': shipping_addr.get('phone', ''),
                            'tiendanube_recipient_name': shipping_addr.get('name', ''),
                        }
                    else:
                        logger.warning(f"API TN devolvió datos pero sin shipping address para order {tn_orderid}")
            except Exception as e:
                logger.error(f"Error en fallback a API TN para order {tn_orderid}: {e}")
        
        # Si aún no hay datos, usar fallback a tb_sale_order_header
        if not tn_data:
            tn_data = {
                'ws_internalid': str(tn_orderid) if tn_orderid else pedido.ws_internalid,
                'tiendanube_number': pedido.tiendanube_number,
                'tiendanube_shipping_address': pedido.tiendanube_shipping_address,
                'tiendanube_shipping_city': pedido.tiendanube_shipping_city,
                'tiendanube_shipping_province': pedido.tiendanube_shipping_province,
                'tiendanube_shipping_zipcode': pedido.tiendanube_shipping_zipcode,
                'tiendanube_shipping_phone': pedido.tiendanube_shipping_phone,
                'tiendanube_recipient_name': pedido.tiendanube_recipient_name,
            }
        
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
            
            # TiendaNube (usar datos parseados del JSON)
            'ws_internalid': tn_data.get('ws_internalid'),
            'tiendanube_number': tn_data.get('tiendanube_number'),
            'tiendanube_shipping_phone': tn_data.get('tiendanube_shipping_phone'),
            'tiendanube_shipping_address': tn_data.get('tiendanube_shipping_address'),
            'tiendanube_shipping_city': tn_data.get('tiendanube_shipping_city'),
            'tiendanube_shipping_province': tn_data.get('tiendanube_shipping_province'),
            'tiendanube_shipping_zipcode': tn_data.get('tiendanube_shipping_zipcode'),
            'tiendanube_recipient_name': tn_data.get('tiendanube_recipient_name'),
            
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
    current_user: Usuario = Depends(get_current_user),
    ssos_id: Optional[int] = Query(None, description="Filtrar estadísticas por estado ERP (20=Pendiente)"),
    dias_atras: int = Query(60, ge=1, le=365, description="Mostrar solo pedidos de los últimos N días (default: 60)")
):
    """
    Estadísticas de pedidos en la DB local.
    Si se proporciona ssos_id, filtra por ese estado (ej: 20 para pendientes).
    EXCLUYE pedidos cerrados (ssot_id = 40 en tb_sale_order_times).
    EXCLUYE pedidos con más de dias_atras días de antigüedad.
    """
    # Subquery para excluir pedidos cerrados
    subquery_cerrados = db.query(SaleOrderTimes.soh_id).filter(
        SaleOrderTimes.ssot_id == 40
    ).distinct()
    
    # Filtro de fecha: Solo pedidos de los últimos N días (desde las 00:00:00 del día inicial)
    fecha_limite = datetime.combine(datetime.now().date() - timedelta(days=dias_atras), datetime.min.time())
    
    # Base query
    base_filter = [
        ~SaleOrderHeader.soh_id.in_(subquery_cerrados),
        SaleOrderHeader.soh_cd >= fecha_limite
    ]
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
        or_(
            func.coalesce(SaleOrderDetail.item_id, SaleOrderDetail.sod_item_id_origin).is_(None),
            func.coalesce(SaleOrderDetail.item_id, SaleOrderDetail.sod_item_id_origin).notin_([2953, 2954])
        )
    )
    if base_filter:
        query = query.filter(and_(*base_filter))
    total_items = query.scalar() or 0
    
    # Con TiendaNube (contar pedidos que tienen registro en tb_tiendanube_orders)
    query = db.query(func.count(SaleOrderHeader.soh_id)).join(
        TiendaNubeOrder,
        and_(
            SaleOrderHeader.soh_id == TiendaNubeOrder.soh_id,
            SaleOrderHeader.bra_id == TiendaNubeOrder.bra_id
        )
    ).filter(
        TiendaNubeOrder.tno_orderid.isnot(None)
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
        "ultima_sync": None,  # No aplica en modo local
        "dias_filtro": dias_atras,
        "fecha_desde": fecha_limite.strftime("%Y-%m-%d")
    }


@router.post("/pedidos-local/sincronizar")
async def sincronizar_pedidos_local(
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user)
):
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
