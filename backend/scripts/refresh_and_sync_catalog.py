#!/usr/bin/env python
"""
Script completo para actualizar catalog status:
1. Consulta price_to_win en ml-webhook (actualiza ml_previews)
2. Sincroniza ml_previews -> ml_catalog_status en pricing
"""
import sys
import os
import asyncio
import httpx
from typing import List

# Agregar el directorio backend al path para imports
backend_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, backend_dir)

# Cargar variables de entorno del .env
from dotenv import load_dotenv
dotenv_path = os.path.join(backend_dir, '.env')
load_dotenv(dotenv_path)

from sqlalchemy import create_engine, text
from app.core.database import SessionLocal
from app.models.mercadolibre_item_publicado import MercadoLibreItemPublicado
from app.models.ml_catalog_status import MLCatalogStatus
from datetime import datetime
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# URL del ml-webhook
ML_WEBHOOK_URL = os.getenv("ML_WEBHOOK_URL", "https://ml-webhook.gaussonline.com.ar")

# URL de BD pricing
DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    logger.error("❌ No se encontró DATABASE_URL en las variables de entorno")
    sys.exit(1)

# Construir URL para ml_webhook DB
import re
match = re.match(r'postgresql://([^:]+):([^@]+)@([^/]+)/(.+)', DATABASE_URL)
if match:
    user, password, host, db = match.groups()
    ML_WEBHOOK_DB_URL = f"postgresql://{user}:{password}@{host}/mlwebhook"
else:
    logger.error("❌ No se pudo parsear DATABASE_URL")
    sys.exit(1)


async def refresh_ml_previews(mla_list: List[str], batch_size: int = 50):
    """
    Consulta el ml-webhook para actualizar ml_previews con price_to_win
    Procesa en batches para no saturar la API
    """
    logger.info(f"🔄 Actualizando ml_previews para {len(mla_list)} MLAs...")

    actualizados = 0
    errores = 0

    async with httpx.AsyncClient(timeout=30.0) as client:
        for i in range(0, len(mla_list), batch_size):
            batch = mla_list[i:i + batch_size]

            for mla in batch:
                try:
                    resource = f"/items/{mla}/price_to_win?version=v2"
                    response = await client.get(
                        f"{ML_WEBHOOK_URL}/api/ml/preview",
                        params={"resource": resource}
                    )

                    if response.status_code == 200:
                        actualizados += 1
                        if actualizados % 100 == 0:
                            logger.info(f"  ✓ {actualizados}/{len(mla_list)} actualizados")
                    else:
                        logger.warning(f"  ⚠ {mla}: HTTP {response.status_code}")
                        errores += 1

                except Exception as e:
                    logger.error(f"  ❌ Error actualizando {mla}: {e}")
                    errores += 1

            # Pequeña pausa entre batches
            await asyncio.sleep(0.5)

    logger.info(f"✅ ml_previews actualizados: {actualizados}, errores: {errores}")
    return actualizados, errores


