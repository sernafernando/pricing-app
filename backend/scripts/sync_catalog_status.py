#!/usr/bin/env python
"""
Script para sincronizar el estado de competencia en catálogos de MercadoLibre
Consulta directamente la BD del ml-webhook para obtener los status actualizados
"""
import sys
import os

# Agregar el directorio backend al path para imports
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# Cargar variables de entorno del .env
from dotenv import load_dotenv
load_dotenv()

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session
from app.core.database import SessionLocal
from app.models.mercadolibre_item_publicado import MercadoLibreItemPublicado
from app.models.ml_catalog_status import MLCatalogStatus
from datetime import datetime
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def sync_catalog_status(mla_id: str = None):
    """
    Sincroniza el estado de competencia en catálogos para publicaciones de ML
    Consulta la API del webhook que actualiza ml_previews automáticamente

    Args:
        mla_id: Si se proporciona, sincroniza solo ese item. Si no, sincroniza todos.
    """
    db_pricing = SessionLocal()

    try:
        # Obtener publicaciones de catálogo desde itempublicados
        query = db_pricing.query(MercadoLibreItemPublicado).filter(
            MercadoLibreItemPublicado.mlp_catalog_listing == True,
            MercadoLibreItemPublicado.mlp_catalog_product_id.isnot(None)
        )

        if mla_id:
            query = query.filter(MercadoLibreItemPublicado.mlp_publicationID == mla_id)

        publicaciones = query.all()

        logger.info(f"Encontradas {len(publicaciones)} publicaciones de catálogo...")

        sincronizadas = 0
        sin_datos = 0
        errores = []

        # Usar requests para consultar el webhook API (que guarda en ml_previews)
        import requests

        ML_WEBHOOK_BASE_URL = "https://ml-webhook.gaussonline.com.ar"

        for pub in publicaciones:
            try:
                mla = pub.mlp_publicationID

                # Cada 100 items, mostrar progreso
                if (sincronizadas + sin_datos) % 100 == 0:
                    logger.info(f"Progreso: {sincronizadas + sin_datos}/{len(publicaciones)} procesados...")

                # Consultar API del webhook (esto guardará en ml_previews automáticamente)
                resource_ptw = f"/items/{mla}/price_to_win?version=v2"

                try:
                    response = requests.get(
                        f"{ML_WEBHOOK_BASE_URL}/api/ml/preview",
                        params={"resource": resource_ptw},
                        timeout=5
                    )

                    if response.status_code == 404:
                        logger.debug(f"{mla} no encontrado en ML")
                        sin_datos += 1
                        continue

                    response.raise_for_status()
                    preview_data = response.json()

                except requests.exceptions.RequestException as e:
                    logger.warning(f"Error consultando webhook para {mla}: {e}")
                    sin_datos += 1
                    continue

                # Extraer status del preview
                status = preview_data.get("status")

                if not status:
                    logger.debug(f"{mla} no tiene status")
                    sin_datos += 1
                    continue

                # Guardar en base de datos pricing
                catalog_status = MLCatalogStatus(
                    mla=mla,
                    catalog_product_id=pub.mlp_catalog_product_id,
                    status=status,
                    current_price=float(preview_data.get("price", 0)) if preview_data.get("price") else None,
                    price_to_win=None,
                    visit_share=None,
                    consistent=None,
                    competitors_sharing_first_place=None,
                    winner_mla=preview_data.get("winner"),
                    winner_price=float(preview_data.get("winner_price", 0)) if preview_data.get("winner_price") else None,
                    fecha_consulta=datetime.now()
                )

                db_pricing.add(catalog_status)
                sincronizadas += 1

                if sincronizadas % 10 == 0:
                    logger.info(f"✓ {sincronizadas} sincronizadas (último: {mla} - {status})")

            except Exception as e:
                logger.error(f"Error sincronizando {pub.mlp_publicationID}: {e}")
                errores.append(f"{pub.mlp_publicationID}: {str(e)}")

        db_pricing.commit()

        logger.info(f"\n{'='*60}")
        logger.info(f"Sincronización completada:")
        logger.info(f"  - Total publicaciones de catálogo: {len(publicaciones)}")
        logger.info(f"  - Sincronizadas: {sincronizadas}")
        logger.info(f"  - Sin datos en webhook: {sin_datos}")
        logger.info(f"  - Errores: {len(errores)}")

        if errores[:5]:  # Mostrar primeros 5 errores
            logger.error(f"\nPrimeros errores:")
            for err in errores[:5]:
                logger.error(f"  - {err}")

        logger.info(f"{'='*60}\n")

    finally:
        db_pricing.close()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description='Sincronizar catalog status de MercadoLibre')
    parser.add_argument('--mla', type=str, help='MLA específico a sincronizar (opcional)')

    args = parser.parse_args()

    sync_catalog_status(args.mla)
