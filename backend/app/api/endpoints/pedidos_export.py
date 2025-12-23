"""
Endpoint para visualización de pedidos de exportación.
Integración del visualizador-pedidos en la pricing-app.
"""
from fastapi import APIRouter, Depends, HTTPException, Query, BackgroundTasks
from sqlalchemy.orm import Session
from sqlalchemy import func, and_, or_, desc
from typing import List, Optional, Dict, Any
from datetime import datetime, date
from pydantic import BaseModel
import httpx
import logging

from app.core.database import get_db
from app.models.sale_order_header import SaleOrderHeader
from app.models.sale_order_detail import SaleOrderDetail
from app.api.deps import get_current_user
from app.services.tienda_nube_order_client import TiendaNubeOrderClient

router = APIRouter()
logger = logging.getLogger(__name__)


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
    
    # Usuario y estado
    user_id: Optional[int]
    ssos_id: Optional[int]
    
    # Observaciones y notas
    observacion: Optional[str]
    nota_interna: Optional[str]
    
    # ML y Tienda Nube
    ml_order_id: Optional[str]
    ml_shipping_id: Optional[int]
    tiendanube_order_id: Optional[str]
    
    # Datos enriquecidos desde TiendaNube API
    tiendanube_number: Optional[str]  # Número de orden visible en TN (NRO-XXXXX)
    tiendanube_shipping_phone: Optional[str]
    tiendanube_shipping_address: Optional[str]
    tiendanube_shipping_city: Optional[str]
    tiendanube_shipping_province: Optional[str]
    tiendanube_shipping_zipcode: Optional[str]
    tiendanube_recipient_name: Optional[str]
    
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
    solo_activos: bool = Query(True, description="Solo pedidos activos (no archivados)"),
    user_id: Optional[int] = Query(None, description="Filtrar por user_id específico"),
    ssos_id: Optional[int] = Query(None, description="Filtrar por ssos_id (estado del pedido)"),
    solo_ml: bool = Query(False, description="Solo pedidos de MercadoLibre"),
    solo_tn: bool = Query(False, description="Solo pedidos de TiendaNube"),
    sin_codigo_envio: bool = Query(False, description="Solo pedidos sin código de envío asignado"),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0)
):
    """
    Obtiene pedidos filtrados por export_id del ERP.
    Export ID 80 típicamente corresponde a pedidos pendientes de preparación.
    
    Filtros opcionales disponibles:
    - user_id: Filtrar por vendedor específico (ej: 50021 para TiendaNube, 50006 para ML)
    - ssos_id: Filtrar por estado del pedido (ej: 20 para pendiente de preparación)
    - solo_ml: Solo pedidos de MercadoLibre (user_id = 50006)
    - solo_tn: Solo pedidos de TiendaNube (user_id = 50021)
    - sin_codigo_envio: Solo pedidos que aún no tienen código de envío asignado
    
    Por defecto solo muestra activos, usar solo_activos=false para ver archivados.
    """
    # Query principal
    query = db.query(SaleOrderHeader).filter(
        SaleOrderHeader.export_id == export_id
    )
    
    # Filtrar por activos/archivados
    if solo_activos:
        query = query.filter(SaleOrderHeader.export_activo == True)
    
    # Filtros opcionales
    if user_id is not None:
        query = query.filter(SaleOrderHeader.user_id == user_id)
    
    if ssos_id is not None:
        query = query.filter(SaleOrderHeader.ssos_id == ssos_id)
    
    # Filtros por canal (basados en user_id del vendedor)
    if solo_ml:
        query = query.filter(SaleOrderHeader.user_id == 50006)  # Vendedor ML
    
    if solo_tn:
        query = query.filter(SaleOrderHeader.user_id == 50021)  # Vendedor TiendaNube
    
    if sin_codigo_envio:
        query = query.filter(SaleOrderHeader.codigo_envio_interno.is_(None))
    
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
            user_id=pedido.user_id,
            ssos_id=pedido.ssos_id,
            observacion=pedido.soh_observation1,
            nota_interna=pedido.soh_internalannotation,
            ml_order_id=pedido.soh_mlid,
            ml_shipping_id=pedido.mlshippingid,
            tiendanube_order_id=pedido.ws_internalid,
            tiendanube_number=pedido.tiendanube_number,
            tiendanube_shipping_phone=pedido.tiendanube_shipping_phone,
            tiendanube_shipping_address=pedido.tiendanube_shipping_address,
            tiendanube_shipping_city=pedido.tiendanube_shipping_city,
            tiendanube_shipping_province=pedido.tiendanube_shipping_province,
            tiendanube_shipping_zipcode=pedido.tiendanube_shipping_zipcode,
            tiendanube_recipient_name=pedido.tiendanube_recipient_name,
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
            user_id=pedido.user_id,
            ssos_id=pedido.ssos_id,
            observacion=pedido.soh_observation1,
            nota_interna=pedido.soh_internalannotation,
            ml_order_id=pedido.soh_mlid,
            ml_shipping_id=pedido.mlshippingid,
            tiendanube_order_id=pedido.ws_internalid,
            tiendanube_number=pedido.tiendanube_number,
            tiendanube_shipping_phone=pedido.tiendanube_shipping_phone,
            tiendanube_shipping_address=pedido.tiendanube_shipping_address,
            tiendanube_shipping_city=pedido.tiendanube_shipping_city,
            tiendanube_shipping_province=pedido.tiendanube_shipping_province,
            tiendanube_shipping_zipcode=pedido.tiendanube_shipping_zipcode,
            tiendanube_recipient_name=pedido.tiendanube_recipient_name,
            codigo_envio_interno=pedido.codigo_envio_interno,
            tipo_envio=None,
            bultos=pedido.soh_packagesqty,
            estado=pedido.soh_statusof,
            total=float(pedido.soh_total) if pedido.soh_total else None,
            items=[]
        ))
    
    return result


