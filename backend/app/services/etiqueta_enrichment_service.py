"""
Servicio de enriquecimiento de etiquetas de envío con datos del ML Webhook.

Se ejecuta en background (asyncio.create_task) después del upload/scan.
Para cada etiqueta nueva, llama al ML webhook y guarda:
- latitud / longitud (coordenadas exactas del destinatario)
- direccion_completa (calle, ciudad, provincia formateada)
- direccion_comentario (notas del comprador: "puerta negra", "timbre 3B")

Usa una sesión de DB independiente para no bloquear la respuesta HTTP.
"""

import asyncio
import logging
from typing import List

from sqlalchemy.orm import Session

from app.core.database import SessionLocal
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
