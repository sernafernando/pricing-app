"""
Endpoints CRUD de zonas de reparto + auto-generación K-Means.
"""

import logging
from datetime import datetime
from typing import Dict, List

from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy import and_
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.api.deps import get_current_user
from app.models.zona_reparto import ZonaReparto
from app.models.asignacion_turbo import AsignacionTurbo
from app.models.geocoding_cache import GeocodingCache
from app.models.mercadolibre_order_shipping import MercadoLibreOrderShipping
from app.models.usuario import Usuario
from app.services.permisos_service import verificar_permiso
from app.services.kmeans_zone_service import generar_zonas_kmeans, validar_envios_geocodificados

from ._shared import (
    ARGENTINA_TZ,
    DeleteResponse,
    ZonaRepartoCreate,
    ZonaRepartoResponse,
)

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/turbo/zonas", response_model=List[ZonaRepartoResponse])
def obtener_zonas(
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
    solo_activas: bool = Query(True, description="Solo zonas activas"),
):
    """Obtiene la lista de zonas de reparto."""
    if not verificar_permiso(db, current_user, "ordenes.gestionar_turbo_routing"):
        raise HTTPException(status_code=403, detail="Sin permiso")

    query = db.query(ZonaReparto)
    if solo_activas:
        query = query.filter(ZonaReparto.activa.is_(True))

    zonas = query.order_by(ZonaReparto.nombre).all()
    return zonas


@router.post("/turbo/zonas", response_model=ZonaRepartoResponse)
def crear_zona(
    zona: ZonaRepartoCreate, db: Session = Depends(get_db), current_user: Usuario = Depends(get_current_user)
):
    """Crea una nueva zona de reparto MANUAL."""
    if not verificar_permiso(db, current_user, "ordenes.gestionar_turbo_routing"):
        raise HTTPException(status_code=403, detail="Sin permiso")

    zona_data = zona.model_dump()
    # Forzar tipo_generacion='manual' para zonas creadas por usuarios
    zona_data["tipo_generacion"] = "manual"

    nueva_zona = ZonaReparto(**zona_data, creado_por=current_user.id)
    db.add(nueva_zona)
    db.commit()
    db.refresh(nueva_zona)

    return nueva_zona


@router.delete("/turbo/zonas/{zona_id}", response_model=DeleteResponse)
def eliminar_zona(zona_id: int, db: Session = Depends(get_db), current_user: dict = Depends(get_current_user)):
    """Desactiva una zona (no la elimina físicamente)."""
    if not verificar_permiso(db, current_user, "ordenes.gestionar_turbo_routing"):
        raise HTTPException(status_code=403, detail="Sin permiso")

    db_zona = db.query(ZonaReparto).filter(ZonaReparto.id == zona_id).first()
    if not db_zona:
        raise HTTPException(status_code=404, detail="Zona no encontrada")

    db_zona.activa = False
    db.commit()

    return DeleteResponse(message="Zona desactivada", success=True)


@router.put("/turbo/zonas/{zona_id}/toggle", response_model=ZonaRepartoResponse)
def toggle_zona(zona_id: int, db: Session = Depends(get_db), current_user: dict = Depends(get_current_user)):
    """
    Activa/desactiva una zona de reparto (toggle del campo activa).

    Casos de uso:
    - Desactivar zonas manuales temporalmente sin perderlas
    - Reactivar zonas manuales después de auto-generar
    - Activar/desactivar zonas para control fino de asignaciones

    El campo tipo_generacion se preserva para distinguir origen (manual/automatica).
    """
    if not verificar_permiso(db, current_user, "ordenes.gestionar_turbo_routing"):
        raise HTTPException(status_code=403, detail="Sin permiso")

    db_zona = db.query(ZonaReparto).filter(ZonaReparto.id == zona_id).first()
    if not db_zona:
        raise HTTPException(status_code=404, detail="Zona no encontrada")

    # Toggle estado
    db_zona.activa = not db_zona.activa
    db.commit()
    db.refresh(db_zona)

    logger.info(
        f"Zona {zona_id} {'activada' if db_zona.activa else 'desactivada'} por usuario {current_user.get('id', 'unknown')}"
    )

    return db_zona


