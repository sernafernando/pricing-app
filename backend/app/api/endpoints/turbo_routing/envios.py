"""
Endpoints de envíos Turbo pendientes y vista administrativa.
"""

import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional

import pytz
from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy.orm import Session

from app.core.database import get_db, get_async_db
from app.api.deps import get_current_user
from app.models.asignacion_turbo import AsignacionTurbo
from app.models.geocoding_cache import GeocodingCache
from app.models.mercadolibre_order_shipping import MercadoLibreOrderShipping
from app.models.envio_turbo_banlist import EnvioTurboBanlist
from app.services.permisos_service import verificar_permiso
from app.services.ml_webhook_service import fetch_shipment_data

from ._shared import (
    EnvioTurboResponse,
    convert_to_argentina_tz,
)

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/turbo/envios/pendientes", response_model=List[EnvioTurboResponse])
def obtener_envios_turbo_pendientes(
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
    incluir_asignados: bool = Query(False, description="Incluir envíos ya asignados"),
    limit: int = Query(200, ge=1, le=500),
    offset: int = Query(0, ge=0),
    dias_atras: int = Query(7, ge=1, le=90, description="Días hacia atrás para consultar scriptEnvios"),
):
    """
    Obtiene envíos Turbo pendientes ACTUALIZADOS desde scriptEnvios del ERP.

    Proceso:
    1. Obtiene todos los envíos Turbo (mlshipping_method_id = 515282) de la BD
    2. Cruza con scriptEnvios para actualizar estado y dirección real
    3. Filtra solo los que estén realmente pendientes (ready_to_ship, not_delivered)

    Esto garantiza direcciones completas y estados actualizados.
    """
    # Verificar permiso
    if not verificar_permiso(db, current_user, "ordenes.gestionar_turbo_routing"):
        raise HTTPException(status_code=403, detail="Sin permiso para gestionar Turbo Routing")

    # 1. Obtener SOLO envíos Turbo pendientes desde BD (filtro directo en query)
    # Filtrar por fecha: solo últimos dias_atras días O envíos TEST
    fecha_desde = datetime.now(pytz.timezone("America/Argentina/Buenos_Aires")) - timedelta(days=dias_atras)

    # Obtener IDs de envíos baneados para excluirlos
    banned_ids_query = db.query(EnvioTurboBanlist.mlshippingid).all()
    banned_ids_set = {str(row[0]) for row in banned_ids_query}

    # Construir filtros base
    filtros_base = [
        MercadoLibreOrderShipping.mlshipping_method_id == "515282",
        # Solo envíos recientes O envíos TEST
        (MercadoLibreOrderShipping.mlestimated_delivery_limit >= fecha_desde)
        | (MercadoLibreOrderShipping.mlshippingid.like("TEST_%")),
        # Excluir envíos baneados (banlist)
        ~MercadoLibreOrderShipping.mlshippingid.in_(banned_ids_set) if banned_ids_set else True,
    ]

    # FILTRO CONDICIONAL DE ESTADO:
    # - Si NO incluye asignados: solo estados pendientes (ready_to_ship, not_delivered)
    # - Si incluye asignados: todos los estados (para seguimiento en tiempo real)
    if not incluir_asignados:
        filtros_base.append(MercadoLibreOrderShipping.mlstatus.in_(["ready_to_ship", "not_delivered"]))

    turbo_query = (
        db.query(
            MercadoLibreOrderShipping.mlshippingid,
            MercadoLibreOrderShipping.mlo_id,
            MercadoLibreOrderShipping.mlstreet_name,
            MercadoLibreOrderShipping.mlstreet_number,
            MercadoLibreOrderShipping.mlzip_code,
            MercadoLibreOrderShipping.mlcity_name,
            MercadoLibreOrderShipping.mlstate_name,
            MercadoLibreOrderShipping.mlreceiver_name,
            MercadoLibreOrderShipping.mlreceiver_phone,
            MercadoLibreOrderShipping.mlestimated_delivery_limit,
            MercadoLibreOrderShipping.mllogistic_type,
            MercadoLibreOrderShipping.mlshipping_mode,
            MercadoLibreOrderShipping.mlturbo,
            MercadoLibreOrderShipping.mlself_service,
            MercadoLibreOrderShipping.mlcross_docking,
            MercadoLibreOrderShipping.mlstatus,
        )
        .filter(*filtros_base)
        .all()
    )

    # 2. Crear lista de envíos pendientes
    envios_turbo_actualizados = []
    for row in turbo_query:
        envios_turbo_actualizados.append(
            {
                "envio_bd": row,
                "envio_erp": None,  # Ya no necesitamos datos del ERP
                "estado_real": row.mlstatus,  # Estado actualizado desde ML Webhook
            }
        )

    # 6. Filtrar asignados si corresponde (query optimizada)
    if not incluir_asignados:
        asignados_ids_query = db.query(AsignacionTurbo.mlshippingid).filter(AsignacionTurbo.estado != "cancelado").all()
        asignados_ids_set = {str(a[0]) for a in asignados_ids_query}

        # Filtrado usando set comprehension (más rápido)
        envios_turbo_actualizados = [
            e for e in envios_turbo_actualizados if str(e["envio_bd"].mlshippingid) not in asignados_ids_set
        ]

    # 7. Obtener asignaciones existentes (solo si incluye asignados)
    asignaciones_map = {}
    if incluir_asignados and envios_turbo_actualizados:
        shipment_ids = [str(e["envio_bd"].mlshippingid) for e in envios_turbo_actualizados]
        asignaciones = db.query(AsignacionTurbo).filter(AsignacionTurbo.mlshippingid.in_(shipment_ids)).all()
        asignaciones_map = {str(asig.mlshippingid): asig for asig in asignaciones}

    # 8. Construir respuesta con paginación
    envios_paginados = envios_turbo_actualizados[offset : offset + limit]

    # Pre-compute geocoding hashes and batch-fetch from cache (1 query instead of N)
    hash_to_item_idx: Dict[str, List[int]] = {}
    item_hashes: List[str] = []
    for idx, item in enumerate(envios_paginados):
        envio_bd = item["envio_bd"]
        direccion_normalizada = f"{envio_bd.mlstreet_name} {envio_bd.mlstreet_number}, {envio_bd.mlcity_name}".strip()
        h = GeocodingCache.hash_direccion(direccion_normalizada)
        item_hashes.append(h)
        hash_to_item_idx.setdefault(h, []).append(idx)

    unique_hashes = list(hash_to_item_idx.keys())
    geocoding_map: Dict[str, GeocodingCache] = {}
    if unique_hashes:
        cache_rows = db.query(GeocodingCache).filter(GeocodingCache.direccion_hash.in_(unique_hashes)).all()
        geocoding_map = {row.direccion_hash: row for row in cache_rows}

    resultado = []
    for idx, item in enumerate(envios_paginados):
        envio_bd = item["envio_bd"]
        envio_erp = item["envio_erp"]
        estado_real = item["estado_real"]

        shipment_id = str(envio_bd.mlshippingid)
        asignacion = asignaciones_map.get(shipment_id)

        # Usar dirección del ERP si existe, sino de la BD
        if envio_erp:
            direccion_completa = envio_erp.get("Dirección de Entrega", "Dirección no disponible")
        else:
            # Fallback: construir desde BD
            direccion_completa = f"{envio_bd.mlstreet_name} {envio_bd.mlstreet_number}, {envio_bd.mlcity_name}".strip()

        # Obtener coordenadas desde batch pre-fetched geocoding_cache
        latitud = None
        longitud = None
        cache = geocoding_map.get(item_hashes[idx])
        if cache and cache.latitud and cache.longitud:
            latitud = float(cache.latitud)
            longitud = float(cache.longitud)

        resultado.append(
            EnvioTurboResponse(
                mlshippingid=shipment_id,
                mlo_id=envio_bd.mlo_id,
                direccion_completa=direccion_completa,
                mlstreet_name=envio_bd.mlstreet_name,
                mlstreet_number=envio_bd.mlstreet_number,
                mlzip_code=envio_bd.mlzip_code,
                mlcity_name=envio_bd.mlcity_name,
                mlstate_name=envio_bd.mlstate_name,
                mlreceiver_name=envio_bd.mlreceiver_name,
                mlreceiver_phone=envio_bd.mlreceiver_phone,
                mlestimated_delivery_limit=convert_to_argentina_tz(envio_bd.mlestimated_delivery_limit),
                mlstatus=estado_real,  # ESTADO REAL desde scriptEnvios
                mllogistic_type=envio_bd.mllogistic_type,
                mlshipping_mode=envio_bd.mlshipping_mode,
                mlturbo=envio_bd.mlturbo,
                mlself_service=envio_bd.mlself_service,
                mlcross_docking=envio_bd.mlcross_docking,
                tipo_envio="turbo",
                asignado=asignacion is not None,
                motoquero_id=asignacion.motoquero_id if asignacion else None,
                motoquero_nombre=asignacion.motoquero.nombre if asignacion and asignacion.motoquero else None,
                latitud=latitud,
                longitud=longitud,
            )
        )

    return resultado


