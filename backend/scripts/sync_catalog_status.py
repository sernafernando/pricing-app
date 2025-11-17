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

# Configuración de la BD del ml-webhook
ML_WEBHOOK_DB_URL = os.getenv("ML_WEBHOOK_DB_URL")

if not ML_WEBHOOK_DB_URL:
    logger.error("❌ No se encontró ML_WEBHOOK_DB_URL en las variables de entorno")
    logger.error("Agregá esta línea al archivo .env:")
    logger.error("ML_WEBHOOK_DB_URL=postgresql://usuario:password@host:puerto/mlwebhook")
    sys.exit(1)


def sync_catalog_status(mla_id: str = None):
    """
    Sincroniza el estado de competencia en catálogos para publicaciones de ML
    Consulta la tabla ml_previews del ml-webhook para obtener los status

    Args:
        mla_id: Si se proporciona, sincroniza solo ese item. Si no, sincroniza todos.
    """
    db_pricing = SessionLocal()
    engine_webhook = create_engine(ML_WEBHOOK_DB_URL)

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

        with engine_webhook.connect() as conn_webhook:
            for pub in publicaciones:
                try:
                    mla = pub.mlp_publicationID
                    logger.info(f"Procesando {mla}...")

                    # Consultar ml_previews del webhook
                    # Buscar el resource que tenga price_to_win
                    resource_ptw = f"/items/{mla}/price_to_win?version=v2"

                    result = conn_webhook.execute(
                        text("""
                            SELECT
                                title, price, currency_id, thumbnail,
                                winner, winner_price, status, brand
                            FROM ml_previews
                            WHERE resource = :resource
                        """),
                        {"resource": resource_ptw}
                    ).fetchone()

                    if not result:
                        logger.debug(f"{mla} no tiene datos en ml_previews, saltando...")
                        sin_datos += 1
                        continue

                    # Extraer datos
                    title, price, currency_id, thumbnail, winner, winner_price, status, brand = result

                    if not status:
                        logger.debug(f"{mla} no tiene status en ml_previews")
                        sin_datos += 1
                        continue

                    # Guardar en base de datos pricing
                    catalog_status = MLCatalogStatus(
                        mla=mla,
                        catalog_product_id=pub.mlp_catalog_product_id,
                        status=status,
                        current_price=float(price) if price else None,
                        price_to_win=None,  # Este dato no está en ml_previews
                        visit_share=None,
                        consistent=None,
                        competitors_sharing_first_place=None,
                        winner_mla=winner,
                        winner_price=float(winner_price) if winner_price else None,
                        fecha_consulta=datetime.now()
                    )

                    db_pricing.add(catalog_status)
                    sincronizadas += 1

                    logger.info(f"✓ {mla} - Status: {status}")

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
        engine_webhook.dispose()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description='Sincronizar catalog status de MercadoLibre')
    parser.add_argument('--mla', type=str, help='MLA específico a sincronizar (opcional)')

    args = parser.parse_args()

    sync_catalog_status(args.mla)
