"""
Endpoints de asignaciones manuales, automáticas y seguimiento diario.
"""

import logging
from datetime import datetime
from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.api.deps import get_current_user
from app.models.motoquero import Motoquero
from app.models.zona_reparto import ZonaReparto
from app.models.asignacion_turbo import AsignacionTurbo
from app.models.geocoding_cache import GeocodingCache
from app.models.mercadolibre_order_shipping import MercadoLibreOrderShipping
from app.services.permisos_service import verificar_permiso
from app.services.auto_assignment_service import asignar_envios_automaticamente

from ._shared import (
    ARGENTINA_TZ,
    AsignacionRequest,
    AsignacionResponse,
    EnvioPorMotoqueroStat,
    convert_to_argentina_tz,
)

router = APIRouter()
logger = logging.getLogger(__name__)


@router.post("/turbo/asignacion/manual", response_model=List[AsignacionResponse])
def asignar_envios_manual(
    asignacion: AsignacionRequest, db: Session = Depends(get_db), current_user: dict = Depends(get_current_user)
):
    """
    Asigna envíos Turbo a un motoquero manualmente.
    """
    if not verificar_permiso(db, current_user, "ordenes.gestionar_turbo_routing"):
        raise HTTPException(status_code=403, detail="Sin permiso")

    # Validar que el motoquero existe
    motoquero = db.query(Motoquero).filter(Motoquero.id == asignacion.motoquero_id).first()
    if not motoquero:
        raise HTTPException(status_code=404, detail="Motoquero no encontrado")

    # Validar zona si se especificó
    if asignacion.zona_id:
        zona = db.query(ZonaReparto).filter(ZonaReparto.id == asignacion.zona_id).first()
        if not zona:
            raise HTTPException(status_code=404, detail="Zona no encontrada")

    asignaciones_creadas = []

    for mlshippingid in asignacion.mlshippingids:
        # Obtener datos del envío
        envio = (
            db.query(MercadoLibreOrderShipping).filter(MercadoLibreOrderShipping.mlshippingid == mlshippingid).first()
        )

        if not envio:
            continue  # Skip si no existe

        # Verificar si ya está asignado
        asignacion_existente = (
            db.query(AsignacionTurbo)
            .filter(AsignacionTurbo.mlshippingid == mlshippingid, AsignacionTurbo.estado != "cancelado")
            .first()
        )

        if asignacion_existente:
            # Reasignar
            asignacion_existente.motoquero_id = asignacion.motoquero_id
            asignacion_existente.zona_id = asignacion.zona_id
            asignacion_existente.asignado_por = asignacion.asignado_por
            asignacion_existente.asignado_at = datetime.now(ARGENTINA_TZ)
            db_asignacion = asignacion_existente
        else:
            # Crear nueva asignación
            # Construir dirección
            direccion_partes = []
            if envio.mlstreet_name:
                direccion_partes.append(envio.mlstreet_name)
            if envio.mlstreet_number:
                direccion_partes.append(envio.mlstreet_number)
            if envio.mlcity_name:
                direccion_partes.append(envio.mlcity_name)
            direccion = ", ".join(direccion_partes) or envio.mlreceiver_address or "Dirección no disponible"

            db_asignacion = AsignacionTurbo(
                mlshippingid=mlshippingid,
                motoquero_id=asignacion.motoquero_id,
                zona_id=asignacion.zona_id,
                direccion=direccion[:500],  # Truncar a 500 chars
                estado="pendiente",
                asignado_por=asignacion.asignado_por,
            )
            db.add(db_asignacion)

        asignaciones_creadas.append(db_asignacion)

    db.commit()

    # Refrescar para obtener IDs
    for a in asignaciones_creadas:
        db.refresh(a)

    return asignaciones_creadas


@router.get("/turbo/asignaciones/resumen", response_model=List[EnvioPorMotoqueroStat])
def obtener_resumen_asignaciones(db: Session = Depends(get_db), current_user: dict = Depends(get_current_user)):
    """
    Obtiene resumen de asignaciones agrupadas por motoquero.
    """
    if not verificar_permiso(db, current_user, "ordenes.gestionar_turbo_routing"):
        raise HTTPException(status_code=403, detail="Sin permiso")

    # Query agrupada
    resumen = (
        db.query(
            Motoquero.id,
            Motoquero.nombre,
            func.count(AsignacionTurbo.id).label("total_envios"),
            func.max(AsignacionTurbo.asignado_at).label("ultima_asignacion"),
        )
        .join(AsignacionTurbo, AsignacionTurbo.motoquero_id == Motoquero.id)
        .filter(Motoquero.activo.is_(True), AsignacionTurbo.estado != "cancelado")
        .group_by(Motoquero.id, Motoquero.nombre)
        .all()
    )

    return [
        EnvioPorMotoqueroStat(
            motoquero_id=r.id, nombre=r.nombre, total_envios=r.total_envios, ultima_asignacion=r.ultima_asignacion
        )
        for r in resumen
    ]


