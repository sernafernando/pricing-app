"""
Servicio de enriquecimiento de etiquetas de envío con datos del ML Webhook.

Se ejecuta en background (asyncio.create_task) después del upload/scan.
Para cada etiqueta nueva, llama al ML webhook y guarda:
- latitud / longitud (coordenadas exactas del destinatario)
- direccion_completa (calle, ciudad, provincia formateada)
- direccion_comentario (notas del comprador: "puerta negra", "timbre 3B")
- es_outlet (si algún item contiene "outlet" en el título)

Usa una sesión de DB independiente para no bloquear la respuesta HTTP.

También incluye `re_enriquecer_desde_db()` para re-procesar etiquetas
leyendo directamente de ml_previews (sin HTTP), útil cuando el webhook
estuvo caído o se agregaron campos nuevos.
"""

import asyncio
import logging
from typing import Dict, List, Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.database import SessionLocal, get_mlwebhook_engine
from app.models.etiqueta_envio import EtiquetaEnvio
from app.services.ml_webhook_service import (
    fetch_shipment_data,
    extraer_coordenadas,
    extraer_direccion_completa,
    extraer_comentario_direccion,
    extraer_es_outlet,
)

logger = logging.getLogger(__name__)


async def enriquecer_etiquetas(shipping_ids: List[str]) -> None:
    """
    Enriquece un lote de etiquetas con datos del ML Webhook.

    Abre su propia sesión de DB para no interferir con la request.
    Procesa secuencialmente (1 call por etiqueta, ~200ms cada una).
    Para 25 etiquetas ≈ 5 segundos total.

    Args:
        shipping_ids: Lista de shipping_ids a enriquecer
    """
    if not shipping_ids:
        return

    logger.info(f"Enriqueciendo {len(shipping_ids)} etiquetas en background...")

    db: Session = SessionLocal()
    enriquecidas = 0
    errores = 0

    try:
        for shipping_id in shipping_ids:
            try:
                data = await fetch_shipment_data(shipping_id)
                if not data:
                    errores += 1
                    continue

                lat, lng = extraer_coordenadas(data)
                direccion = extraer_direccion_completa(data)
                comentario = extraer_comentario_direccion(data)
                es_outlet = extraer_es_outlet(data)

                # Actualizar solo si hay algo que guardar
                if lat is not None or direccion or comentario or es_outlet:
                    etiqueta = db.query(EtiquetaEnvio).filter(EtiquetaEnvio.shipping_id == shipping_id).first()
                    if etiqueta:
                        if lat is not None and lng is not None:
                            etiqueta.latitud = lat
                            etiqueta.longitud = lng
                        if direccion:
                            etiqueta.direccion_completa = direccion
                        if comentario:
                            etiqueta.direccion_comentario = comentario
                        if es_outlet:
                            etiqueta.es_outlet = True

                        enriquecidas += 1

                # Pequeño yield para no bloquear el event loop
                await asyncio.sleep(0.05)

            except Exception as e:
                logger.error(f"Error enriqueciendo {shipping_id}: {e}")
                errores += 1

        db.commit()
        logger.info(f"Enriquecimiento completo: {enriquecidas}/{len(shipping_ids)} OK, {errores} errores")

    except Exception as e:
        db.rollback()
        logger.error(f"Error en commit de enriquecimiento: {e}")
    finally:
        db.close()


def lanzar_enriquecimiento_background(shipping_ids: List[str]) -> None:
    """
    Lanza el enriquecimiento como background task en el event loop actual.

    Se usa desde endpoints sync (def, no async def) usando el loop de uvicorn.
    No bloquea la respuesta HTTP — el usuario recibe el resultado del upload
    inmediatamente y las coordenadas se llenan en background.

    Args:
        shipping_ids: Lista de shipping_ids de etiquetas nuevas
    """
    if not shipping_ids:
        return

    try:
        loop = asyncio.get_event_loop()
        loop.create_task(enriquecer_etiquetas(shipping_ids))
        logger.info(f"Background enrichment lanzado para {len(shipping_ids)} etiquetas")
    except RuntimeError:
        logger.warning("No hay event loop disponible para background enrichment")


# ── Re-enrichment desde ml_previews (DB directa) ──────────────


def _fetch_previews_batch(
    shipping_ids: List[str],
) -> Dict[str, Dict]:
    """
    Lee ml_previews en batch para un lote de shipping_ids.

    Busca registros con resource = '/shipments/{id}' y devuelve un dict
    {shipping_id: {title, status, extra_data}} para cada match.
    """
    engine = get_mlwebhook_engine()

    # Construir la lista de resources esperados: '/shipments/12345'
    resources = [f"/shipments/{sid}" for sid in shipping_ids]

    with engine.connect() as conn:
        rows = conn.execute(
            text("""
                SELECT resource, title, status, extra_data
                FROM ml_previews
                WHERE resource = ANY(:resources)
            """),
            {"resources": resources},
        ).fetchall()

    result: Dict[str, Dict] = {}
    for row in rows:
        resource, title, status, extra_data = row
        # Extraer shipping_id de '/shipments/12345'
        sid = resource.replace("/shipments/", "")
        result[sid] = {
            "title": title,
            "status": status,
            "extra_data": extra_data or {},
        }

    return result


