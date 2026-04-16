"""
Endpoints de geocodificación de envíos Turbo (individual, batch Mapbox, batch ML).
"""

import asyncio
import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import and_
from sqlalchemy.orm import Session

from app.core.database import get_background_db, get_async_db
from app.api.deps import get_current_user
from app.models.asignacion_turbo import AsignacionTurbo
from app.models.geocoding_cache import GeocodingCache
from app.models.mercadolibre_order_shipping import MercadoLibreOrderShipping
from app.services.permisos_service import verificar_permiso
from app.services.geocoding_service import geocode_address
from app.services.ml_webhook_service import fetch_shipment_data, extraer_coordenadas, extraer_direccion_completa

router = APIRouter()
logger = logging.getLogger(__name__)


@router.post("/turbo/geocoding/envio/{shipment_id}", response_model=dict)
async def geocodificar_envio(
    shipment_id: str, db: Session = Depends(get_async_db), current_user: dict = Depends(get_current_user)
):
    """
    Geocodifica un envío específico usando su dirección.
    Guarda el resultado en la tabla geocoding_cache y actualiza asignaciones_turbo si existe.
    """
    if not verificar_permiso(db, current_user, "ordenes.gestionar_turbo_routing"):
        raise HTTPException(status_code=403, detail="Sin permiso")

    # Buscar envío en BD
    envio = db.query(MercadoLibreOrderShipping).filter(MercadoLibreOrderShipping.mlshippingid == shipment_id).first()

    if not envio:
        raise HTTPException(status_code=404, detail="Envío no encontrado")

    # Construir dirección
    direccion_partes = []
    if envio.mlstreet_name:
        direccion_partes.append(envio.mlstreet_name)
    if envio.mlstreet_number:
        direccion_partes.append(envio.mlstreet_number)

    direccion = " ".join(direccion_partes) if direccion_partes else None
    ciudad = envio.mlcity_name or "Buenos Aires"

    if not direccion:
        raise HTTPException(status_code=400, detail="Envío sin dirección válida")

    # Geocodificar
    coords = await geocode_address(direccion, ciudad=ciudad, db=db)

    if not coords:
        raise HTTPException(status_code=404, detail="No se pudo geocodificar la dirección")

    latitud, longitud = coords

    # Actualizar asignación si existe
    asignacion = (
        db.query(AsignacionTurbo)
        .filter(AsignacionTurbo.mlshippingid == shipment_id, AsignacionTurbo.estado != "cancelado")
        .first()
    )

    if asignacion:
        asignacion.latitud = latitud
        asignacion.longitud = longitud
        asignacion.direccion = f"{direccion}, {ciudad}"
        db.commit()

    return {
        "shipment_id": shipment_id,
        "direccion": f"{direccion}, {ciudad}",
        "latitud": latitud,
        "longitud": longitud,
        "actualizado_en_asignacion": asignacion is not None,
    }


