"""
Endpoint SIMPLE para visualización de pedidos del Export 87.
USA tb_pedidos_export - sin quilombo de JOINs.
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import func, and_, or_, text
from typing import List, Optional, Dict, Any
from datetime import datetime, date
from pydantic import BaseModel
import httpx
import logging

from app.core.database import get_db
from app.models.pedido_export import PedidoExport
from app.api.deps import get_current_user
from app.services.tienda_nube_order_client import TiendaNubeOrderClient

router = APIRouter()
logger = logging.getLogger(__name__)


# Schemas
class ItemPedido(BaseModel):
    """Item dentro de un pedido"""
    item_id: int
    cantidad: float
    
    class Config:
        from_attributes = True


class PedidoResumen(BaseModel):
    """Resumen de un pedido (agrupado por id_pedido)"""
    id_pedido: int
    id_cliente: Optional[int]
    nombre_cliente: Optional[str]
    
    # Envío
    tipo_envio: Optional[str]
    direccion_envio: Optional[str]
    fecha_envio: Optional[datetime]
    observaciones: Optional[str]
    
    # TiendaNube
    orden_tn: Optional[str]
    order_id_tn: Optional[str]
    
    # Datos enriquecidos de TN API (si aplica)
    tn_shipping_phone: Optional[str] = None
    tn_shipping_address: Optional[str] = None
    tn_shipping_city: Optional[str] = None
    tn_shipping_province: Optional[str] = None
    
    # Items
    total_items: int
    items: List[ItemPedido] = []
    
    class Config:
        from_attributes = True


class EstadisticasPedidos(BaseModel):
    """Estadísticas de pedidos"""
    total_pedidos: int
    total_items: int
    con_tiendanube: int
    sin_direccion: int
    ultima_sync: Optional[datetime]


@router.get("/pedidos-export-v2", response_model=List[PedidoResumen])
async def obtener_pedidos(
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
    solo_activos: bool = Query(True, description="Solo pedidos activos"),
    solo_tn: bool = Query(False, description="Solo pedidos de TiendaNube"),
    buscar: Optional[str] = Query(None, description="Buscar por nombre cliente u orden TN"),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0)
):
    """
    Obtiene pedidos desde tb_pedidos_export.
    SIMPLE - sin quilombo de JOINs.
    """
    # Query base - seleccionar campos únicos por pedido
    query = db.query(
        PedidoExport.id_pedido,
        PedidoExport.id_cliente,
        PedidoExport.nombre_cliente,
        PedidoExport.tipo_envio,
        PedidoExport.direccion_envio,
        PedidoExport.fecha_envio,
        PedidoExport.observaciones,
        PedidoExport.orden_tn,
        PedidoExport.order_id_tn,
        func.count(PedidoExport.item_id).label('total_items')
    ).group_by(
        PedidoExport.id_pedido,
        PedidoExport.id_cliente,
        PedidoExport.nombre_cliente,
        PedidoExport.tipo_envio,
        PedidoExport.direccion_envio,
        PedidoExport.fecha_envio,
        PedidoExport.observaciones,
        PedidoExport.orden_tn,
        PedidoExport.order_id_tn
    )
    
    # Filtros
    if solo_activos:
        query = query.filter(PedidoExport.activo == True)
    
    if solo_tn:
        query = query.filter(PedidoExport.order_id_tn.isnot(None))
    
    if buscar:
        query = query.filter(
            or_(
                PedidoExport.nombre_cliente.ilike(f'%{buscar}%'),
                PedidoExport.orden_tn.ilike(f'%{buscar}%'),
                PedidoExport.id_pedido == int(buscar) if buscar.isdigit() else False
            )
        )
    
    # Ordenar por fecha_envio descendente
    query = query.order_by(PedidoExport.fecha_envio.desc().nullslast())
    
    # Ejecutar
    pedidos = query.offset(offset).limit(limit).all()
    
    # Transformar a response
    result = []
    for p in pedidos:
        # Obtener items del pedido
        items_query = db.query(PedidoExport.item_id, PedidoExport.cantidad).filter(
            PedidoExport.id_pedido == p.id_pedido
        ).all()
        
        items = [ItemPedido(item_id=i.item_id, cantidad=float(i.cantidad)) for i in items_query]
        
        result.append(PedidoResumen(
            id_pedido=p.id_pedido,
            id_cliente=p.id_cliente,
            nombre_cliente=p.nombre_cliente,
            tipo_envio=p.tipo_envio,
            direccion_envio=p.direccion_envio,
            fecha_envio=p.fecha_envio,
            observaciones=p.observaciones,
            orden_tn=p.orden_tn,
            order_id_tn=p.order_id_tn,
            total_items=p.total_items,
            items=items
        ))
    
    return result


@router.get("/pedidos-export-v2/estadisticas", response_model=EstadisticasPedidos)
async def obtener_estadisticas(
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """Estadísticas de pedidos activos"""
    
    total_pedidos = db.query(func.count(func.distinct(PedidoExport.id_pedido))).filter(
        PedidoExport.activo == True
    ).scalar() or 0
    
    total_items = db.query(func.count(PedidoExport.item_id)).filter(
        PedidoExport.activo == True
    ).scalar() or 0
    
    con_tiendanube = db.query(func.count(func.distinct(PedidoExport.id_pedido))).filter(
        and_(
            PedidoExport.activo == True,
            PedidoExport.order_id_tn.isnot(None)
        )
    ).scalar() or 0
    
    sin_direccion = db.query(func.count(func.distinct(PedidoExport.id_pedido))).filter(
        and_(
            PedidoExport.activo == True,
            PedidoExport.direccion_envio.is_(None)
        )
    ).scalar() or 0
    
    ultima_sync = db.query(func.max(PedidoExport.fecha_sync)).filter(
        PedidoExport.activo == True
    ).scalar()
    
    return EstadisticasPedidos(
        total_pedidos=total_pedidos,
        total_items=total_items,
        con_tiendanube=con_tiendanube,
        sin_direccion=sin_direccion,
        ultima_sync=ultima_sync
    )


@router.post("/pedidos-export-v2/sincronizar")
async def sincronizar_pedidos(
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """
    Sincroniza pedidos desde Export 87 del ERP.
    Llama al script de sincronización.
    """
    logger.info("🔄 Iniciando sincronización de pedidos...")
    
    try:
        # Llamar a gbp-parser para obtener datos del Export 87
        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.post(
                "http://localhost:8002/api/gbp-parser",
                json={"intExpgr_id": 87}
            )
            response.raise_for_status()
            data = response.json()
        
        if not data or not isinstance(data, list):
            raise HTTPException(500, "No se obtuvieron datos del Export 87")
        
        logger.info(f"✓ Obtenidos {len(data)} registros del ERP")
        
        # Procesar (mismo código que el script pero inline)
        pedidos_actuales = set()
        registros_unicos = {}
        
        for record in data:
            id_pedido = record.get('IDPedido')
            item_id = record.get('item_id')
            if id_pedido:
                pedidos_actuales.add(id_pedido)
            if id_pedido and item_id:
                key = (id_pedido, item_id)
                registros_unicos[key] = record
        
        # Archivar viejos
        archivados = db.query(PedidoExport).filter(
            and_(
                PedidoExport.activo == True,
                PedidoExport.id_pedido.notin_(pedidos_actuales)
            )
        ).update(
            {"activo": False},
            synchronize_session=False
        )
        
        # Procesar registros
        nuevos = 0
        actualizados = 0
        
        for record in registros_unicos.values():
            id_pedido = record.get('IDPedido')
            item_id = record.get('item_id')
            
            if not id_pedido or not item_id:
                continue
            
            pedido = db.query(PedidoExport).filter(
                and_(
                    PedidoExport.id_pedido == id_pedido,
                    PedidoExport.item_id == item_id
                )
            ).first()
            
            pedido_data = {
                'id_pedido': id_pedido,
                'item_id': item_id,
                'id_cliente': record.get('IDCliente'),
                'nombre_cliente': record.get('NombreCliente'),
                'cantidad': record.get('Cantidad'),
                'tipo_envio': record.get('Tipo de Envío'),
                'direccion_envio': record.get('Dirección de Envío'),
                'fecha_envio': record.get('Fecha de envío'),
                'observaciones': record.get('Observaciones'),
                'orden_tn': record.get('Orden TN'),
                'order_id_tn': str(record.get('orderID')) if record.get('orderID') else None,
                'activo': True,
                'fecha_sync': datetime.now()
            }
            
            if pedido:
                for key, value in pedido_data.items():
                    if key not in ['id_pedido', 'item_id']:
                        setattr(pedido, key, value)
                actualizados += 1
            else:
                pedido = PedidoExport(**pedido_data)
                db.add(pedido)
                nuevos += 1
        
        db.commit()
        
        logger.info(f"✅ Sincronización OK: {nuevos} nuevos, {actualizados} actualizados, {archivados} archivados")
        
        return {
            "mensaje": "Sincronización completada",
            "nuevos": nuevos,
            "actualizados": actualizados,
            "archivados": archivados,
            "registros_unicos": len(registros_unicos)
        }
        
    except httpx.HTTPError as e:
        logger.error(f"❌ Error llamando a gbp-parser: {e}")
        raise HTTPException(500, f"Error consultando ERP: {str(e)}")
    except Exception as e:
        logger.error(f"❌ Error en sincronización: {e}", exc_info=True)
        db.rollback()
        raise HTTPException(500, f"Error: {str(e)}")


@router.post("/pedidos-export-v2/enriquecer-tiendanube")
async def enriquecer_tiendanube(
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """
    Enriquece pedidos TN con datos de la API.
    TODO: Implementar cuando se necesite.
    """
    # Por ahora, solo retornar que está pendiente
    return {
        "mensaje": "Feature pendiente - enriquecimiento TN",
        "pedidos_tn": db.query(func.count(func.distinct(PedidoExport.id_pedido))).filter(
            and_(
                PedidoExport.activo == True,
                PedidoExport.order_id_tn.isnot(None)
            )
        ).scalar() or 0
    }
