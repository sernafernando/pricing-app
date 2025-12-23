"""
Endpoint SIMPLE usando SOLO tb_sale_order_header.
Sin quilombo de tablas intermedias.
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import func, and_, or_, text
from typing import List, Optional, Dict, Any
from datetime import datetime
from pydantic import BaseModel
import logging
import httpx

from app.core.database import get_db
from app.models.sale_order_header import SaleOrderHeader
from app.models.sale_order_detail import SaleOrderDetail
from app.models.tb_customer import TBCustomer
from app.models.tb_item import TBItem

router = APIRouter()
logger = logging.getLogger(__name__)


# Schemas
class ItemPedidoDetalle(BaseModel):
    """Item con descripción"""
    item_id: int
    cantidad: float
    item_desc: Optional[str] = None
    item_code: Optional[str] = None
    
    class Config:
        from_attributes = True


class PedidoDetallado(BaseModel):
    """Pedido con TODOS los datos desde tb_sale_order_header"""
    # IDs
    soh_id: int
    comp_id: int
    bra_id: int
    cust_id: Optional[int]
    user_id: Optional[int]
    
    # Cliente
    nombre_cliente: Optional[str]
    
    # Fechas
    soh_cd: Optional[datetime]  # Fecha creación
    soh_deliverydate: Optional[datetime]  # Fecha entrega
    
    # Direcciones y envío
    soh_deliveryaddress: Optional[str]
    soh_observation2: Optional[str]  # Tipo de envío
    
    # Observaciones
    soh_observation1: Optional[str]  # Observaciones
    soh_internalannotation: Optional[str]  # Orden TN / notas internas
    
    # TiendaNube
    ws_internalid: Optional[str]  # Order ID de TN
    tiendanube_number: Optional[str]  # NRO-XXXXX
    tiendanube_shipping_phone: Optional[str]
    tiendanube_shipping_address: Optional[str]
    tiendanube_shipping_city: Optional[str]
    tiendanube_shipping_province: Optional[str]
    tiendanube_shipping_zipcode: Optional[str]
    tiendanube_recipient_name: Optional[str]
    
    # MercadoLibre
    soh_mlid: Optional[str]
    mlshippingid: Optional[int]
    
    # Otros
    soh_packagesqty: Optional[int]  # Bultos
    soh_total: Optional[float]
    
    # Items
    total_items: int = 0
    items: List[ItemPedidoDetalle] = []
    
    class Config:
        from_attributes = True


class EstadisticasPedidos(BaseModel):
    total_pedidos: int
    total_items: int
    con_tiendanube: int
    con_mercadolibre: int
    sin_direccion: int
    ultima_sync: Optional[datetime]


@router.get("/pedidos-simple", response_model=List[PedidoDetallado])
async def obtener_pedidos(
    db: Session = Depends(get_db),
    solo_activos: bool = Query(True),
    solo_tn: bool = Query(False),
    solo_ml: bool = Query(False),
    user_id: Optional[int] = Query(None),
    buscar: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0)
):
    """
    Obtiene pedidos DIRECTAMENTE desde tb_sale_order_header.
    Filtra por export_id=80 y export_activo=true.
    """
    # Query base con JOIN para obtener nombre_cliente
    query = db.query(
        SaleOrderHeader,
        TBCustomer.cust_name.label('nombre_cliente')
    ).outerjoin(
        TBCustomer,
        and_(
            SaleOrderHeader.cust_id == TBCustomer.cust_id,
            SaleOrderHeader.comp_id == TBCustomer.comp_id
        )
    ).filter(
        SaleOrderHeader.export_id == 80
    )
    
    # Filtros
    if solo_activos:
        query = query.filter(SaleOrderHeader.export_activo == True)
    
    if solo_tn:
        query = query.filter(SaleOrderHeader.user_id == 50021)
    
    if solo_ml:
        query = query.filter(SaleOrderHeader.user_id == 50006)
    
    if user_id:
        query = query.filter(SaleOrderHeader.user_id == user_id)
    
    if buscar:
        query = query.filter(
            or_(
                SaleOrderHeader.soh_id == int(buscar) if buscar.isdigit() else False,
                SaleOrderHeader.tiendanube_number.ilike(f'%{buscar}%'),
                SaleOrderHeader.soh_internalannotation.ilike(f'%{buscar}%')
            )
        )
    
    # Ordenar y limitar
    query = query.order_by(SaleOrderHeader.soh_deliverydate.desc().nullslast())
    pedidos_db = query.offset(offset).limit(limit).all()
    
    # Transformar a response
    result = []
    for row in pedidos_db:
        pedido = row[0]  # SaleOrderHeader
        nombre_cliente = row[1] if len(row) > 1 else None  # cust_name
        # Obtener items del pedido con descripción y código
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
            SaleOrderDetail.soh_id == pedido.soh_id
        ).all()
        
        items = [
            ItemPedidoDetalle(
                item_id=i.item_id,
                cantidad=float(i.sod_qty) if i.sod_qty else 0,
                item_desc=i.item_desc,
                item_code=i.item_code
            ) for i in items_query
        ]
        
        result.append(PedidoDetallado(
            soh_id=pedido.soh_id,
            comp_id=pedido.comp_id,
            bra_id=pedido.bra_id,
            cust_id=pedido.cust_id,
            user_id=pedido.user_id,
            nombre_cliente=nombre_cliente,
            soh_cd=pedido.soh_cd,
            soh_deliverydate=pedido.soh_deliverydate,
            soh_deliveryaddress=pedido.soh_deliveryaddress,
            soh_observation2=pedido.soh_observation2,
            soh_observation1=pedido.soh_observation1,
            soh_internalannotation=pedido.soh_internalannotation,
            ws_internalid=pedido.ws_internalid,
            tiendanube_number=pedido.tiendanube_number,
            tiendanube_shipping_phone=pedido.tiendanube_shipping_phone,
            tiendanube_shipping_address=pedido.tiendanube_shipping_address,
            tiendanube_shipping_city=pedido.tiendanube_shipping_city,
            tiendanube_shipping_province=pedido.tiendanube_shipping_province,
            tiendanube_shipping_zipcode=pedido.tiendanube_shipping_zipcode,
            tiendanube_recipient_name=pedido.tiendanube_recipient_name,
            soh_mlid=pedido.soh_mlid,
            mlshippingid=pedido.mlshippingid,
            soh_packagesqty=pedido.soh_packagesqty,
            soh_total=float(pedido.soh_total) if pedido.soh_total else None,
            total_items=len(items),
            items=items
        ))
    
    return result


@router.get("/pedidos-simple/estadisticas", response_model=EstadisticasPedidos)
async def obtener_estadisticas(db: Session = Depends(get_db)):
    """Estadísticas de pedidos desde tb_sale_order_header"""
    
    base_query = db.query(SaleOrderHeader).filter(
        and_(
            SaleOrderHeader.export_id == 80,
            SaleOrderHeader.export_activo == True
        )
    )
    
    total_pedidos = base_query.count()
    
    # Total items (sumando desde sale_order_detail)
    total_items = db.query(func.count(SaleOrderDetail.item_id)).filter(
        SaleOrderDetail.soh_id.in_(
            db.query(SaleOrderHeader.soh_id).filter(
                and_(
                    SaleOrderHeader.export_id == 80,
                    SaleOrderHeader.export_activo == True
                )
            )
        )
    ).scalar() or 0
    
    con_tiendanube = base_query.filter(
        SaleOrderHeader.ws_internalid.isnot(None)
    ).count()
    
    con_mercadolibre = base_query.filter(
        SaleOrderHeader.soh_mlid.isnot(None)
    ).count()
    
    sin_direccion = base_query.filter(
        and_(
            SaleOrderHeader.soh_deliveryaddress.is_(None),
            SaleOrderHeader.tiendanube_shipping_address.is_(None)
        )
    ).count()
    
    ultima_sync = db.query(func.max(SaleOrderHeader.soh_lastupdate)).filter(
        and_(
            SaleOrderHeader.export_id == 80,
            SaleOrderHeader.export_activo == True
        )
    ).scalar()
    
    return EstadisticasPedidos(
        total_pedidos=total_pedidos,
        total_items=total_items,
        con_tiendanube=con_tiendanube,
        con_mercadolibre=con_mercadolibre,
        sin_direccion=sin_direccion,
        ultima_sync=ultima_sync
    )


@router.post("/pedidos-simple/sincronizar")
async def sincronizar_pedidos(db: Session = Depends(get_db)):
    """
    Sincroniza pedidos desde el Export 87 del ERP.
    Llama al endpoint existente que ya tiene toda la lógica.
    """
    logger.info("🔄 Iniciando sincronización desde Export 87...")
    
    try:
        # Llamar al endpoint existente de sincronización
        async with httpx.AsyncClient(timeout=300.0) as client:
            response = await client.post(
                "http://localhost:8002/api/pedidos-export/sincronizar-export-80"
            )
            response.raise_for_status()
            data = response.json()
        
        logger.info(f"✅ Sincronización completada: {data}")
        
        return {
            "mensaje": "Sincronización completada exitosamente",
            "registros_obtenidos": data.get("registros_obtenidos", 0),
            "detalle": data
        }
        
    except httpx.HTTPError as e:
        logger.error(f"❌ Error en sincronización: {e}")
        raise HTTPException(500, f"Error en sincronización: {str(e)}")
    except Exception as e:
        logger.error(f"❌ Error inesperado: {e}", exc_info=True)
        raise HTTPException(500, f"Error inesperado: {str(e)}")