@router.post("/turbo/asignar-automatico")
def asignar_automaticamente_por_zona(db: Session = Depends(get_db), current_user: dict = Depends(get_current_user)):
    """
    Asigna automáticamente envíos pendientes a motoqueros según su zona.

    Proceso:
    1. Obtiene envíos Turbo pendientes con coordenadas
    2. Obtiene zonas activas con motoqueros asignados
    3. Usa point-in-polygon para determinar qué zona contiene cada envío
    4. Crea asignaciones automáticas en la BD
    5. Retorna resumen de asignaciones creadas
    """
    if not verificar_permiso(db, current_user, "ordenes.gestionar_turbo_routing"):
        raise HTTPException(status_code=403, detail="Sin permiso para gestionar Turbo Routing")

    # 1. Obtener envíos pendientes con coordenadas (sin asignar)
    envios_sin_asignar = (
        db.query(
            MercadoLibreOrderShipping.mlshippingid,
            MercadoLibreOrderShipping.mlstreet_name,
            MercadoLibreOrderShipping.mlstreet_number,
            MercadoLibreOrderShipping.mlcity_name,
            MercadoLibreOrderShipping.mlstatus,
        )
        .filter(
            MercadoLibreOrderShipping.mlshipping_method_id == "515282",
            MercadoLibreOrderShipping.mlstatus.in_(["ready_to_ship", "not_delivered"]),
            ~MercadoLibreOrderShipping.mlshippingid.in_(
                db.query(AsignacionTurbo.mlshippingid).filter(AsignacionTurbo.estado != "cancelado")
            ),
        )
        .all()
    )

    if not envios_sin_asignar:
        return {
            "total_procesados": 0,
            "total_asignados": 0,
            "total_sin_zona": 0,
            "asignaciones": [],
            "sin_zona": [],
            "mensaje": "No hay envíos pendientes sin asignar",
        }

    # 2. Obtener coordenadas desde geocoding_cache — batch lookup (1 query)
    envio_hashes_auto = []
    for envio in envios_sin_asignar:
        direccion = f"{envio.mlstreet_name} {envio.mlstreet_number}, {envio.mlcity_name}".strip()
        envio_hashes_auto.append(GeocodingCache.hash_direccion(direccion))

    unique_hashes_auto = list(set(envio_hashes_auto))
    geo_map_auto: Dict[str, GeocodingCache] = {}
    if unique_hashes_auto:
        cache_rows = db.query(GeocodingCache).filter(GeocodingCache.direccion_hash.in_(unique_hashes_auto)).all()
        geo_map_auto = {row.direccion_hash: row for row in cache_rows}

    envios_coords = []
    for envio, h in zip(envios_sin_asignar, envio_hashes_auto):
        cache = geo_map_auto.get(h)
        if cache and cache.latitud and cache.longitud:
            envios_coords.append((str(envio.mlshippingid), float(cache.latitud), float(cache.longitud)))

    if not envios_coords:
        return {
            "total_procesados": len(envios_sin_asignar),
            "total_asignados": 0,
            "total_sin_zona": len(envios_sin_asignar),
            "asignaciones": [],
            "sin_zona": [str(e.mlshippingid) for e in envios_sin_asignar],
            "mensaje": "Ningún envío tiene coordenadas. Ejecutá geocoding batch primero.",
        }

    # 3. Obtener zonas activas con motoqueros asignados
    zonas_query = (
        db.query(ZonaReparto.id, ZonaReparto.nombre, ZonaReparto.poligono).filter(ZonaReparto.activa.is_(True)).all()
    )

    if not zonas_query:
        return {
            "total_procesados": len(envios_coords),
            "total_asignados": 0,
            "total_sin_zona": len(envios_coords),
            "asignaciones": [],
            "sin_zona": [e[0] for e in envios_coords],
            "mensaje": "No hay zonas activas. Creá zonas primero.",
        }

    # Obtener motoqueros por zona (asignación manual previa o configuración)
    # Por ahora, asignamos 1 motoquero activo por zona de forma round-robin
    motoqueros_activos = db.query(Motoquero).filter(Motoquero.activo.is_(True)).order_by(Motoquero.id).all()

    if not motoqueros_activos:
        return {
            "total_procesados": len(envios_coords),
            "total_asignados": 0,
            "total_sin_zona": len(envios_coords),
            "asignaciones": [],
            "sin_zona": [e[0] for e in envios_coords],
            "mensaje": "No hay motoqueros activos. Creá motoqueros primero.",
        }

    # Mapear zona -> motoquero (round-robin)
    zonas_motoqueros = []
    for i, zona in enumerate(zonas_query):
        motoquero = motoqueros_activos[i % len(motoqueros_activos)]
        zonas_motoqueros.append(
            {
                "id": zona.id,
                "nombre": zona.nombre,
                "poligono": zona.poligono,
                "motoquero_id": motoquero.id,
                "motoquero_nombre": motoquero.nombre,
            }
        )

    # 4. Asignar usando point-in-polygon
    resultado = asignar_envios_automaticamente(envios_coords, zonas_motoqueros)

    # 5. Crear asignaciones en BD — batch fetch envíos + geocoding
    asig_shipment_ids = [a["mlshippingid"] for a in resultado["asignaciones"]]

    # Batch fetch envíos (1 query instead of N)
    envios_para_asignar = (
        (
            db.query(MercadoLibreOrderShipping)
            .filter(MercadoLibreOrderShipping.mlshippingid.in_(asig_shipment_ids))
            .all()
        )
        if asig_shipment_ids
        else []
    )
    envios_map_asig = {str(e.mlshippingid): e for e in envios_para_asignar}

    # Batch fetch geocoding for these envíos (1 query instead of N)
    asig_hashes: Dict[str, str] = {}  # shipment_id -> hash
    for sid, envio in envios_map_asig.items():
        direccion = f"{envio.mlstreet_name} {envio.mlstreet_number}, {envio.mlcity_name}".strip()
        asig_hashes[sid] = GeocodingCache.hash_direccion(direccion)

    unique_asig_hashes = list(set(asig_hashes.values()))
    geo_map_asig: Dict[str, GeocodingCache] = {}
    if unique_asig_hashes:
        cache_rows = db.query(GeocodingCache).filter(GeocodingCache.direccion_hash.in_(unique_asig_hashes)).all()
        geo_map_asig = {row.direccion_hash: row for row in cache_rows}

    asignaciones_creadas = []
    for asignacion_data in resultado["asignaciones"]:
        envio = envios_map_asig.get(asignacion_data["mlshippingid"])
        if not envio:
            continue

        # Construir dirección
        direccion = f"{envio.mlstreet_name} {envio.mlstreet_number}, {envio.mlcity_name}".strip()

        # Obtener coordenadas from pre-fetched map
        h = asig_hashes.get(asignacion_data["mlshippingid"], "")
        cache = geo_map_asig.get(h)
        latitud = float(cache.latitud) if cache else None
        longitud = float(cache.longitud) if cache else None

        # Crear asignación
        asignacion = AsignacionTurbo(
            mlshippingid=asignacion_data["mlshippingid"],
            motoquero_id=asignacion_data["motoquero_id"],
            zona_id=asignacion_data["zona_id"],
            direccion=direccion[:500],
            latitud=latitud,
            longitud=longitud,
            estado="pendiente",
            asignado_por="automatico",
        )

        db.add(asignacion)
        asignaciones_creadas.append(asignacion_data)

    db.commit()

    logger.info(
        f"✅ Asignación automática: {len(asignaciones_creadas)} asignados, {resultado['total_sin_zona']} sin zona"
    )

    return {
        "total_procesados": len(envios_coords),
        "total_asignados": len(asignaciones_creadas),
        "total_sin_zona": resultado["total_sin_zona"],
        "asignaciones": asignaciones_creadas,
        "sin_zona": resultado["sin_zona"],
        "mensaje": f"✅ {len(asignaciones_creadas)} envíos asignados automáticamente",
    }


