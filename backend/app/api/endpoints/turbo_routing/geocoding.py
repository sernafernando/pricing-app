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

    # Release the request session before going out to Mapbox: the lookup above opened
    # a transaction, and holding it across the HTTP round-trip leaves the connection
    # `idle in transaction` for the whole call. Only reads are pending, so this
    # discards no work. `db=None` makes geocode_address use its own short-lived
    # session for the cache instead of ours.
    db.commit()

    # Geocodificar — sin sesión de DB retenida
    coords = await geocode_address(direccion, ciudad=ciudad, db=None)

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

    Pool-safe en tres fases: se lee todo con una sesión corta, el loop de HTTP
    corre SIN ninguna sesión tomada, y las escrituras van juntas al final.
    """
    if not verificar_permiso(db, current_user, "ordenes.gestionar_turbo_routing"):
        raise HTTPException(status_code=403, detail="Sin permiso")

    if len(shipment_ids) > 100:
        raise HTTPException(status_code=400, detail="Máximo 100 envíos por batch")

    # Release the request session: the permission check above opened a transaction on
    # it and nothing reads from `db` again. Left open, it would sit `idle in
    # transaction` for the whole batch while the phases below ask the pool for more.
    db.commit()

    resultados: dict = {"total": len(shipment_ids), "exitosos": 0, "fallidos": 0, "detalles": []}
    # Keyed by shipment_id so `detalles` can be rebuilt in the caller's original order
    # at the end: the phases below resolve items in two passes, and emitting as we go
    # would silently reorder the response relative to `shipment_ids`.
    detalle_por_envio: dict[str, dict] = {}

    # ── PHASE 1: short session — resolve every address up front ──
    pendientes: list[tuple[str, str, str]] = []  # (shipment_id, direccion, ciudad)
    with get_background_db() as read_db:
        for shipment_id in shipment_ids:
            envio = (
                read_db.query(MercadoLibreOrderShipping)
                .filter(MercadoLibreOrderShipping.mlshippingid == shipment_id)
                .first()
            )

            if not envio:
                resultados["fallidos"] += 1
                detalle_por_envio[shipment_id] = {
                    "shipment_id": shipment_id,
                    "status": "error",
                    "mensaje": "Envío no encontrado",
                }
                continue

            direccion_partes = []
            if envio.mlstreet_name:
                direccion_partes.append(envio.mlstreet_name)
            if envio.mlstreet_number:
                direccion_partes.append(envio.mlstreet_number)

            direccion = " ".join(direccion_partes) if direccion_partes else None
            ciudad = envio.mlcity_name or "Buenos Aires"

            if not direccion:
                resultados["fallidos"] += 1
                detalle_por_envio[shipment_id] = {
                    "shipment_id": shipment_id,
                    "status": "error",
                    "mensaje": "Sin dirección válida",
                }
                continue

            pendientes.append((shipment_id, direccion, ciudad))
    # PHASE 1 closes here — pool released, nothing held during the HTTP calls below.

    # ── PHASE 2: NO session — the slow Mapbox loop ──
    # `db=None` keeps geocode_address off our session: it opens its own short-lived
    # one for the cache, closed before each HTTP call.
    coords_por_envio: dict[str, tuple[float, float, str]] = {}
    for shipment_id, direccion, ciudad in pendientes:
        coords = await geocode_address(direccion, ciudad=ciudad, db=None)

        if not coords:
            resultados["fallidos"] += 1
            detalle_por_envio[shipment_id] = {
                "shipment_id": shipment_id,
                "status": "error",
                "mensaje": "No se pudo geocodificar",
            }
        else:
            latitud, longitud = coords
            coords_por_envio[shipment_id] = (latitud, longitud, f"{direccion}, {ciudad}")
            resultados["exitosos"] += 1
            detalle_por_envio[shipment_id] = {
                "shipment_id": shipment_id,
                "status": "success",
                "latitud": latitud,
                "longitud": longitud,
            }

        # Rate limiting — sin ninguna conexión tomada
        await asyncio.sleep(0.1)

    # ── PHASE 3: short session — one write pass, one commit ──
    if coords_por_envio:
        with get_background_db() as write_db:
            for shipment_id, (latitud, longitud, direccion_completa) in coords_por_envio.items():
                write_db.query(AsignacionTurbo).filter(
                    AsignacionTurbo.mlshippingid == shipment_id, AsignacionTurbo.estado != "cancelado"
                ).update(
                    {"latitud": latitud, "longitud": longitud, "direccion": direccion_completa},
                    synchronize_session=False,
                )
            # commit is handled by get_background_db() on exit

    # Rebuild in the caller's original order, as the pre-refactor loop emitted them.
    resultados["detalles"] = [detalle_por_envio[sid] for sid in shipment_ids if sid in detalle_por_envio]

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

    # Release the request session before the loop below. The permission check and the
    # query above opened a transaction on it, and nothing reads from `db` again — it
    # would otherwise sit `idle in transaction` for the entire batch (up to 200 items
    # × one ML Webhook round-trip each), holding a pool connection hostage while the
    # per-item short sessions ask the pool for more.
    db.commit()

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