@router.post("/pedidos-export/sincronizar-export-80")
async def sincronizar_export_80(
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    force_full: bool = Query(False, description="Forzar sincronización completa (puede tardar varios minutos)")
):
    """
    Sincroniza pedidos desde el export_id 87 del ERP (sin filtros) via gbp-parser.
    Marca los pedidos con export_id=80 para mantener compatibilidad.
    
    Query 87 = TODOS los pedidos pendientes sin filtros
    Los filtros se aplican después en nuestra DB.
    
    Si force_full=true, hace sincronización completa (puede tardar).
    """
    logger.info("Iniciando sincronización desde export_id=87 (query sin filtros)")
    
    try:
        # Llamar a gbp-parser para obtener datos del export 87 (sin filtros)
        async with httpx.AsyncClient(timeout=300.0) as client:  # 5 minutos timeout para sync masivo
            response = await client.post(
                "http://localhost:8002/api/gbp-parser",
                json={"intExpgr_id": 87}  # Query 87 = todos los pedidos sin filtros
            )
            response.raise_for_status()
            data = response.json()
        
        if not data or not isinstance(data, list):
            raise HTTPException(500, "No se obtuvieron datos del export 87")
        
        logger.info(f"Obtenidos {len(data)} registros desde export_id=87 (query sin filtros)")
        
        # Procesar y guardar en background
        background_tasks.add_task(procesar_pedidos_export_80, data, db, force_full)
        
        return {
            "mensaje": "Sincronización iniciada en background",
            "registros_obtenidos": len(data),
            "export_id_origen": 87,
            "export_id_destino": 80,
            "modo": "completo" if force_full else "incremental"
        }
        
    except httpx.HTTPError as e:
        logger.error(f"Error llamando a gbp-parser: {e}")
        raise HTTPException(500, f"Error consultando ERP: {str(e)}")
    except Exception as e:
        logger.error(f"Error sincronizando export 80: {e}", exc_info=True)
        raise HTTPException(500, f"Error en sincronización: {str(e)}")


async def enriquecer_pedidos_tiendanube(db: Session, soh_ids: set):
    """
    Enriquece pedidos de TiendaNube con datos de la API.
    Solo enriquece pedidos que:
    - user_id = 50021 (TiendaNube)
    - Tienen ws_internalid (order ID de TN)
    - NO tienen tiendanube_number (aún no enriquecidos)
    """
    # Buscar pedidos TN sin enriquecer
    pedidos_tn = db.query(SaleOrderHeader).filter(
        and_(
            SaleOrderHeader.soh_id.in_(soh_ids),
            SaleOrderHeader.user_id == 50021,
            SaleOrderHeader.ws_internalid.isnot(None),
            SaleOrderHeader.tiendanube_number.is_(None)  # No enriquecido
        )
    ).all()
    
    if not pedidos_tn:
        logger.info("No hay pedidos TN nuevos para enriquecer")
        return
    
    logger.info(f"Enriqueciendo {len(pedidos_tn)} pedidos TN con API...")
    
    tn_client = TiendaNubeOrderClient()
    enriquecidos = 0
    errores = 0
    
    for pedido in pedidos_tn:
        try:
            tn_order_id = int(pedido.ws_internalid)
            tn_data = await tn_client.get_order_details(tn_order_id)
            
            if not tn_data:
                logger.warning(f"No se obtuvieron datos TN para orden {tn_order_id}")
                errores += 1
                continue
            
            # Actualizar campos con datos de TN
            pedido.tiendanube_number = tn_data.get('number')
            
            shipping_address = tn_data.get('shipping_address', {})
            if shipping_address:
                pedido.tiendanube_shipping_phone = shipping_address.get('phone')
                pedido.tiendanube_shipping_address = tn_client.build_shipping_address(shipping_address)
                pedido.tiendanube_shipping_city = shipping_address.get('city')
                pedido.tiendanube_shipping_province = shipping_address.get('province')
                pedido.tiendanube_shipping_zipcode = shipping_address.get('zipcode')
                pedido.tiendanube_recipient_name = shipping_address.get('name')
            
            enriquecidos += 1
            
        except (ValueError, TypeError) as e:
            logger.error(f"Error convirtiendo ws_internalid '{pedido.ws_internalid}' a int: {e}")
            errores += 1
        except Exception as e:
            logger.error(f"Error enriqueciendo pedido {pedido.soh_id}: {e}")
            errores += 1
    
    db.commit()
    logger.info(f"✅ Enriquecimiento TN completado: {enriquecidos} OK, {errores} errores")


