"""
Script para sincronizar publicaciones de MercadoLibre de forma INCREMENTAL
Solo actualiza publicaciones ACTIVAS (optval_statusId = 2)

Estrategia:
- Sincronización completa: 1 vez al día (sync_ml_publications_full.py - TODAS en batches)
- Sincronización incremental: cada hora (este script - solo ACTIVAS)
"""

import sys
import os
from pathlib import Path

# Cargar variables de entorno desde .env ANTES de importar settings
if __name__ == "__main__":
    backend_path = Path(__file__).resolve().parent.parent.parent
    if str(backend_path) not in sys.path:
        sys.path.insert(0, str(backend_path))
    from dotenv import load_dotenv

    env_path = backend_path / ".env"
    load_dotenv(dotenv_path=env_path)

import asyncio
import httpx
from datetime import datetime
from sqlalchemy.orm import Session
from sqlalchemy import func
from app.core.database import SessionLocal
from app.core.config import settings
from app.models.ml_publication_snapshot import MLPublicationSnapshot
from app.models.mercadolibre_item_publicado import MercadoLibreItemPublicado
from app.scripts.sync_ml_publications_full import (
    extraer_datos_publicacion,
    sanitizar_datos_ml,
    aplicar_snapshot,
    crear_snapshot,
)

# Tokens globales
ACCESS_TOKEN = None
REFRESH_TOKEN = settings.ML_REFRESH_TOKEN


async def refresh_access_token():
    """Refresca el access token usando el refresh token"""
    global ACCESS_TOKEN, REFRESH_TOKEN

    if not settings.ML_CLIENT_ID or not settings.ML_CLIENT_SECRET or not REFRESH_TOKEN:
        raise ValueError("Faltan credenciales de MercadoLibre en el .env")

    url = "https://api.mercadolibre.com/oauth/token"
    data = {
        "grant_type": "refresh_token",
        "client_id": settings.ML_CLIENT_ID,
        "client_secret": settings.ML_CLIENT_SECRET,
        "refresh_token": REFRESH_TOKEN,
    }

    async with httpx.AsyncClient() as client:
        response = await client.post(url, data=data)
        response.raise_for_status()
        tokens = response.json()

        ACCESS_TOKEN = tokens.get("access_token")
        if tokens.get("refresh_token"):
            REFRESH_TOKEN = tokens.get("refresh_token")

        print("✓ Token refrescado exitosamente")
        return ACCESS_TOKEN


async def call_meli(endpoint: str, retry=True):
    """Llamada a la API de MercadoLibre con manejo automático de tokens"""
    global ACCESS_TOKEN

    if not ACCESS_TOKEN:
        await refresh_access_token()

    url = f"https://api.mercadolibre.com{endpoint}"
    headers = {"Authorization": f"Bearer {ACCESS_TOKEN}"}

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(url, headers=headers)

        if response.status_code == 401 and retry:
            print("Token expirado, refrescando...")
            await refresh_access_token()
            return await call_meli(endpoint, retry=False)

        response.raise_for_status()
        return response.json()


async def obtener_mla_ids_activos(db: Session) -> list:
    """
    Obtiene los MLA IDs de publicaciones ACTIVAS (optval_statusId = 2)
    Solo sincroniza publicaciones que están activas en GBP
    """
    print("Obteniendo MLA IDs de publicaciones ACTIVAS...")

    # Obtener MLA IDs de publicaciones activas en mercadolibre_items_publicados
    mla_ids = (
        db.query(MercadoLibreItemPublicado.mlp_publicationID)
        .filter(MercadoLibreItemPublicado.optval_statusId == 2)
        .distinct()
        .all()
    )

    ids = [row[0] for row in mla_ids if row[0]]  # Filtrar nulos
    print(f"✓ Encontradas {len(ids)} publicaciones ACTIVAS para sincronizar")

    return ids