@router.post("/turbo/zonas/auto-generar", response_model=List[ZonaRepartoResponse])
def auto_generar_zonas(
    cantidad_motoqueros: int = Query(..., description="Cantidad de zonas a generar"),
    eliminar_anteriores: bool = Query(False, description="Eliminar zonas auto-generadas anteriores"),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    """
    Auto-genera zonas de reparto usando K-Means clustering sobre envíos geocodificados.

    Algoritmo:
    1. Obtiene envíos Turbo pendientes (sin asignar)
    2. Filtra solo los geocodificados (lat/lng válidos)
    3. Valida que al menos 70% estén geocodificados
    4. Aplica K-Means para agrupar en K clusters (K = cantidad_motoqueros)
    5. Genera polígono ConvexHull por cada cluster
    6. Balancea automáticamente cantidad de paquetes por zona

    Args:
        cantidad_motoqueros: Cantidad de zonas a crear (1 zona por motoquero)
        eliminar_anteriores: Si True, desactiva zonas auto-generadas previas

    Returns:
        Lista de zonas creadas con distribución equitativa de envíos
    """
    if not verificar_permiso(db, current_user, "ordenes.gestionar_turbo_routing"):
        raise HTTPException(status_code=403, detail="Sin permiso")

    if cantidad_motoqueros < 1 or cantidad_motoqueros > 6:
        raise HTTPException(status_code=400, detail="Cantidad debe estar entre 1 y 6")

    try:
        logger.info(f"🤖 Auto-generando {cantidad_motoqueros} zonas con K-Means clustering...")

        # 1. Obtener envíos Turbo SIN asignar que TENGAN GEOCODING
        # Primero obtenemos los hashes de direcciones que están en el cache
        direcciones_geocodificadas = db.query(GeocodingCache.direccion_normalizada).all()
        direcciones_set = {d[0] for d in direcciones_geocodificadas}

        # Obtener envíos Turbo sin asignar
        envios_candidatos = (
            db.query(MercadoLibreOrderShipping)
            .filter(
                and_(
                    MercadoLibreOrderShipping.mlshipping_method_id == "515282",
                    MercadoLibreOrderShipping.mlstatus.notin_(
                        ["delivered", "cancelled", "returned", "lost", "damaged"]
                    ),
                    ~MercadoLibreOrderShipping.mlshippingid.in_(
                        db.query(AsignacionTurbo.mlshippingid).filter(AsignacionTurbo.estado != "cancelado")
                    ),
                )
            )
            .limit(200)
            .all()
        )  # Traer más para filtrar los geocodificados

        # Filtrar solo los que tienen geocoding
        envios_sin_asignar = []
        for envio in envios_candidatos:
            direccion = f"{envio.mlstreet_name} {envio.mlstreet_number}, {envio.mlcity_name}".strip()
            if direccion in direcciones_set:
                envios_sin_asignar.append(envio)

        if not envios_sin_asignar:
            raise HTTPException(status_code=400, detail="No hay envíos Turbo pendientes para asignar")

        logger.info(f"📦 {len(envios_sin_asignar)} envíos Turbo sin asignar")

        # 2. Filtrar envíos geocodificados (lat/lng válidos) — batch lookup
        # Pre-compute all hashes and fetch in a single query
        envio_hashes = []
        for envio in envios_sin_asignar:
            direccion = f"{envio.mlstreet_name} {envio.mlstreet_number}, {envio.mlcity_name}".strip()
            envio_hashes.append(GeocodingCache.hash_direccion(direccion))

        unique_hashes = list(set(envio_hashes))
        geo_map: Dict[str, GeocodingCache] = {}
        if unique_hashes:
            cache_rows = db.query(GeocodingCache).filter(GeocodingCache.direccion_hash.in_(unique_hashes)).all()
            geo_map = {row.direccion_hash: row for row in cache_rows}

        envios_coords = []
        for envio, h in zip(envios_sin_asignar, envio_hashes):
            cache = geo_map.get(h)
            if cache and cache.latitud and cache.longitud:
                envios_coords.append((float(cache.latitud), float(cache.longitud), envio.mlm_id))

        # 3. Validar porcentaje de geocodificación
        es_valido, mensaje = validar_envios_geocodificados(
            total_envios=len(envios_sin_asignar), envios_geocodificados=len(envios_coords), porcentaje_minimo=0.7
        )

        if not es_valido:
            raise HTTPException(status_code=400, detail=mensaje)

        logger.info(mensaje)

        # 4. Eliminar zonas anteriores si se solicita
        if eliminar_anteriores:
            # Manuales: DESACTIVAR (conservar en BD)
            zonas_manuales = (
                db.query(ZonaReparto)
                .filter(ZonaReparto.activa.is_(True), ZonaReparto.tipo_generacion == "manual")
                .all()
            )
            for zona in zonas_manuales:
                zona.activa = False

            # Automáticas: ELIMINAR FÍSICAMENTE
            zonas_automaticas = db.query(ZonaReparto).filter(ZonaReparto.tipo_generacion == "automatica").all()
            for zona in zonas_automaticas:
                db.delete(zona)

            db.commit()
            logger.info(
                f"🗑️ Zonas manuales desactivadas: {len(zonas_manuales)} | "
                f"Zonas automáticas eliminadas: {len(zonas_automaticas)}"
            )

        # 5. Generar zonas usando K-Means
        zonas_data = generar_zonas_kmeans(envios_coords=envios_coords, cantidad_zonas=cantidad_motoqueros)

        if not zonas_data:
            raise HTTPException(status_code=500, detail="No se pudieron generar zonas. Verificar logs del servidor.")

        # 6. Guardar en BD (validar nombres duplicados)
        # Obtener nombres existentes de zonas activas
        nombres_existentes_query = db.query(ZonaReparto.nombre).filter(ZonaReparto.activa.is_(True)).all()
        nombres_existentes_set = {n[0] for n in nombres_existentes_query}

        zonas_creadas = []
        for zona_data in zonas_data:
            # Combinar nombre + descripción
            nombre_base = f"{zona_data['nombre']} - {zona_data['descripcion']}"

            # Si el nombre ya existe, agregar timestamp
            nombre_final = nombre_base
            if nombre_base in nombres_existentes_set:
                timestamp = datetime.now(ARGENTINA_TZ).strftime("%H:%M:%S")
                nombre_final = f"{nombre_base} [{timestamp}]"
                logger.warning(f"⚠️ Nombre duplicado detectado: '{nombre_base}' → '{nombre_final}'")

            # Agregar al set para evitar duplicados dentro del mismo batch
            nombres_existentes_set.add(nombre_final)

            nueva_zona = ZonaReparto(
                nombre=nombre_final,
                poligono=zona_data["poligono"],
                color=zona_data["color"],
                activa=True,
                tipo_generacion="automatica",  # Marcar como auto-generada por K-Means
                creado_por=current_user.id,
            )
            db.add(nueva_zona)
            zonas_creadas.append(nueva_zona)

        db.commit()

        # Refrescar para obtener IDs
        for zona in zonas_creadas:
            db.refresh(zona)

        logger.info(f"✅ {len(zonas_creadas)} zonas auto-generadas con K-Means")
        return zonas_creadas

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Error auto-generando zonas: {e}", exc_info=True)
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Error generando zonas: {str(e)}")