def procesar_pedidos_export_80(data: List[Dict[str, Any]], db: Session, force_full: bool = False):
    """
    Procesa los datos del export 80 y actualiza la DB.
    Marca pedidos activos y archiva los que ya no están.
    Se ejecuta en background.
    
    Filtros aplicados:
    - user_id IN (50021, 50006) - Vendedores TiendaNube y MercadoLibre
    - ssos_id = 20 (estado: pendiente de preparación)
    - Excluye pedidos que SOLO tengan items 2953/2954 (items de envío/servicio)
    
    Args:
        data: Lista de registros desde el ERP
        db: Session de SQLAlchemy
        force_full: Si True, hace commit cada N registros para evitar timeout en syncs masivos
    """
    try:
        pedidos_actualizados = 0
        pedidos_archivados = 0
        pedidos_excluidos = 0
        soh_ids_actuales = set()
        
        # 1. Recolectar IDs de pedidos actuales en el export y mapear orderID (TN)
        logger.info(f"Procesando {len(data)} registros desde el export 80")
        order_id_map = {}  # {soh_id: orderID de TN}
        
        for row in data:
            soh_id = row.get("IDPedido")
            if soh_id:
                soh_ids_actuales.add(soh_id)
                # Guardar orderID de TiendaNube si existe
                order_id = row.get("orderID")
                if order_id and soh_id not in order_id_map:
                    order_id_map[soh_id] = str(order_id)
        
        logger.info(f"Total de pedidos únicos en el export (sin filtrar): {len(soh_ids_actuales)}")
        logger.info(f"Pedidos con orderID de TiendaNube: {len(order_id_map)}")
        
        # 2. Aplicar filtros: Solo pedidos con user_id IN (50021, 50006) y ssos_id=20
        pedidos_filtrados = db.query(SaleOrderHeader.soh_id).filter(
            and_(
                SaleOrderHeader.soh_id.in_(soh_ids_actuales),
                SaleOrderHeader.user_id.in_([50021, 50006]),  # TiendaNube y MercadoLibre
                SaleOrderHeader.ssos_id == 20
            )
        ).all()
        
        soh_ids_filtrados = set([p.soh_id for p in pedidos_filtrados])
        logger.info(f"Pedidos que cumplen filtros (user_id IN [50021,50006], ssos_id=20): {len(soh_ids_filtrados)}")
        
        # 3. Excluir pedidos que SOLO tienen items 2953/2954 (envíos/servicios)
        # Verificamos pedidos que tienen TODOS sus items en (2953, 2954)
        pedidos_solo_servicio = db.query(SaleOrderDetail.soh_id).filter(
            SaleOrderDetail.soh_id.in_(soh_ids_filtrados)
        ).group_by(SaleOrderDetail.soh_id).having(
            func.count(SaleOrderDetail.item_id) == func.sum(
                func.case((SaleOrderDetail.item_id.in_([2953, 2954]), 1), else_=0)
            )
        ).all()
        
        soh_ids_excluidos = set([p.soh_id for p in pedidos_solo_servicio])
        soh_ids_validos = soh_ids_filtrados - soh_ids_excluidos
        
        pedidos_excluidos = len(soh_ids_excluidos)
        logger.info(f"Pedidos excluidos (solo items 2953/2954): {pedidos_excluidos}")
        logger.info(f"Pedidos válidos finales: {len(soh_ids_validos)}")
        
        # 4. Marcar pedidos válidos como activos y actualizar ws_internalid
        batch_size = 100
        soh_ids_list = list(soh_ids_validos)
        
        for i in range(0, len(soh_ids_list), batch_size):
            batch = soh_ids_list[i:i + batch_size]
            
            # Actualizar cada pedido individualmente para poder setear ws_internalid
            for soh_id in batch:
                update_data = {
                    "export_id": 80,
                    "export_activo": True
                }
                
                # Si tiene orderID de TN, actualizar ws_internalid
                if soh_id in order_id_map:
                    update_data["ws_internalid"] = order_id_map[soh_id]
                
                db.query(SaleOrderHeader).filter(
                    SaleOrderHeader.soh_id == soh_id
                ).update(update_data, synchronize_session=False)
            
            pedidos_actualizados += len(batch)
            
            if force_full and i % 500 == 0:
                db.commit()  # Commit parcial cada 500 registros
                logger.info(f"Procesados {pedidos_actualizados} pedidos...")
        
        # 5. Archivar pedidos que ya no están en el export 80 válido
        pedidos_archivados_count = db.query(SaleOrderHeader).filter(
            and_(
                SaleOrderHeader.export_id == 80,
                SaleOrderHeader.export_activo == True,
                SaleOrderHeader.soh_id.notin_(soh_ids_validos)
            )
        ).update(
            {"export_activo": False},
            synchronize_session=False
        )
        
        pedidos_archivados = pedidos_archivados_count
        
        db.commit()
        logger.info(
            f"✅ Sincronización completada: {pedidos_actualizados} pedidos activos, "
            f"{pedidos_archivados} pedidos archivados, {pedidos_excluidos} excluidos por filtros"
        )
        
        # 6. Copiar tno_orderid a ws_internalid desde tb_tiendanube_orders
        pedidos_tn_actualizados = db.execute(
            """
            UPDATE tb_sale_order_header tsoh
            SET ws_internalid = tno.tno_orderid::text
            FROM tb_tiendanube_orders tno
            WHERE tsoh.soh_id = tno.soh_id
              AND tsoh.bra_id = tno.bra_id
              AND tsoh.user_id = 50021
              AND tsoh.export_id = 80
              AND tsoh.export_activo = true
              AND tno.tno_orderid IS NOT NULL
              AND (tsoh.ws_internalid IS NULL OR tsoh.ws_internalid != tno.tno_orderid::text)
            """
        ).rowcount
        
        db.commit()
        logger.info(f"✅ Copiados {pedidos_tn_actualizados} tno_orderid a ws_internalid")
        
        # 7. Enriquecer pedidos TN con datos de la API (ejecuta de forma síncrona)
        import asyncio
        try:
            asyncio.run(enriquecer_pedidos_tiendanube(db, soh_ids_validos))
        except Exception as e:
            logger.error(f"Error en enriquecimiento TN: {e}")
        
    except Exception as e:
        db.rollback()
        logger.error(f"❌ Error procesando pedidos export 80: {e}", exc_info=True)