@router.post("/turbo/geocoding/batch", response_model=dict)
async def geocodificar_batch(
    shipment_ids: list[str], db: Session = Depends(get_async_db), current_user: dict = Depends(get_current_user)
):
    """
    Geocodifica múltiples envíos en batch.
    IMPORTANTE: Esto puede tomar tiempo. Mapbox permite ~10 req/seg.

    Usa sesiones cortas (get_background_db) por cada item para no retener
    una conexión del pool durante todo el batch (10-20s con rate limiting).
    """
    if not verificar_permiso(db, current_user, "ordenes.gestionar_turbo_routing"):
        raise HTTPException(status_code=403, detail="Sin permiso")

    if len(shipment_ids) > 100:
        raise HTTPException(status_code=400, detail="Máximo 100 envíos por batch")

    resultados = {"total": len(shipment_ids), "exitosos": 0, "fallidos": 0, "detalles": []}

    for shipment_id in shipment_ids:
        with get_background_db() as bg_db:
            # Buscar envío
            envio = (
                bg_db.query(MercadoLibreOrderShipping)
                .filter(MercadoLibreOrderShipping.mlshippingid == shipment_id)
                .first()
            )

            if not envio:
                resultados["fallidos"] += 1
                resultados["detalles"].append(
                    {"shipment_id": shipment_id, "status": "error", "mensaje": "Envío no encontrado"}
                )
                continue

            # Construir dirección
            direccion_partes = []
            if envio.mlstreet_name:
                direccion_partes.append(envio.mlstreet_name)
            if envio.mlstreet_number:
                direccion_partes.append(envio.mlstreet_number)

            direccion = " ".join(direccion_partes) if direccion_partes else None
            ciudad = envio.mlcity_name or "Buenos Aires"

            if not direccion:
                resultados["fallidos"] += 1
                resultados["detalles"].append(
                    {"shipment_id": shipment_id, "status": "error", "mensaje": "Sin dirección válida"}
                )
                continue

            # Geocodificar (HTTP call a Mapbox — la sesión queda open pero es breve)
            coords = await geocode_address(direccion, ciudad=ciudad, db=bg_db)

            if not coords:
                resultados["fallidos"] += 1
                resultados["detalles"].append(
                    {"shipment_id": shipment_id, "status": "error", "mensaje": "No se pudo geocodificar"}
                )
                continue

            latitud, longitud = coords

            # Actualizar asignación si existe
            asignacion = (
                bg_db.query(AsignacionTurbo)
                .filter(AsignacionTurbo.mlshippingid == shipment_id, AsignacionTurbo.estado != "cancelado")
                .first()
            )

            if asignacion:
                asignacion.latitud = latitud
                asignacion.longitud = longitud
                asignacion.direccion = f"{direccion}, {ciudad}"

            resultados["exitosos"] += 1
            resultados["detalles"].append(
                {"shipment_id": shipment_id, "status": "success", "latitud": latitud, "longitud": longitud}
            )

            # commit is handled by get_background_db() on exit

        # Rate limiting FUERA de la sesión — la conexión ya se devolvió al pool
        await asyncio.sleep(0.1)

    return resultados