def sync_catalog_status():
    """
    Sincroniza el estado de competencia desde ml_previews a ml_catalog_status
    """
    db_pricing = SessionLocal()

    try:
        # Obtener publicaciones de catálogo desde itempublicados
        query = db_pricing.query(MercadoLibreItemPublicado).filter(
            MercadoLibreItemPublicado.mlp_catalog_listing == True,
            MercadoLibreItemPublicado.mlp_catalog_product_id.isnot(None)
        )

        publicaciones = query.all()
        logger.info(f"📦 Encontradas {len(publicaciones)} publicaciones de catálogo")

        if not publicaciones:
            logger.info("No hay publicaciones de catálogo para sincronizar")
            return 0, 0

        # Crear lista de MLAs
        mla_list = [pub.mlp_publicationID for pub in publicaciones]

        # PASO 1: Actualizar ml_previews consultando la API
        logger.info("\n" + "="*60)
        logger.info("PASO 1: Actualizando datos en ml-webhook")
        logger.info("="*60)
        actualizados, errores_api = asyncio.run(refresh_ml_previews(mla_list))

        # PASO 2: Sincronizar desde ml_previews a pricing
        logger.info("\n" + "="*60)
        logger.info("PASO 2: Sincronizando ml_previews → pricing")
        logger.info("="*60)

        sincronizadas = 0
        sin_datos = 0
        errores = []

        # Conectar a la BD del webhook
        engine_webhook = create_engine(ML_WEBHOOK_DB_URL)

        with engine_webhook.connect() as conn_webhook:
            # Hacer una sola query para todos los MLAs
            results = conn_webhook.execute(
                text("""
                    SELECT
                        SUBSTRING(resource FROM '/items/(.+)/price_to_win') as mla,
                        price,
                        status,
                        winner,
                        winner_price
                    FROM ml_previews
                    WHERE resource LIKE '/items/%/price_to_win%'
                    AND SUBSTRING(resource FROM '/items/(.+)/price_to_win') = ANY(:mla_list)
                """),
                {"mla_list": mla_list}
            ).fetchall()

            logger.info(f"Encontrados {len(results)} registros con status en ml_previews")

            # Crear diccionario de resultados
            results_dict = {}
            for row in results:
                mla, price, status, winner, winner_price = row
                if status:  # Solo si tiene status
                    results_dict[mla] = {
                        'price': price,
                        'status': status,
                        'winner': winner,
                        'winner_price': winner_price
                    }

            # Procesar cada publicación
            fecha_consulta = datetime.now()

            for pub in publicaciones:
                try:
                    mla = pub.mlp_publicationID

                    if mla not in results_dict:
                        sin_datos += 1
                        continue

                    data = results_dict[mla]

                    # Guardar en base de datos pricing
                    catalog_status = MLCatalogStatus(
                        mla=mla,
                        catalog_product_id=pub.mlp_catalog_product_id,
                        status=data['status'],
                        current_price=float(data['price']) if data['price'] else None,
                        price_to_win=None,
                        visit_share=None,
                        consistent=None,
                        competitors_sharing_first_place=None,
                        winner_mla=data['winner'],
                        winner_price=float(data['winner_price']) if data['winner_price'] else None,
                        fecha_consulta=fecha_consulta
                    )

                    db_pricing.add(catalog_status)
                    sincronizadas += 1

                    if sincronizadas % 500 == 0:
                        logger.info(f"✓ {sincronizadas} sincronizadas")

                except Exception as e:
                    logger.error(f"Error sincronizando {pub.mlp_publicationID}: {e}")
                    errores.append(f"{pub.mlp_publicationID}: {str(e)}")

        engine_webhook.dispose()
        db_pricing.commit()

        logger.info(f"\n{'='*60}")
        logger.info(f"RESUMEN FINAL:")
        logger.info(f"{'='*60}")
        logger.info(f"  📊 Total publicaciones de catálogo: {len(publicaciones)}")
        logger.info(f"  🔄 Actualizaciones en ml-webhook: {actualizados}")
        logger.info(f"  ✅ Sincronizadas a pricing: {sincronizadas}")
        logger.info(f"  ⚠️  Sin datos en webhook: {sin_datos}")
        logger.info(f"  ❌ Errores API: {errores_api}")
        logger.info(f"  ❌ Errores sync: {len(errores)}")

        if errores[:5]:
            logger.error(f"\nPrimeros errores de sincronización:")
            for err in errores[:5]:
                logger.error(f"  - {err}")

        logger.info(f"{'='*60}\n")

        return sincronizadas, len(errores)

    finally:
        db_pricing.close()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description='Actualiza ml-webhook y sincroniza catalog status a pricing'
    )

    args = parser.parse_args()

    try:
        sync_catalog_status()
    except Exception as e:
        logger.error(f"❌ Error fatal: {e}", exc_info=True)
        sys.exit(1)