@router.get("/pedidos-export/{soh_id}/items", response_model=List[PedidoExportItem])
async def obtener_items_pedido(
    soh_id: int,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """Obtiene los items/productos de un pedido específico"""
    
    items = db.query(SaleOrderDetail).filter(
        SaleOrderDetail.soh_id == soh_id
    ).all()
    
    result = []
    for item in items:
        result.append(PedidoExportItem(
            item_id=item.item_id,
            item_code=None,  # TODO: Join con tabla items
            item_desc=None,   # TODO: Join con tabla items
            cantidad=float(item.sod_qty) if item.sod_qty else 0,
            precio_unitario=float(item.sod_price) if hasattr(item, 'sod_price') and item.sod_price else None
        ))
    
    return result


@router.get("/pedidos-export/estadisticas-sincronizacion")
async def estadisticas_sincronizacion(
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """Obtiene estadísticas de la última sincronización del export 80"""
    
    total_export_80 = db.query(func.count(SaleOrderHeader.soh_id)).filter(
        SaleOrderHeader.export_id == 80
    ).scalar() or 0
    
    activos = db.query(func.count(SaleOrderHeader.soh_id)).filter(
        and_(
            SaleOrderHeader.export_id == 80,
            SaleOrderHeader.export_activo == True
        )
    ).scalar() or 0
    
    archivados = db.query(func.count(SaleOrderHeader.soh_id)).filter(
        and_(
            SaleOrderHeader.export_id == 80,
            SaleOrderHeader.export_activo == False
        )
    ).scalar() or 0
    
    return {
        "export_id": 80,
        "total_pedidos": total_export_80,
        "activos": activos,
        "archivados": archivados,
        "porcentaje_activos": round((activos / total_export_80 * 100), 2) if total_export_80 > 0 else 0
    }