def re_enriquecer_desde_db(shipping_ids: List[str]) -> Dict[str, object]:
    """
    Re-enriquece etiquetas leyendo ml_previews directamente (sin HTTP).

    Para cada etiqueta en shipping_ids:
    1. Lee title + extra_data de ml_previews (batch query, rápido)
    2. Extrae lat/lng de extra_data.destination_lat/destination_lng
    3. Extrae direccion_completa de extra_data.destination_city + destination_state
    4. Detecta es_outlet buscando "outlet" en title
    5. Actualiza EtiquetaEnvio en la DB de pricing

    Args:
        shipping_ids: Lista de shipping_ids a re-enriquecer

    Returns:
        Dict con contadores y lista de IDs que no estaban en ml_previews.
    """
    if not shipping_ids:
        return {"actualizadas": 0, "sin_preview": 0, "total": 0, "ids_sin_preview": []}

    logger.info(f"Re-enriqueciendo {len(shipping_ids)} etiquetas desde ml_previews...")

    # 1) Leer previews en batch
    previews = _fetch_previews_batch(shipping_ids)
    logger.info(f"Encontrados {len(previews)}/{len(shipping_ids)} previews en ml_previews")

    # 2) Actualizar etiquetas en pricing DB
    db: Session = SessionLocal()
    actualizadas = 0
    sin_preview = 0
    ids_sin_preview: List[str] = []

    try:
        for sid in shipping_ids:
            preview = previews.get(sid)
            extra = preview.get("extra_data", {}) if preview else {}
            title = (preview.get("title", "") or "") if preview else ""

            # Si no hay preview o el preview está vacío (sin extra_data ni title),
            # mandarlo al fallback HTTP que sí tiene los datos completos de ML
            if not preview or (not extra and not title):
                sin_preview += 1
                ids_sin_preview.append(sid)
                continue

            # Extraer campos
            lat: Optional[float] = None
            lng: Optional[float] = None
            raw_lat = extra.get("destination_lat")
            raw_lng = extra.get("destination_lng")
            if raw_lat is not None and raw_lng is not None:
                try:
                    lat = float(raw_lat)
                    lng = float(raw_lng)
                    # Validar rango Argentina
                    if not (-55 <= lat <= -20 and -75 <= lng <= -50):
                        lat, lng = None, None
                except (ValueError, TypeError):
                    lat, lng = None, None

            city = extra.get("destination_city", "")
            state = extra.get("destination_state", "")
            direccion_parts = [p for p in [city, state] if p]
            direccion = ", ".join(direccion_parts) if direccion_parts else None

            es_outlet = "outlet" in title.lower() if title else False

            # Actualizar etiqueta
            etiqueta = db.query(EtiquetaEnvio).filter(EtiquetaEnvio.shipping_id == sid).first()
            if not etiqueta:
                continue

            cambio = False
            if lat is not None and lng is not None:
                etiqueta.latitud = lat
                etiqueta.longitud = lng
                cambio = True
            if direccion:
                etiqueta.direccion_completa = direccion
                cambio = True
            if es_outlet:
                etiqueta.es_outlet = True
                cambio = True

            if cambio:
                actualizadas += 1

        db.commit()
        logger.info(
            f"Re-enrichment DB completo: {actualizadas} actualizadas, "
            f"{sin_preview} sin preview, {len(shipping_ids)} total"
        )

    except Exception as e:
        db.rollback()
        logger.error(f"Error en re-enrichment: {e}")
        raise
    finally:
        db.close()

    return {
        "actualizadas": actualizadas,
        "sin_preview": sin_preview,
        "total": len(shipping_ids),
        "ids_sin_preview": ids_sin_preview,
    }


async def re_enriquecer_por_http(shipping_ids: List[str]) -> Dict[str, int]:
    """
    Fallback: re-enriquece etiquetas vía HTTP al proxy ml-webhook (1 request c/u).

    Se usa para los shipping_ids que no están en ml_previews.
    Más lento (~200ms por etiqueta) pero funciona siempre.

    Args:
        shipping_ids: Lista de shipping_ids a enriquecer por HTTP

    Returns:
        Dict con contadores: {"actualizadas": N, "errores": N, "total": N}
    """
    if not shipping_ids:
        return {"actualizadas": 0, "errores": 0, "total": 0}

    logger.info(f"Fallback HTTP: enriqueciendo {len(shipping_ids)} etiquetas...")

    db: Session = SessionLocal()
    actualizadas = 0
    errores = 0

    try:
        for shipping_id in shipping_ids:
            try:
                data = await fetch_shipment_data(shipping_id)
                if not data:
                    errores += 1
                    continue

                lat, lng = extraer_coordenadas(data)
                direccion = extraer_direccion_completa(data)
                comentario = extraer_comentario_direccion(data)
                es_outlet = extraer_es_outlet(data)

                if lat is not None or direccion or comentario or es_outlet:
                    etiqueta = db.query(EtiquetaEnvio).filter(EtiquetaEnvio.shipping_id == shipping_id).first()
                    if etiqueta:
                        if lat is not None and lng is not None:
                            etiqueta.latitud = lat
                            etiqueta.longitud = lng
                        if direccion:
                            etiqueta.direccion_completa = direccion
                        if comentario:
                            etiqueta.direccion_comentario = comentario
                        if es_outlet:
                            etiqueta.es_outlet = True
                        actualizadas += 1

                await asyncio.sleep(0.05)

            except Exception as e:
                logger.error(f"Fallback HTTP error para {shipping_id}: {e}")
                errores += 1

        db.commit()
        logger.info(f"Fallback HTTP completo: {actualizadas}/{len(shipping_ids)} OK, {errores} errores")

    except Exception as e:
        db.rollback()
        logger.error(f"Error en commit fallback HTTP: {e}")
        raise
    finally:
        db.close()

    return {
        "actualizadas": actualizadas,
        "errores": errores,
        "total": len(shipping_ids),
    }
