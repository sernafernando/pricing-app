#!/usr/bin/env python
"""
Script para sincronizar el estado de competencia en catálogos de MercadoLibre
"""
import asyncio
import sys
import os

# Agregar el directorio backend al path para imports
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from sqlalchemy.orm import Session
from app.core.database import SessionLocal
from app.models.publicacion_ml import PublicacionML
from app.models.ml_catalog_status import MLCatalogStatus
from app.services.ml_webhook_client import ml_webhook_client
from datetime import datetime
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def sync_catalog_status(mla_id: str = None):
    """
    Sincroniza el estado de competencia en catálogos para publicaciones de ML

    Args:
        mla_id: Si se proporciona, sincroniza solo ese item. Si no, sincroniza todos.
    """
    db = SessionLocal()

    try:
        # Obtener publicaciones a sincronizar
        query = db.query(PublicacionML)

        if mla_id:
            query = query.filter(PublicacionML.mla == mla_id)

        publicaciones = query.all()

        logger.info(f"Sincronizando {len(publicaciones)} publicaciones...")

        sincronizadas = 0
        errores = []

        for pub in publicaciones:
            try:
                logger.info(f"Procesando {pub.mla}...")

                # Obtener preview básico primero para ver si tiene catálogo
                preview = await ml_webhook_client.get_item_preview(pub.mla)

                if not preview or not preview.get("catalog_product_id"):
                    logger.debug(f"{pub.mla} no tiene catalog_product_id, saltando...")
                    continue

                # Tiene catálogo, obtener price_to_win
                ptw_data = await ml_webhook_client.get_item_preview(pub.mla, include_price_to_win=True)

                if not ptw_data:
                    logger.warning(f"No se pudo obtener price_to_win para {pub.mla}")
                    continue

                # Guardar en base de datos
                catalog_status = MLCatalogStatus(
                    mla=pub.mla,
                    catalog_product_id=ptw_data.get("catalog_product_id"),
                    status=ptw_data.get("status"),
                    current_price=float(ptw_data.get("price", 0)) if ptw_data.get("price") else None,
                    price_to_win=float(ptw_data.get("price_to_win", 0)) if ptw_data.get("price_to_win") else None,
                    visit_share=ptw_data.get("visit_share"),
                    consistent=ptw_data.get("consistent"),
                    competitors_sharing_first_place=ptw_data.get("competitors_sharing_first_place"),
                    winner_mla=ptw_data.get("winner"),
                    winner_price=float(ptw_data.get("winner_price", 0)) if ptw_data.get("winner_price") else None,
                    fecha_consulta=datetime.now()
                )

                db.add(catalog_status)
                sincronizadas += 1

                logger.info(f"✓ {pub.mla} - Status: {catalog_status.status}")

            except Exception as e:
                logger.error(f"Error sincronizando {pub.mla}: {e}")
                errores.append(f"{pub.mla}: {str(e)}")

        db.commit()

        logger.info(f"\n{'='*60}")
        logger.info(f"Sincronización completada:")
        logger.info(f"  - Total publicaciones: {len(publicaciones)}")
        logger.info(f"  - Sincronizadas: {sincronizadas}")
        logger.info(f"  - Errores: {len(errores)}")

        if errores[:5]:  # Mostrar primeros 5 errores
            logger.error(f"\nPrimeros errores:")
            for err in errores[:5]:
                logger.error(f"  - {err}")

        logger.info(f"{'='*60}\n")

    finally:
        db.close()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description='Sincronizar catalog status de MercadoLibre')
    parser.add_argument('--mla', type=str, help='MLA específico a sincronizar (opcional)')

    args = parser.parse_args()

    asyncio.run(sync_catalog_status(args.mla))
