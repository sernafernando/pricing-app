"""
Script para sincronizar TODAS las publicaciones de MercadoLibre
Procesa en batches para evitar timeouts con grandes volúmenes

Estrategia:
- Sincronización completa: 1 vez al día (este script - TODAS las publicaciones)
- Sincronización incremental: cada hora (sync_ml_publications_incremental.py - solo ACTIVAS)

Ejecutar:
    cd /var/www/html/pricing-app/backend
    python -m app.scripts.sync_ml_publications_full
"""

import sys
import os
from pathlib import Path

if __name__ == "__main__":
    backend_path = Path(__file__).resolve().parent.parent.parent
    if str(backend_path) not in sys.path:
        sys.path.insert(0, str(backend_path))
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
from app.models.mercadolibre_item_publicado import MercadoLibreItemPublicado

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


async def obtener_todos_mla_ids(db: Session) -> list:
    """
    Obtiene TODOS los MLA IDs de todas las publicaciones en mercadolibre_items_publicados
    """
    print("Obteniendo TODOS los MLA IDs...")

    mla_ids = db.query(MercadoLibreItemPublicado.mlp_publicationID).filter(
        MercadoLibreItemPublicado.mlp_publicationID.isnot(None)
    ).distinct().all()

    ids = [row[0] for row in mla_ids if row[0]]
    print(f"✓ Encontradas {len(ids)} publicaciones TOTALES para sincronizar")

    return ids


async def procesar_batch(ids_batch: list, db: Session, batch_num: int, total_batches: int):
    """Procesa un batch de MLA IDs"""
    chunk_size = 20  # ML API permite hasta 20 items por request
    saved = 0
    updated = 0
    errors = 0
    errores_detalle = []

    today = datetime.now().date()

    for i in range(0, len(ids_batch), chunk_size):
        chunk = ids_batch[i:i + chunk_size]
        ids_str = ",".join(chunk)

        # Llamada a la API (si falla, loguear y seguir con el siguiente chunk)
        try:
            batch = await call_meli(f"/items?ids={ids_str}")
        except Exception as e:
            errors += len(chunk)
            errores_detalle.append(f"  ⚠️  API error chunk [{chunk[0]}...{chunk[-1]}]: {str(e)[:100]}")
            continue

        # Procesar cada publicación INDIVIDUALMENTE
        for item_wrapper in batch:
            mla_id = None
            try:
                item = item_wrapper.get("body")
                if not item:
                    # ML devolvió error para esta publicación específica
                    error_status = item_wrapper.get("code", "?")
                    error_mla = item_wrapper.get("body", {})
                    if isinstance(error_mla, dict):
                        mla_id = error_mla.get("id", "desconocido")
                    errors += 1
                    errores_detalle.append(f"  ⚠️  {mla_id}: ML respondió sin body (code={error_status})")
                    continue

                mla_id = item.get("id")

                # Buscar campaña de cuotas
                campaign = None
                sale_terms = item.get("sale_terms", [])
                for term in sale_terms:
                    if term.get("id") == "INSTALLMENTS_CAMPAIGN":
                        campaign = term.get("value_name")
                        break

                # Lógica condicional de campaña
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

                # Intentar obtener item_id del SKU
                item_id = None
                if seller_sku and seller_sku.isdigit():
                    item_id = int(seller_sku)

                # Verificar si ya existe un snapshot del día de hoy
                existing = db.query(MLPublicationSnapshot).filter(
                    MLPublicationSnapshot.mla_id == mla_id,
                    func.date(MLPublicationSnapshot.snapshot_date) == today
                ).first()

                if existing:
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
                    db.commit()
                    updated += 1
                else:
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
                    db.commit()
                    saved += 1

            except Exception as e:
                db.rollback()
                errors += 1
                errores_detalle.append(f"  ⚠️  {mla_id or 'desconocido'}: {str(e)[:120]}")
                continue

        # Pequeña pausa para no saturar la API
        await asyncio.sleep(0.3)

    return saved, updated, errors, errores_detalle


async def sync_ml_publications_full(db: Session = None):
    """
    Sincronización COMPLETA de TODAS las publicaciones
    Procesa en batches grandes para manejar el volumen
    """
    print("=" * 70)
    print("SINCRONIZACIÓN COMPLETA - TODAS LAS PUBLICACIONES")
    print("=" * 70)
    print(f"Inicio: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print()

    db_was_provided = db is not None
    if not db:
        db = SessionLocal()

    try:
        # 1. Obtener TODOS los MLA IDs
        all_ids = await obtener_todos_mla_ids(db)

        if not all_ids:
            print("⚠️  No hay publicaciones para sincronizar")
            return 0, 0, 0

        # 2. Dividir en batches grandes (1000 por batch)
        batch_size = 1000
        total_batches = (len(all_ids) + batch_size - 1) // batch_size

        print(f"Procesando en {total_batches} batches de {batch_size} publicaciones...")
        print()

        total_saved = 0
        total_updated = 0
        total_errors = 0
        todos_los_errores = []

        for batch_num in range(total_batches):
            start_idx = batch_num * batch_size
            end_idx = min(start_idx + batch_size, len(all_ids))
            batch_ids = all_ids[start_idx:end_idx]

            print(f"📦 Batch {batch_num + 1}/{total_batches} ({len(batch_ids)} publicaciones)...")

            saved, updated, errors, errores_detalle = await procesar_batch(
                batch_ids, db, batch_num + 1, total_batches
            )

            total_saved += saved
            total_updated += updated
            total_errors += errors
            todos_los_errores.extend(errores_detalle)

            print(f"   ✓ Nuevos: {saved}, Actualizados: {updated}, Errores: {errors}")

            # Mostrar errores del batch si los hay
            for err in errores_detalle:
                print(err)

            # Pausa entre batches
            if batch_num < total_batches - 1:
                await asyncio.sleep(1)

        print()
        print("=" * 70)
        print("RESUMEN SINCRONIZACIÓN COMPLETA")
        print("=" * 70)
        print(f"Total nuevos: {total_saved}")
        print(f"Total actualizados: {total_updated}")
        print(f"Total errores: {total_errors}")
        print(f"Total procesados OK: {total_saved + total_updated}")

        if todos_los_errores:
            print()
            print(f"DETALLE DE ERRORES ({len(todos_los_errores)}):")
            for err in todos_los_errores:
                print(err)

        print()
        print(f"Fin: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print("=" * 70)

        return total_saved, total_updated, total_errors

    except Exception as e:
        print(f"❌ Error durante la sincronización: {str(e)}")
        raise
    finally:
        if not db_was_provided:
            db.close()


if __name__ == "__main__":
    asyncio.run(sync_ml_publications_full())
