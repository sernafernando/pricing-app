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
    - user_id: Filtrar por vendedor específico (ej: 50021 para TiendaNube)
    - ssos_id: Filtrar por estado del pedido (ej: 20 para pendiente de preparación)
    - solo_ml: Solo pedidos de MercadoLibre (tienen soh_mlid)
    - solo_tn: Solo pedidos de TiendaNube (tienen ws_internalid)
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
    
    if solo_ml:
        query = query.filter(SaleOrderHeader.soh_mlid.isnot(None))
    
    if solo_tn:
        query = query.filter(SaleOrderHeader.ws_internalid.isnot(None))
    
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


def procesar_pedidos_export_80(data: List[Dict[str, Any]], db: Session, force_full: bool = False):
    """
    Procesa los datos del export 80 y actualiza la DB.
    Marca pedidos activos y archiva los que ya no están.
    Se ejecuta en background.
    
    Filtros aplicados:
    - user_id = 50021 (vendedor TiendaNube)
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
        
        # 1. Recolectar IDs de pedidos actuales en el export
        logger.info(f"Procesando {len(data)} registros desde el export 80")
        for row in data:
            soh_id = row.get("IDPedido")
            if soh_id:
                soh_ids_actuales.add(soh_id)
        
        logger.info(f"Total de pedidos únicos en el export (sin filtrar): {len(soh_ids_actuales)}")
        
        # 2. Aplicar filtros: Solo pedidos con user_id=50021 y ssos_id=20
        pedidos_filtrados = db.query(SaleOrderHeader.soh_id).filter(
            and_(
                SaleOrderHeader.soh_id.in_(soh_ids_actuales),
                SaleOrderHeader.user_id == 50021,
                SaleOrderHeader.ssos_id == 20
            )
        ).all()
        
        soh_ids_filtrados = set([p.soh_id for p in pedidos_filtrados])
        logger.info(f"Pedidos que cumplen filtros (user_id=50021, ssos_id=20): {len(soh_ids_filtrados)}")
        
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
        
        # 4. Marcar pedidos válidos como activos (batch por performance)
        batch_size = 100
        soh_ids_list = list(soh_ids_validos)
        
        for i in range(0, len(soh_ids_list), batch_size):
            batch = soh_ids_list[i:i + batch_size]
            
            # Update masivo
            db.query(SaleOrderHeader).filter(
                SaleOrderHeader.soh_id.in_(batch)
            ).update(
                {
                    "export_id": 80,
                    "export_activo": True
                },
                synchronize_session=False
            )
            
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
