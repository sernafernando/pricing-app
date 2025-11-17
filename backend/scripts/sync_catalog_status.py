#!/usr/bin/env python
"""
Script para sincronizar el estado de competencia en catálogos de MercadoLibre
Consulta directamente la BD del ml-webhook para obtener los status actualizados
"""
import sys
import os

# Agregar el directorio backend al path para imports
backend_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, backend_dir)

# Cargar variables de entorno del .env (buscar en el directorio backend)
from dotenv import load_dotenv
dotenv_path = os.path.join(backend_dir, '.env')
load_dotenv(dotenv_path)

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session
from app.core.database import SessionLocal, engine
from app.models.mercadolibre_item_publicado import MercadoLibreItemPublicado
from app.models.ml_catalog_status import MLCatalogStatus
from datetime import datetime
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Obtener la URL de la BD pricing
DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    logger.error("❌ No se encontró DATABASE_URL en las variables de entorno")
    sys.exit(1)

# Construir URL para ml_webhook usando la misma conexión pero diferente DB
# Asumimos que mlwebhook está en el mismo servidor que pricing_db
import re
match = re.match(r'postgresql://([^:]+):([^@]+)@([^/]+)/(.+)', DATABASE_URL)
if match:
    user, password, host, db = match.groups()
    # Usar el mismo usuario/password/host pero DB mlwebhook
    ML_WEBHOOK_DB_URL = f"postgresql://{user}:{password}@{host}/mlwebhook"
    logger.info(f"Conectando a ml-webhook en: {host}/mlwebhook")
else:
    logger.error("❌ No se pudo parsear DATABASE_URL")
    sys.exit(1)


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

        # Conectar a la BD del webhook
        engine_webhook = create_engine(ML_WEBHOOK_DB_URL)

        logger.info("Consultando ml_previews...")

        with engine_webhook.connect() as conn_webhook:
            for pub in publicaciones:
                try:
                    mla = pub.mlp_publicationID

                    # Cada 100 items, mostrar progreso
                    if (sincronizadas + sin_datos + len(errores)) % 100 == 0:
                        total_proc = sincronizadas + sin_datos + len(errores)
                        logger.info(f"Progreso: {total_proc}/{len(publicaciones)} procesados (✓ {sincronizadas} sync)")

                    # Consultar ml_previews del webhook
                    resource_ptw = f"/items/{mla}/price_to_win?version=v2"

                    result = conn_webhook.execute(
                        text("""
                            SELECT price, status, winner, winner_price
                            FROM ml_previews
                            WHERE resource = :resource
                        """),
                        {"resource": resource_ptw}
                    ).fetchone()

                    if not result:
                        sin_datos += 1
                        continue

                    # Extraer datos
                    price, status, winner, winner_price = result

                    if not status:
                        sin_datos += 1
                        continue

                    # Guardar en base de datos pricing
                    catalog_status = MLCatalogStatus(
                        mla=mla,
                        catalog_product_id=pub.mlp_catalog_product_id,
                        status=status,
                        current_price=float(price) if price else None,
                        price_to_win=None,
                        visit_share=None,
                        consistent=None,
                        competitors_sharing_first_place=None,
                        winner_mla=winner,
                        winner_price=float(winner_price) if winner_price else None,
                        fecha_consulta=datetime.now()
                    )

                    db_pricing.add(catalog_status)
                    sincronizadas += 1

                    if sincronizadas % 100 == 0:
                        logger.info(f"✓ {sincronizadas} sincronizadas (último: {mla} - {status})")

                except Exception as e:
                    logger.error(f"Error sincronizando {pub.mlp_publicationID}: {e}")
                    errores.append(f"{pub.mlp_publicationID}: {str(e)}")

        engine_webhook.dispose()

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