@router.get("/turbo/asignaciones/hoy")
def obtener_asignaciones_del_dia(
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
    fecha: Optional[str] = Query(None, description="Fecha en formato YYYY-MM-DD (default: hoy)"),
):
    """
    Obtiene todas las asignaciones del día agrupadas por motoquero.
    Incluye estado actualizado de cada envío desde ML.

    Útil para:
    - Seguimiento en tiempo real del trabajo de cada motoquero
    - Ver qué envíos están pendientes, en camino o entregados
    - Control de performance del día
    """
    if not verificar_permiso(db, current_user, "ordenes.gestionar_turbo_routing"):
        raise HTTPException(status_code=403, detail="Sin permiso para gestionar Turbo Routing")

    # Fecha objetivo (hoy si no se especifica)
    if fecha:
        try:
            fecha_obj = datetime.strptime(fecha, "%Y-%m-%d").date()
        except ValueError:
            raise HTTPException(status_code=400, detail="Formato de fecha inválido. Usar YYYY-MM-DD")
    else:
        fecha_obj = datetime.now(ARGENTINA_TZ).date()

    # Obtener asignaciones del día
    fecha_inicio = datetime.combine(fecha_obj, datetime.min.time()).replace(tzinfo=ARGENTINA_TZ)
    fecha_fin = datetime.combine(fecha_obj, datetime.max.time()).replace(tzinfo=ARGENTINA_TZ)

    asignaciones = (
        db.query(AsignacionTurbo)
        .filter(
            AsignacionTurbo.asignado_at >= fecha_inicio,
            AsignacionTurbo.asignado_at <= fecha_fin,
            AsignacionTurbo.estado != "cancelado",
        )
        .order_by(AsignacionTurbo.motoquero_id, AsignacionTurbo.asignado_at)
        .all()
    )

    # Agrupar por motoquero
    motoqueros_dict = {}

    for asig in asignaciones:
        motoquero_id = asig.motoquero_id

        if motoquero_id not in motoqueros_dict:
            motoqueros_dict[motoquero_id] = {
                "motoquero_id": motoquero_id,
                "nombre": asig.motoquero.nombre if asig.motoquero else "Sin nombre",
                "activo": asig.motoquero.activo if asig.motoquero else False,
                "envios": [],
                "total_envios": 0,
                "pendientes": 0,
                "en_camino": 0,
                "entregados": 0,
                "cancelados": 0,
            }

        # Obtener estado actual del envío desde ML
        envio_ml = (
            db.query(MercadoLibreOrderShipping)
            .filter(MercadoLibreOrderShipping.mlshippingid == asig.mlshippingid)
            .first()
        )

        estado_ml = envio_ml.mlstatus if envio_ml else "unknown"

        # Mapear estado ML a estado interno
        if estado_ml in ["delivered", "delivered_picked_up"]:
            estado_display = "entregado"
        elif estado_ml in ["shipped", "handling", "ready_to_ship"]:
            estado_display = "en_camino" if estado_ml == "shipped" else "pendiente"
        else:
            estado_display = "pendiente"

        # Construir objeto de envío
        envio_data = {
            "asignacion_id": asig.id,
            "mlshippingid": asig.mlshippingid,
            "direccion": asig.direccion,
            "latitud": float(asig.latitud) if asig.latitud else None,
            "longitud": float(asig.longitud) if asig.longitud else None,
            "zona_nombre": asig.zona.nombre if asig.zona else None,
            "estado_asignacion": asig.estado,
            "estado_ml": estado_ml,
            "estado_display": estado_display,
            "orden_ruta": asig.orden_ruta,
            "asignado_at": convert_to_argentina_tz(asig.asignado_at) if asig.asignado_at else None,
            "entregado_at": convert_to_argentina_tz(asig.entregado_at) if asig.entregado_at else None,
            "destinatario": envio_ml.mlreceiver_name if envio_ml else None,
            "telefono": envio_ml.mlreceiver_phone if envio_ml else None,
        }

        motoqueros_dict[motoquero_id]["envios"].append(envio_data)
        motoqueros_dict[motoquero_id]["total_envios"] += 1

        # Contadores por estado
        if estado_display == "entregado":
            motoqueros_dict[motoquero_id]["entregados"] += 1
        elif estado_display == "en_camino":
            motoqueros_dict[motoquero_id]["en_camino"] += 1
        else:
            motoqueros_dict[motoquero_id]["pendientes"] += 1

    # Convertir a lista
    motoqueros_list = list(motoqueros_dict.values())

    # Calcular totales generales
    total_asignaciones = sum(m["total_envios"] for m in motoqueros_list)
    total_entregados = sum(m["entregados"] for m in motoqueros_list)
    total_pendientes = sum(m["pendientes"] for m in motoqueros_list)

    return {
        "fecha": fecha_obj.isoformat(),
        "total_asignaciones": total_asignaciones,
        "total_entregados": total_entregados,
        "total_pendientes": total_pendientes,
        "motoqueros": motoqueros_list,
    }