@router.get("/turbo/envios/todos")
def obtener_todos_los_envios_turbo(
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
    estado: Optional[str] = Query(None, description="Filtrar por estado (ready_to_ship, delivered, etc.)"),
    search: str = Query("", description="Buscar por ID, destinatario, dirección"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    fecha_desde: Optional[str] = Query(None, description="Fecha desde (YYYY-MM-DD)"),
    fecha_hasta: Optional[str] = Query(None, description="Fecha hasta (YYYY-MM-DD)"),
):
    """
    Vista administrativa: obtiene TODOS los envíos Turbo sin filtro por estado.

    Uso: Para buscar envíos históricos, verificar estados, auditoría.

    Características:
    - NO actualiza estados automáticamente (solo consulta BD)
    - Permite filtrar por estado, fecha, búsqueda
    - Paginación para performance
    - Estados se actualizan solo al abrir detalle del envío
    """
    if not verificar_permiso(db, current_user, "ordenes.gestionar_turbo_routing"):
        raise HTTPException(status_code=403, detail="Sin permiso para gestionar Turbo Routing")

    # Query base
    query = db.query(
        MercadoLibreOrderShipping.mlshippingid,
        MercadoLibreOrderShipping.mlo_id,
        MercadoLibreOrderShipping.mlstreet_name,
        MercadoLibreOrderShipping.mlstreet_number,
        MercadoLibreOrderShipping.mlzip_code,
        MercadoLibreOrderShipping.mlcity_name,
        MercadoLibreOrderShipping.mlstate_name,
        MercadoLibreOrderShipping.mlreceiver_name,
        MercadoLibreOrderShipping.mlreceiver_phone,
        MercadoLibreOrderShipping.mlestimated_delivery_limit,
        MercadoLibreOrderShipping.mllogistic_type,
        MercadoLibreOrderShipping.mlshipping_mode,
        MercadoLibreOrderShipping.mlstatus,
        MercadoLibreOrderShipping.mlturbo,
        MercadoLibreOrderShipping.mlself_service,
        MercadoLibreOrderShipping.mlcross_docking,
    ).filter(MercadoLibreOrderShipping.mlshipping_method_id == "515282")

    # Filtro por estado
    if estado:
        query = query.filter(MercadoLibreOrderShipping.mlstatus == estado)

    # Filtro por búsqueda
    if search:
        query = query.filter(
            (MercadoLibreOrderShipping.mlshippingid.ilike(f"%{search}%"))
            | (MercadoLibreOrderShipping.mlreceiver_name.ilike(f"%{search}%"))
            | (MercadoLibreOrderShipping.mlstreet_name.ilike(f"%{search}%"))
        )

    # Filtro por fecha
    if fecha_desde:
        query = query.filter(MercadoLibreOrderShipping.mlestimated_delivery_limit >= fecha_desde)
    if fecha_hasta:
        query = query.filter(MercadoLibreOrderShipping.mlestimated_delivery_limit <= fecha_hasta)

    # Ordenar por fecha descendente
    query = query.order_by(MercadoLibreOrderShipping.mlestimated_delivery_limit.desc())

    # Contar total
    total = query.count()

    # Paginación
    envios = query.offset(offset).limit(limit).all()

    # Verificar si tiene asignación
    envios_ids = [str(e.mlshippingid) for e in envios]
    asignaciones_map = {}
    if envios_ids:
        asignaciones = db.query(AsignacionTurbo).filter(AsignacionTurbo.mlshippingid.in_(envios_ids)).all()
        asignaciones_map = {str(a.mlshippingid): a for a in asignaciones}

    # Batch-fetch geocoding cache for all envíos in page (1 query instead of N)
    todos_hashes: List[str] = []
    for envio in envios:
        direccion = f"{envio.mlstreet_name} {envio.mlstreet_number}, {envio.mlcity_name}".strip()
        todos_hashes.append(GeocodingCache.hash_direccion(direccion))

    unique_todos_hashes = list(set(todos_hashes))
    geo_map_todos: Dict[str, GeocodingCache] = {}
    if unique_todos_hashes:
        cache_rows = db.query(GeocodingCache).filter(GeocodingCache.direccion_hash.in_(unique_todos_hashes)).all()
        geo_map_todos = {row.direccion_hash: row for row in cache_rows}

    # Construir respuesta
    resultado = []
    for idx, envio in enumerate(envios):
        shipment_id = str(envio.mlshippingid)
        asignacion = asignaciones_map.get(shipment_id)

        # Construir dirección
        direccion = f"{envio.mlstreet_name} {envio.mlstreet_number}, {envio.mlcity_name}".strip()

        # Obtener coordenadas desde pre-fetched cache
        latitud = None
        longitud = None
        cache = geo_map_todos.get(todos_hashes[idx])
        if cache and cache.latitud and cache.longitud:
            latitud = float(cache.latitud)
            longitud = float(cache.longitud)

        resultado.append(
            EnvioTurboResponse(
                mlshippingid=shipment_id,
                mlo_id=envio.mlo_id,
                direccion_completa=direccion,
                mlstreet_name=envio.mlstreet_name,
                mlstreet_number=envio.mlstreet_number,
                mlzip_code=envio.mlzip_code,
                mlcity_name=envio.mlcity_name,
                mlstate_name=envio.mlstate_name,
                mlreceiver_name=envio.mlreceiver_name,
                mlreceiver_phone=envio.mlreceiver_phone,
                fecha_estimada_entrega=convert_to_argentina_tz(envio.mlestimated_delivery_limit)
                if envio.mlestimated_delivery_limit
                else None,
                mllogistic_type=envio.mllogistic_type,
                mlshipping_mode=envio.mlshipping_mode,
                estado=envio.mlstatus or "unknown",
                latitud=latitud,
                longitud=longitud,
                asignado_a=asignacion.motoquero.nombre if asignacion and asignacion.motoquero else None,
                asignado_a_id=asignacion.motoquero_id if asignacion else None,
                zona_nombre=asignacion.zona.nombre if asignacion and asignacion.zona else None,
                zona_id=asignacion.zona_id if asignacion else None,
            )
        )

    return {"total": total, "envios": resultado, "page": offset // limit + 1, "page_size": limit}


@router.get("/turbo/envios/{shipping_id}/detalle")
async def obtener_detalle_envio_actualizado(
    shipping_id: str, db: Session = Depends(get_async_db), current_user: dict = Depends(get_current_user)
):
    """
    Obtiene detalle de un envío específico y ACTUALIZA su estado desde ML Webhook.

    Usado en modal de detalle para tener info 100% actualizada sin sobrecargar batch.
    """
    if not verificar_permiso(db, current_user, "ordenes.gestionar_turbo_routing"):
        raise HTTPException(status_code=403, detail="Sin permiso para gestionar Turbo Routing")

    # Obtener envío de BD
    envio = db.query(MercadoLibreOrderShipping).filter(MercadoLibreOrderShipping.mlshippingid == shipping_id).first()

    if not envio:
        raise HTTPException(status_code=404, detail="Envío no encontrado")

    # Actualizar estado desde ML Webhook (solo si NO es TEST)
    ml_data = None
    if not shipping_id.startswith("TEST_"):
        try:
            ml_data = await fetch_shipment_data(shipping_id)
            if ml_data:
                nuevo_estado = ml_data.get("status", "").lower()
                if nuevo_estado and envio.mlstatus != nuevo_estado:
                    envio.mlstatus = nuevo_estado
                    db.commit()
                    logger.info(f"Estado actualizado para {shipping_id}: {nuevo_estado}")
        except Exception as e:
            logger.error(f"Error actualizando estado de {shipping_id}: {e}")

    # Obtener asignación si existe
    asignacion = db.query(AsignacionTurbo).filter(AsignacionTurbo.mlshippingid == shipping_id).first()

    # Construir dirección
    direccion = f"{envio.mlstreet_name} {envio.mlstreet_number}, {envio.mlcity_name}".strip()

    # Obtener coordenadas
    latitud = None
    longitud = None
    direccion_hash = GeocodingCache.hash_direccion(direccion)
    cache = db.query(GeocodingCache).filter(GeocodingCache.direccion_hash == direccion_hash).first()

    if cache and cache.latitud and cache.longitud:
        latitud = float(cache.latitud)
        longitud = float(cache.longitud)

    return {
        "mlshippingid": str(envio.mlshippingid),
        "mlo_id": envio.mlo_id,
        "direccion_completa": direccion,
        "mlstreet_name": envio.mlstreet_name,
        "mlstreet_number": envio.mlstreet_number,
        "mlzip_code": envio.mlzip_code,
        "mlcity_name": envio.mlcity_name,
        "mlstate_name": envio.mlstate_name,
        "mlreceiver_name": envio.mlreceiver_name,
        "mlreceiver_phone": envio.mlreceiver_phone,
        "fecha_estimada_entrega": convert_to_argentina_tz(envio.mlestimated_delivery_limit)
        if envio.mlestimated_delivery_limit
        else None,
        "mllogistic_type": envio.mllogistic_type,
        "mlshipping_mode": envio.mlshipping_mode,
        "estado": envio.mlstatus or "unknown",
        "latitud": latitud,
        "longitud": longitud,
        "asignado_a": asignacion.motoquero.nombre if asignacion and asignacion.motoquero else None,
        "asignado_a_id": asignacion.motoquero_id if asignacion else None,
        "zona_nombre": asignacion.zona.nombre if asignacion and asignacion.zona else None,
        "zona_id": asignacion.zona_id if asignacion else None,
        "ml_data": ml_data,  # Datos raw de ML para debugging
    }
