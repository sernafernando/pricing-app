"""
Script para sincronizar publicaciones de MercadoLibre de forma INCREMENTAL
Actualiza solo las publicaciones que ya tenemos en snapshots (no busca nuevas)
Para hacer un sync completo de TODAS las publicaciones, usar sync_ml_publications.py

Estrategia:
- Sincronización completa: 1 vez al día (sync_ml_publications.py - trae todas las 14k+)
- Sincronización incremental: cada hora (este script - solo actualiza las que ya tenemos)
"""

import sys
import os
from pathlib import Path

# Cargar variables de entorno desde .env ANTES de importar settings
if __name__ == "__main__":
    backend_path = Path(__file__).resolve().parent.parent.parent
    from dotenv import load_dotenv
    env_path = backend_path / '.env'
    load_dotenv(dotenv_path=env_path)

import asyncio
import httpx
from datetime import datetime
from sqlalchemy.orm import Session
from sqlalchemy import func
from app.core.database import SessionLocal
from app.core.config import settings
from app.models.ml_publication_snapshot import MLPublicationSnapshot

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
        "refresh_token": REFRESH_TOKEN
    }

    async with httpx.AsyncClient() as client:
        response = await client.post(url, data=data)
        response.raise_for_status()
        tokens = response.json()

        ACCESS_TOKEN = tokens.get("access_token")
        if tokens.get("refresh_token"):
            REFRESH_TOKEN = tokens.get("refresh_token")

        print(f"✓ Token refrescado exitosamente")
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


async def obtener_mla_ids_del_snapshot(db: Session) -> list:
    """
    Obtiene los MLA IDs de las publicaciones que ya tenemos en snapshots
    Solo actualizaremos estas publicaciones (no busca nuevas)
    """
    print("Obteniendo MLA IDs de snapshots existentes...")

    # Obtener todos los MLA IDs únicos que tenemos en la base
    mla_ids = db.query(MLPublicationSnapshot.mla_id).distinct().all()

    ids = [row[0] for row in mla_ids]
    print(f"✓ Encontrados {len(ids)} MLA IDs en snapshots para actualizar")

    return ids


async def traer_detalles_batch(ids: list, db: Session):
    """Obtiene detalles de publicaciones en batches y los guarda en la DB"""
    chunk_size = 20
    total_saved = 0
    total_updated = 0

    print(f"Procesando {len(ids)} publicaciones en batches de {chunk_size}...")

    for i in range(0, len(ids), chunk_size):
        chunk = ids[i:i + chunk_size]
        ids_str = ",".join(chunk)

        try:
            batch = await call_meli(f"/items?ids={ids_str}")

            for item_wrapper in batch:
                item = item_wrapper.get("body")
                if not item:
                    continue

                # Buscar campaña de cuotas
                campaign = None
                sale_terms = item.get("sale_terms", [])
                for term in sale_terms:
                    if term.get("id") == "INSTALLMENTS_CAMPAIGN":
                        campaign = term.get("value_name")
                        break

                # Lógica condicional de campaña según las especificaciones
                if item.get("listing_type_id") == "gold_special":
                    campaign = "Clásica"
                elif not campaign and item.get("listing_type_id") == "gold_pro":
                    campaign = "6x_campaign"
                elif not campaign:
                    campaign = "-"

                # Buscar SKU
                seller_sku = None
                attributes = item.get("attributes", [])
                for attr in attributes:
                    if attr.get("id") == "SELLER_SKU":
                        seller_sku = attr.get("value_id")
                        break

                # Intentar obtener item_id del SKU (si es numérico)
                item_id = None
                if seller_sku and seller_sku.isdigit():
                    item_id = int(seller_sku)

                mla_id = item.get("id")

                # Verificar si ya existe un snapshot del día de hoy para este MLA_ID
                today = datetime.now().date()
                existing = db.query(MLPublicationSnapshot).filter(
                    MLPublicationSnapshot.mla_id == mla_id,
                    func.date(MLPublicationSnapshot.snapshot_date) == today
                ).first()

                if existing:
                    # Actualizar el existente
                    existing.title = item.get("title")
                    existing.price = item.get("price")
                    existing.base_price = item.get("base_price")
                    existing.available_quantity = item.get("available_quantity")
                    existing.sold_quantity = item.get("sold_quantity")
                    existing.status = item.get("status")
                    existing.listing_type_id = item.get("listing_type_id")
                    existing.permalink = item.get("permalink")
                    existing.installments_campaign = campaign
                    existing.seller_sku = seller_sku
                    existing.item_id = item_id
                    existing.snapshot_date = datetime.now()
                    total_updated += 1
                else:
                    # Crear nuevo registro de snapshot
                    snapshot = MLPublicationSnapshot(
                        mla_id=mla_id,
                        title=item.get("title"),
                        price=item.get("price"),
                        base_price=item.get("base_price"),
                        available_quantity=item.get("available_quantity"),
                        sold_quantity=item.get("sold_quantity"),
                        status=item.get("status"),
                        listing_type_id=item.get("listing_type_id"),
                        permalink=item.get("permalink"),
                        installments_campaign=campaign,
                        seller_sku=seller_sku,
                        item_id=item_id,
                        snapshot_date=datetime.now()
                    )
                    db.add(snapshot)
                    total_saved += 1

            # Commit cada batch
            db.commit()
            print(f"  Procesados {min(i + chunk_size, len(ids))}/{len(ids)} - Nuevos: {total_saved}, Actualizados: {total_updated}")

        except Exception as e:
            print(f"  Error en batch {i//chunk_size + 1}: {str(e)}")
            db.rollback()
            continue

        # Pequeña pausa para no saturar la API
        await asyncio.sleep(0.5)

    print(f"✓ Sincronización incremental completada: {total_saved} nuevos, {total_updated} actualizados")
    return total_saved, total_updated


async def sync_ml_publications_incremental(db: Session = None):
    """
    Función principal de sincronización INCREMENTAL
    Actualiza TODAS las publicaciones que ya están en nuestros snapshots
    No importa si son viejas o nuevas, se actualizan todas
    """
    print("=" * 60)
    print("SINCRONIZACIÓN INCREMENTAL DE PUBLICACIONES ML")
    print("=" * 60)
    print(f"Inicio: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print()

    # Si no se proporciona una sesión, crear una nueva
    db_was_provided = db is not None
    if not db:
        db = SessionLocal()

    try:
        # 1. Obtener MLA IDs que ya tenemos en snapshots
        ids = await obtener_mla_ids_del_snapshot(db)

        if not ids:
            print("⚠️  No hay snapshots previos, ejecuta sync_ml_publications.py primero")
            return 0, 0

        # 2. Limpiar snapshots del día de hoy para reemplazarlos
        today = datetime.now().date()
        deleted = db.query(MLPublicationSnapshot).filter(
            func.date(MLPublicationSnapshot.snapshot_date) == today
        ).delete()
        db.commit()
        if deleted > 0:
            print(f"Eliminados {deleted} snapshots del día de hoy para reemplazar")
            print()

        # 3. Traer detalles y actualizar TODAS
        result = await traer_detalles_batch(ids, db)

        return result

    except Exception as e:
        print(f"❌ Error durante la sincronización: {str(e)}")
        raise
    finally:
        # Solo cerrar la sesión si fue creada internamente
        if not db_was_provided:
            db.close()

    print()
    print(f"Fin: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(sync_ml_publications_incremental())
