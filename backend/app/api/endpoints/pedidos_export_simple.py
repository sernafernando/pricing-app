"""
Endpoint SIMPLE usando SOLO tb_sale_order_header.
Sin quilombo de tablas intermedias.
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import func, and_, or_, text, case
from typing import List, Optional, Dict, Any
from datetime import datetime
from pydantic import BaseModel
import logging
import httpx
import os
from pathlib import Path
from fastapi.responses import Response

from app.core.database import get_db
from app.models.sale_order_header import SaleOrderHeader
from app.models.sale_order_detail import SaleOrderDetail
from app.models.tb_customer import TBCustomer
from app.models.tb_item import TBItem
from app.models.tb_user import TBUser

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
    
    # Usuario (canal de venta)
    user_name: Optional[str]
    
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
    
    # Override de dirección de envío (prioridad para visualización)
    override_shipping_address: Optional[str]
    override_shipping_city: Optional[str]
    override_shipping_province: Optional[str]
    override_shipping_zipcode: Optional[str]
    override_shipping_phone: Optional[str]
    override_shipping_recipient: Optional[str]
    override_notes: Optional[str]
    override_modified_at: Optional[datetime]
    
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
    solo_sin_direccion: bool = Query(False),
    user_id: Optional[int] = Query(None),
    provincia: Optional[str] = Query(None),
    cliente: Optional[str] = Query(None),
    buscar: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0)
):
    """
    Obtiene pedidos DIRECTAMENTE desde tb_sale_order_header.
    Filtra por export_id=80 y export_activo=true.
    """
    # Query base con JOINs para obtener nombre_cliente y user_name
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
    ).filter(
        SaleOrderHeader.export_id == 80
    )
    
    # Filtros
    if solo_activos:
        query = query.filter(SaleOrderHeader.export_activo == True)
    
    if solo_tn:
        # Filtrar por ws_internalid (cualquier pedido con Order ID de TN)
        # NO por user_id, porque puede haber pedidos de TN con otro user_id
        query = query.filter(SaleOrderHeader.ws_internalid.isnot(None))
    
    if solo_ml:
        # Filtrar por soh_mlid (cualquier pedido con ML ID)
        query = query.filter(SaleOrderHeader.soh_mlid.isnot(None))
    
    if user_id:
        query = query.filter(SaleOrderHeader.user_id == user_id)
    
    if solo_sin_direccion:
        # Filtrar pedidos SIN dirección en ninguna fuente
        query = query.filter(
            and_(
                # No tiene override
                or_(
                    SaleOrderHeader.override_shipping_address.is_(None),
                    SaleOrderHeader.override_shipping_address == ''
                ),
                # No tiene TN
                or_(
                    SaleOrderHeader.tiendanube_shipping_address.is_(None),
                    SaleOrderHeader.tiendanube_shipping_address == ''
                ),
                # No tiene ERP
                or_(
                    SaleOrderHeader.soh_deliveryaddress.is_(None),
                    SaleOrderHeader.soh_deliveryaddress == ''
                )
            )
        )
    
    if provincia:
        # Buscar en provincia de override, TN o ERP (en ese orden de prioridad)
        query = query.filter(
            or_(
                SaleOrderHeader.override_shipping_province.ilike(f'%{provincia}%'),
                SaleOrderHeader.tiendanube_shipping_province.ilike(f'%{provincia}%')
            )
        )
    
    if cliente:
        # Buscar por nombre de cliente
        query = query.filter(TBCustomer.cust_name.ilike(f'%{cliente}%'))
    
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
        user_name = row[2] if len(row) > 2 else None  # user_name
        # Obtener items del pedido con descripción y código
        # Para combos usar sod_item_id_origin, para items normales usar item_id
        # Excluir items 2953 y 2954 (descuentos/servicios de TiendaNube)
        
        # COALESCE: si item_id es NULL (combo), usar sod_item_id_origin
        item_id_efectivo = func.coalesce(SaleOrderDetail.item_id, SaleOrderDetail.sod_item_id_origin).label('item_id_efectivo')
        
        items_query = db.query(
            item_id_efectivo,
            SaleOrderDetail.sod_qty,
            TBItem.item_desc,
            TBItem.item_code
        ).outerjoin(
            TBItem,
            and_(
                func.coalesce(SaleOrderDetail.item_id, SaleOrderDetail.sod_item_id_origin) == TBItem.item_id,
                SaleOrderDetail.comp_id == TBItem.comp_id
            )
        ).filter(
            and_(
                SaleOrderDetail.soh_id == pedido.soh_id,
                func.coalesce(SaleOrderDetail.item_id, SaleOrderDetail.sod_item_id_origin).notin_([2953, 2954])  # Excluir descuentos
            )
        ).all()
        
        # Los resultados son tuplas: (item_id, sod_qty, item_desc, item_code)
        items = [
            ItemPedidoDetalle(
                item_id=row[0],  # item_id de la tupla
                cantidad=float(row[1]) if row[1] else 0,  # sod_qty
                item_desc=row[2],  # item_desc (puede ser None si no existe en tb_item)
                item_code=row[3]   # item_code (puede ser None si no existe en tb_item)
            ) for row in items_query if row[0] is not None  # Filtrar solo si item_id existe
        ]
        
        result.append(PedidoDetallado(
            soh_id=pedido.soh_id,
            comp_id=pedido.comp_id,
            bra_id=pedido.bra_id,
            cust_id=pedido.cust_id,
            user_id=pedido.user_id,
            nombre_cliente=nombre_cliente,
            user_name=user_name,
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
            override_shipping_address=pedido.override_shipping_address,
            override_shipping_city=pedido.override_shipping_city,
            override_shipping_province=pedido.override_shipping_province,
            override_shipping_zipcode=pedido.override_shipping_zipcode,
            override_shipping_phone=pedido.override_shipping_phone,
            override_shipping_recipient=pedido.override_shipping_recipient,
            override_notes=pedido.override_notes,
            override_modified_at=pedido.override_modified_at,
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
    
    # Sin dirección = NO tiene override NI TN NI ERP (o todas vacías)
    sin_direccion = base_query.filter(
        and_(
            # No tiene override
            or_(
                SaleOrderHeader.override_shipping_address.is_(None),
                SaleOrderHeader.override_shipping_address == ''
            ),
            # No tiene TN
            or_(
                SaleOrderHeader.tiendanube_shipping_address.is_(None),
                SaleOrderHeader.tiendanube_shipping_address == ''
            ),
            # No tiene ERP
            or_(
                SaleOrderHeader.soh_deliveryaddress.is_(None),
                SaleOrderHeader.soh_deliveryaddress == ''
            )
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


@router.get("/pedidos-simple/usuarios-disponibles")
async def obtener_usuarios_disponibles(db: Session = Depends(get_db)):
    """
    Obtiene la lista de usuarios (canales) que tienen pedidos activos.
    Retorna lista con user_id y user_name.
    """
    # Obtener user_ids distintos de pedidos activos
    usuarios = db.query(
        SaleOrderHeader.user_id,
        TBUser.user_name
    ).outerjoin(
        TBUser,
        SaleOrderHeader.user_id == TBUser.user_id
    ).filter(
        and_(
            SaleOrderHeader.export_id == 80,
            SaleOrderHeader.export_activo == True,
            SaleOrderHeader.user_id.isnot(None)
        )
    ).distinct().order_by(TBUser.user_name.asc().nullslast()).all()
    
    return [
        {
            "user_id": u.user_id,
            "user_name": u.user_name or f"User {u.user_id}"
        }
        for u in usuarios
    ]


@router.get("/pedidos-simple/provincias-disponibles")
async def obtener_provincias_disponibles(db: Session = Depends(get_db)):
    """
    Obtiene la lista de provincias únicas en pedidos activos.
    Prioriza override > TN > ERP.
    """
    # Usar COALESCE para obtener provincia con prioridad
    provincia_efectiva = func.coalesce(
        SaleOrderHeader.override_shipping_province,
        SaleOrderHeader.tiendanube_shipping_province
    ).label('provincia')
    
    provincias = db.query(provincia_efectiva).filter(
        and_(
            SaleOrderHeader.export_id == 80,
            SaleOrderHeader.export_activo == True,
            provincia_efectiva.isnot(None),
            provincia_efectiva != ''
        )
    ).distinct().order_by(provincia_efectiva.asc()).all()
    
    return [p[0] for p in provincias if p[0]]


class ShippingOverride(BaseModel):
    """Datos para sobrescribir dirección de envío"""
    direccion: str
    ciudad: Optional[str] = None
    provincia: Optional[str] = None
    codigo_postal: Optional[str] = None
    telefono: Optional[str] = None
    destinatario: Optional[str] = None
    notas: Optional[str] = None
    
    class Config:
        from_attributes = True


@router.put("/pedidos-simple/{soh_id}/override-shipping")
async def actualizar_direccion_envio(
    soh_id: int,
    override_data: ShippingOverride,
    db: Session = Depends(get_db)
):
    """
    Sobrescribe la dirección de envío de un pedido específico.
    Este override tiene prioridad para VISUALIZACIÓN, pero las etiquetas ZPL
    deben usar los datos reales de TN/ERP cuando estén disponibles.
    """
    # Buscar el pedido
    pedido = db.query(SaleOrderHeader).filter(
        SaleOrderHeader.soh_id == soh_id
    ).first()
    
    if not pedido:
        raise HTTPException(404, f"Pedido {soh_id} no encontrado")
    
    # Actualizar campos de override
    pedido.override_shipping_address = override_data.direccion
    pedido.override_shipping_city = override_data.ciudad
    pedido.override_shipping_province = override_data.provincia
    pedido.override_shipping_zipcode = override_data.codigo_postal
    pedido.override_shipping_phone = override_data.telefono
    pedido.override_shipping_recipient = override_data.destinatario
    pedido.override_notes = override_data.notas
    pedido.override_modified_at = datetime.now()
    # TODO: pedido.override_modified_by = current_user.user_id cuando tengamos auth
    
    db.commit()
    db.refresh(pedido)
    
    logger.info(f"✅ Override de dirección actualizado para pedido {soh_id}")
    
    return {
        "mensaje": "Dirección de envío actualizada exitosamente",
        "soh_id": soh_id,
        "override_modified_at": pedido.override_modified_at
    }


@router.delete("/pedidos-simple/{soh_id}/override-shipping")
async def eliminar_override_direccion(
    soh_id: int,
    db: Session = Depends(get_db)
):
    """
    Elimina el override de dirección de envío, volviendo a los datos originales.
    """
    pedido = db.query(SaleOrderHeader).filter(
        SaleOrderHeader.soh_id == soh_id
    ).first()
    
    if not pedido:
        raise HTTPException(404, f"Pedido {soh_id} no encontrado")
    
    # Limpiar campos de override
    pedido.override_shipping_address = None
    pedido.override_shipping_city = None
    pedido.override_shipping_province = None
    pedido.override_shipping_zipcode = None
    pedido.override_shipping_phone = None
    pedido.override_shipping_recipient = None
    pedido.override_notes = None
    pedido.override_modified_at = None
    pedido.override_modified_by = None
    
    db.commit()
    
    logger.info(f"🗑️ Override de dirección eliminado para pedido {soh_id}")
    
    return {
        "mensaje": "Override eliminado, usando datos originales",
        "soh_id": soh_id
    }


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


@router.get("/pedidos-simple/{soh_id}/etiqueta-zpl")
async def generar_etiqueta_zpl(
    soh_id: int,
    num_bultos: int = Query(1, ge=1, le=10),
    tipo_envio_manual: Optional[str] = Query(None),
    tipo_domicilio_manual: Optional[str] = Query(None),
    db: Session = Depends(get_db)
):
    """
    Genera etiquetas ZPL para impresión en Zebra.
    USA OVERRIDE si existe, luego TN, luego ERP.
    
    Parámetros:
    - soh_id: ID del pedido
    - num_bultos: Número de bultos (genera una etiqueta por bulto)
    - tipo_envio_manual: Override manual del tipo de envío (opcional)
    - tipo_domicilio_manual: Override manual del tipo de domicilio (opcional)
    """
    # Buscar pedido con items
    pedido = db.query(SaleOrderHeader).filter(
        SaleOrderHeader.soh_id == soh_id
    ).first()
    
    if not pedido:
        raise HTTPException(404, f"Pedido {soh_id} no encontrado")
    
    # Obtener items (excluyendo 2953 y 2954)
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
            func.coalesce(SaleOrderDetail.item_id, SaleOrderDetail.sod_item_id_origin).notin_([2953, 2954])
        )
    ).all()
    
    # Calcular cantidad total y concatenar SKUs
    cantidad_total = sum(float(i.sod_qty) if i.sod_qty else 0 for i in items_query)
    skus_concatenados = ' - '.join([i.item_code for i in items_query if i.item_code]) or 'N/A'
    
    # PRIORIDAD: override > TN > ERP
    direccion = pedido.override_shipping_address or pedido.tiendanube_shipping_address or pedido.soh_deliveryaddress or 'N/A'
    ciudad = pedido.override_shipping_city or pedido.tiendanube_shipping_city or 'N/A'
    provincia = pedido.override_shipping_province or pedido.tiendanube_shipping_province or 'N/A'
    codigo_postal = pedido.override_shipping_zipcode or pedido.tiendanube_shipping_zipcode or 'N/A'
    telefono = pedido.override_shipping_phone or pedido.tiendanube_shipping_phone or 'N/A'
    destinatario = pedido.override_shipping_recipient or pedido.tiendanube_recipient_name or 'N/A'
    
    # Tipo de envío
    tipo_envio = tipo_envio_manual
    if not tipo_envio:
        raw_tipo_envio = pedido.soh_observation2  # Tipo de envío del ERP
        tipo_envio = str(raw_tipo_envio).replace('_x0020_', ' ').strip() if raw_tipo_envio else 'N/A'
    
    # Tipo de domicilio
    tipo_domicilio = tipo_domicilio_manual
    if not tipo_domicilio:
        tipo_envio_lower = tipo_envio.lower()
        if "domicilio" in tipo_envio_lower:
            tipo_domicilio = "Domicilio"
        elif "sucursal" in tipo_envio_lower:
            tipo_domicilio = "Sucursal"
        else:
            tipo_domicilio = "N/A"
    
    # Leer template ZPL
    template_path = Path(__file__).parent.parent.parent.parent / "templates" / "etiqueta.zpl"
    
    try:
        with open(template_path, 'r', encoding='utf-8') as f:
            zpl_template = f.read()
    except FileNotFoundError:
        logger.error(f"Template ZPL no encontrado en: {template_path}")
        raise HTTPException(500, "Template de etiqueta no encontrado")
    
    # Contexto para template
    context = {
        'CANTIDAD_ITEMS_PEDIDO': str(int(cantidad_total)),
        'SKUS_CONCATENADOS': skus_concatenados[:50],  # Limitar longitud
        'ID_PEDIDO': str(pedido.soh_id),
        'ORDEN_TN': pedido.tiendanube_number or pedido.ws_internalid or 'N/A',
        'TIPO_ENVIO_ETIQUETA': tipo_envio,
        'NOMBRE_DESTINATARIO': destinatario,
        'TELEFONO_DESTINATARIO': telefono,
        'DIRECCION_CALLE': direccion,
        'OBSERVACIONES': pedido.soh_observation1 or pedido.override_notes or 'N/A',
        'CODIGO_POSTAL': codigo_postal,
        'BARRIO': ciudad,
        'TIPO_DOMICILIO': tipo_domicilio,
        'TOTAL_BULTOS': str(num_bultos)
    }
    
    # Generar etiquetas (una por bulto)
    zpl_labels = []
    for i in range(1, num_bultos + 1):
        label_context = context.copy()
        label_context['BULTO_ACTUAL'] = str(i)
        
        # Reemplazar variables en template
        rendered_zpl = zpl_template
        for key, value in label_context.items():
            rendered_zpl = rendered_zpl.replace(f'{{{{{key}}}}}', str(value))
        
        zpl_labels.append(rendered_zpl)
    
    # Unir todas las etiquetas
    full_zpl = "\n".join(zpl_labels)
    
    logger.info(f"✅ Generadas {num_bultos} etiquetas ZPL para pedido {soh_id}")
    
    # Retornar como archivo de texto
    return Response(
        content=full_zpl,
        media_type="text/plain",
        headers={
            "Content-Disposition": f"attachment; filename=etiqueta_pedido_{soh_id}.txt"
        }
    )