@router.post("/turbo/geocoding/batch-ml", response_model=dict)
async def geocodificar_batch_ml_webhook(
    db: Session = Depends(get_async_db), current_user: dict = Depends(get_current_user)
):
    """
    Geocodifica TODOS los envíos Turbo sin asignar usando ML Webhook API.

    Ventajas sobre Mapbox:
    - 100% precisión (ML ya hizo el geocoding)
    - 0 costo (API interna)
    - Más rápido (sin rate limiting externo)

    Algoritmo:
    1. Obtiene envíos Turbo sin asignar
    2. Por cada envío, llama a ML Webhook con mlshippingid
    3. Extrae lat/lng del JSON
    4. Guarda en geocoding_cache

    Returns:
        Estadísticas de geocodificación batch
    """
    if not verificar_permiso(db, current_user, "ordenes.gestionar_turbo_routing"):
        raise HTTPException(status_code=403, detail="Sin permiso")

    logger.info("🚀 Iniciando geocoding batch desde ML Webhook...")

    # 1. Obtener envíos Turbo SIN asignar
    # NOTA: Filtramos excluyendo estados finales porque mlstatus en BD puede estar desactualizado
    envios_sin_asignar = (
        db.query(MercadoLibreOrderShipping)
        .filter(
            and_(
                MercadoLibreOrderShipping.mlshipping_method_id == "515282",
                MercadoLibreOrderShipping.mlstatus.notin_(["delivered", "cancelled", "returned", "lost", "damaged"]),
                ~MercadoLibreOrderShipping.mlshippingid.in_(
                    db.query(AsignacionTurbo.mlshippingid).filter(AsignacionTurbo.estado != "cancelado")
                ),
            )
        )
        .limit(200)
        .all()
    )  # Limitar para evitar sobrecarga en geocoding batch

    total_envios = len(envios_sin_asignar)

    if total_envios == 0:
        return {
            "total": 0,
            "exitosos": 0,
            "fallidos": 0,
            "sin_shipping_id": 0,
            "sin_coordenadas": 0,
            "mensaje": "No hay envíos Turbo pendientes",
        }

    # Extraer campos necesarios a dicts planos ANTES del loop.
    # Los objetos ORM quedarán detached cuando usemos get_background_db(),
    # así que materializamos los valores que necesitamos ahora.
    envios_data = [
        {
            "mlshippingid": e.mlshippingid,
            "mlo_id": e.mlo_id,
            "mlstreet_name": e.mlstreet_name,
            "mlstreet_number": e.mlstreet_number,
            "mlcity_name": e.mlcity_name,
        }
        for e in envios_sin_asignar
    ]

    logger.info(f"📦 {total_envios} envíos Turbo sin asignar")

    # Contadores
    exitosos = 0
    fallidos = 0
    sin_shipping_id = 0
    sin_coordenadas = 0

    # Set para trackear hashes procesados en este batch (evitar duplicados)
    hashes_procesados_batch = set()

    # 2. Procesar cada envío con sesiones cortas (get_background_db).
    # Cada iteración hace un HTTP call a ML Webhook (~50ms+), así que
    # usamos sesiones independientes para no retener una conexión del pool
    # durante todo el batch (200 items × 50ms = 10s+).
    for envio in envios_data:
        try:
            # Validar que tenga shipping_id
            if not envio["mlshippingid"]:
                sin_shipping_id += 1
                logger.warning(f"Envío sin mlshippingid: mlo_id={envio['mlo_id']}")
                continue

            # Llamar a ML Webhook — SIN sesión DB abierta
            data = await fetch_shipment_data(envio["mlshippingid"])

            if not data:
                fallidos += 1
                continue

            # Extraer coordenadas
            lat, lng = extraer_coordenadas(data)

            if lat is None or lng is None:
                sin_coordenadas += 1
                logger.warning(f"Envío {envio['mlshippingid']} sin coordenadas en ML Webhook")
                continue

            # Construir dirección normalizada
            direccion_completa = extraer_direccion_completa(data)

            if not direccion_completa:
                # Fallback: usar datos extraídos
                direccion_completa = (
                    f"{envio['mlstreet_name']} {envio['mlstreet_number']}, {envio['mlcity_name']}".strip()
                )

            # Guardar en cache de geocoding (merge = insert or update)
            direccion_hash = GeocodingCache.hash_direccion(direccion_completa)

            # Si ya procesamos este hash en este batch, skipear
            # (evita UniqueViolation cuando hay direcciones repetidas)
            if direccion_hash in hashes_procesados_batch:
                exitosos += 1  # Contar como exitoso (ya está cacheado)
                continue

            # Sesión corta solo para la escritura en DB
            with get_background_db() as bg_db:
                # Merge: si existe la dirección (buscar por PK), actualiza; si no, inserta
                existing = bg_db.query(GeocodingCache).filter(GeocodingCache.direccion_hash == direccion_hash).first()

                if existing:
                    # Actualizar registro existente
                    existing.latitud = lat
                    existing.longitud = lng
                    existing.provider = "ml_webhook"
                else:
                    # Crear nuevo registro
                    cache_entry = GeocodingCache(
                        direccion_hash=direccion_hash,
                        direccion_normalizada=direccion_completa,
                        latitud=lat,
                        longitud=lng,
                        provider="ml_webhook",
                    )
                    bg_db.add(cache_entry)

                # commit is handled by get_background_db() on exit

            # Marcar hash como procesado
            hashes_procesados_batch.add(direccion_hash)

            exitosos += 1

            # Log cada 10 envíos
            if exitosos % 10 == 0:
                logger.info(f"✅ Geocodificados: {exitosos}/{total_envios}")

            # Rate limiting FUERA de la sesión — la conexión ya se devolvió al pool
            await asyncio.sleep(0.05)  # 50ms = ~20 req/seg

        except Exception as e:
            fallidos += 1
            logger.error(f"Error geocodificando envío {envio['mlshippingid']}: {e}", exc_info=True)
            continue

    logger.info(
        f"✅ Geocoding batch completado: "
        f"{exitosos} exitosos, {fallidos} fallidos, "
        f"{sin_shipping_id} sin ID, {sin_coordenadas} sin coords"
    )

    return {
        "total": total_envios,
        "exitosos": exitosos,
        "fallidos": fallidos,
        "sin_shipping_id": sin_shipping_id,
        "sin_coordenadas": sin_coordenadas,
        "porcentaje_exito": round((exitosos / total_envios * 100), 2) if total_envios > 0 else 0,
    }