async def traer_detalles_batch(ids: list, db: Session):
    """Obtiene detalles de publicaciones en batches y los guarda en la DB"""
    chunk_size = 20
    total_saved = 0
    total_updated = 0
    total_errors = 0
    errores_detalle = []

    today = datetime.now().date()

    print(f"Procesando {len(ids)} publicaciones en batches de {chunk_size}...")

    for i in range(0, len(ids), chunk_size):
        chunk = ids[i : i + chunk_size]
        ids_str = ",".join(chunk)

        # Llamada a la API (si falla, loguear y seguir con el siguiente chunk)
        try:
            batch = await call_meli(f"/items?ids={ids_str}")
        except Exception as e:
            total_errors += len(chunk)
            errores_detalle.append(f"  ⚠️  API error chunk [{chunk[0]}...{chunk[-1]}]: {str(e)[:100]}")
            continue

        # Procesar cada publicación INDIVIDUALMENTE
        for item_wrapper in batch:
            mla_id = None
            try:
                item = item_wrapper.get("body")
                if not item:
                    error_status = item_wrapper.get("code", "?")
                    total_errors += 1
                    errores_detalle.append(f"  ⚠️  ML respondió sin body (code={error_status})")
                    continue

                mla_id = item.get("id")
                campaign, seller_sku, item_id = extraer_datos_publicacion(item)

                # Verificar si ya existe un snapshot del día de hoy para este MLA_ID
                existing = (
                    db.query(MLPublicationSnapshot)
                    .filter(
                        MLPublicationSnapshot.mla_id == mla_id, func.date(MLPublicationSnapshot.snapshot_date) == today
                    )
                    .first()
                )

                if existing:
                    aplicar_snapshot(existing, item, campaign, seller_sku, item_id)
                    db.commit()
                    total_updated += 1
                else:
                    db.add(crear_snapshot(mla_id, item, campaign, seller_sku, item_id))
                    db.commit()
                    total_saved += 1

            except Exception as e:
                db.rollback()
                total_errors += 1
                errores_detalle.append(f"  ⚠️  {mla_id or 'desconocido'}: {str(e)[:150]}")
                continue

        print(
            f"  Procesados {min(i + chunk_size, len(ids))}/{len(ids)} - Nuevos: {total_saved}, Actualizados: {total_updated}, Errores: {total_errors}"
        )

        # Pequeña pausa para no saturar la API
        await asyncio.sleep(0.5)

    print()
    print(
        f"✓ Sincronización incremental completada: {total_saved} nuevos, {total_updated} actualizados, {total_errors} errores"
    )

    if errores_detalle:
        print(f"\nDETALLE DE ERRORES ({len(errores_detalle)}):")
        for err in errores_detalle:
            print(err)

    return total_saved, total_updated


async def sync_ml_publications_incremental(db: Session = None):
    """
    Función principal de sincronización INCREMENTAL
    Solo actualiza publicaciones ACTIVAS (optval_statusId = 2)
    """
    print("=" * 60)
    print("SINCRONIZACIÓN INCREMENTAL - SOLO ACTIVAS")
    print("=" * 60)
    print(f"Inicio: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print()

    # Si no se proporciona una sesión, crear una nueva
    db_was_provided = db is not None
    if not db:
        db = SessionLocal()

    try:
        # 1. Obtener MLA IDs de publicaciones ACTIVAS
        ids = await obtener_mla_ids_activos(db)

        if not ids:
            print("⚠️  No hay publicaciones activas para sincronizar")
            return 0, 0

        # 2. Traer detalles y actualizar
        result = await traer_detalles_batch(ids, db)

        print()
        print(f"Fin: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print("=" * 60)

        return result

    except Exception as e:
        print(f"❌ Error durante la sincronización: {str(e)}")
        raise
    finally:
        # Solo cerrar la sesión si fue creada internamente
        if not db_was_provided:
            db.close()


if __name__ == "__main__":
    asyncio.run(sync_ml_publications_incremental())
