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

    env_path = backend_path / ".env"
    load_dotenv(dotenv_path=env_path)

import asyncio
import httpx
from datetime import datetime
from sqlalchemy.orm import Session
from sqlalchemy import func
from app.core.database import SessionLocal
from app.models.ml_publication_snapshot import MLPublicationSnapshot
from app.models.mercadolibre_item_publicado import MercadoLibreItemPublicado
from app.services.ml_api_client import MercadoLibreAPIClient

# El access token vive en la DB del ml-webhook (única fuente de OAuth para ML);
# este cliente solo lo lee/cachea, nunca hace el intercambio de refresh_token.
_ml_client = MercadoLibreAPIClient()


async def call_meli(http_client: httpx.AsyncClient, endpoint: str, retry=True):
    """Llamada a la API de MercadoLibre con manejo automático de tokens"""
    token = await _ml_client.get_access_token()

    url = f"https://api.mercadolibre.com{endpoint}"
    headers = {"Authorization": f"Bearer {token}"}

    response = await http_client.get(url, headers=headers)

    if response.status_code == 401 and retry:
        print("Token expirado, releyendo desde la DB de ml-webhook...")
        _ml_client.invalidate_cached_token()
        return await call_meli(http_client, endpoint, retry=False)

    response.raise_for_status()
    return response.json()


def safe_int(value):
    """Convierte un valor a int de forma segura. Retorna None si no es posible."""
    if value is None:
        return None
    try:
        return int(value)
    except (ValueError, TypeError):
        return None


def safe_numeric(value):
    """Convierte un valor a float de forma segura. Retorna None si no es posible."""
    if value is None:
        return None
    try:
        return float(value)
    except (ValueError, TypeError):
        return None


def extraer_datos_publicacion(item):
    """Extrae campaña, SKU e item_id de una respuesta de ML"""
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
    if seller_sku and str(seller_sku).isdigit():
        item_id = int(seller_sku)

    return campaign, seller_sku, item_id


def sanitizar_datos_ml(item, campaign, seller_sku, item_id):
    """
    Sanitiza los datos de ML antes de enviarlos a PostgreSQL.
    Convierte tipos para evitar InvalidTextRepresentation.
    """
    return {
        "title": str(item.get("title", ""))[:500] if item.get("title") else None,
        "price": safe_numeric(item.get("price")),
        "base_price": safe_numeric(item.get("base_price")),
        "available_quantity": safe_int(item.get("available_quantity")),
        "sold_quantity": safe_int(item.get("sold_quantity")),
        "status": str(item.get("status", ""))[:50] if item.get("status") else None,
        "listing_type_id": str(item.get("listing_type_id", ""))[:50] if item.get("listing_type_id") else None,
        "permalink": str(item.get("permalink", ""))[:500] if item.get("permalink") else None,
        "installments_campaign": str(campaign)[:100] if campaign else None,
        "seller_sku": str(seller_sku)[:100] if seller_sku else None,
        "item_id": safe_int(item_id),
        "snapshot_date": datetime.now(),
    }


def aplicar_snapshot(snapshot, item, campaign, seller_sku, item_id):
    """Actualiza los campos de un snapshot existente con datos nuevos"""
    datos = sanitizar_datos_ml(item, campaign, seller_sku, item_id)
    for key, value in datos.items():
        setattr(snapshot, key, value)


def crear_snapshot(mla_id, item, campaign, seller_sku, item_id):
    """Crea un nuevo objeto MLPublicationSnapshot"""
    datos = sanitizar_datos_ml(item, campaign, seller_sku, item_id)
    datos["mla_id"] = str(mla_id)[:50] if mla_id else None
    return MLPublicationSnapshot(**datos)


async def obtener_todos_mla_ids(db: Session) -> list:
    """
    Obtiene TODOS los MLA IDs de todas las publicaciones en mercadolibre_items_publicados
    """
    print("Obteniendo TODOS los MLA IDs...")

    mla_ids = (
        db.query(MercadoLibreItemPublicado.mlp_publicationID)
        .filter(MercadoLibreItemPublicado.mlp_publicationID.isnot(None))
        .distinct()
        .all()
    )

    ids = [row[0] for row in mla_ids if row[0]]
    print(f"✓ Encontradas {len(ids)} publicaciones TOTALES para sincronizar")

    return ids


def precargar_snapshots_hoy(db: Session, today) -> dict:
    """
    Precarga todos los snapshot IDs del día de hoy en un dict {mla_id: snapshot_id}
    para evitar 15.000 queries individuales.
    """
    print("Precargando snapshots existentes del día...")

    snapshots = (
        db.query(MLPublicationSnapshot.mla_id, MLPublicationSnapshot.id)
        .filter(func.date(MLPublicationSnapshot.snapshot_date) == today)
        .all()
    )

    cache = {row[0]: row[1] for row in snapshots}
    print(f"✓ {len(cache)} snapshots existentes en cache")

    return cache


async def procesar_batch(
    ids_batch: list,
    db: Session,
    batch_num: int,
    total_batches: int,
    http_client: httpx.AsyncClient,
    snapshots_cache: dict,
):
    """
    Procesa un batch de MLA IDs.
    Estrategia: commit por chunk de 20 → si falla, fallback a individual.
    """
    chunk_size = 20
    saved = 0
    updated = 0
    errors = 0
    errores_detalle = []

    for i in range(0, len(ids_batch), chunk_size):
        chunk = ids_batch[i : i + chunk_size]
        ids_str = ",".join(chunk)

        # Llamada a la API
        try:
            batch = await call_meli(http_client, f"/items?ids={ids_str}")
        except Exception as e:
            errors += len(chunk)
            errores_detalle.append(f"  ⚠️  API error chunk [{chunk[0]}...{chunk[-1]}]: {str(e)[:100]}")
            continue

        # Preparar las operaciones del chunk en memoria
        chunk_items = []  # [(mla_id, item_data, campaign, seller_sku, item_id), ...]
        for item_wrapper in batch:
            item = item_wrapper.get("body")
            if not item:
                error_status = item_wrapper.get("code", "?")
                errors += 1
                errores_detalle.append(f"  ⚠️  ML respondió sin body (code={error_status})")
                continue

            mla_id = item.get("id")
            campaign, seller_sku, item_id = extraer_datos_publicacion(item)
            chunk_items.append((mla_id, item, campaign, seller_sku, item_id))

        if not chunk_items:
            continue

        # Intentar commit del chunk completo
        try:
            chunk_saved = 0
            chunk_updated = 0

            for mla_id, item, campaign, seller_sku, item_id in chunk_items:
                if mla_id in snapshots_cache:
                    # Actualizar existente
                    existing = db.get(MLPublicationSnapshot, snapshots_cache[mla_id])
                    if existing:
                        aplicar_snapshot(existing, item, campaign, seller_sku, item_id)
                        chunk_updated += 1
                    else:
                        # Cache stale, crear nuevo
                        snapshot = crear_snapshot(mla_id, item, campaign, seller_sku, item_id)
                        db.add(snapshot)
                        chunk_saved += 1
                else:
                    # Crear nuevo
                    snapshot = crear_snapshot(mla_id, item, campaign, seller_sku, item_id)
                    db.add(snapshot)
                    chunk_saved += 1

            db.commit()

            # Actualizar contadores y cache
            saved += chunk_saved
            updated += chunk_updated

            # Actualizar cache para nuevos snapshots (por si el incremental ya los creó)
            for mla_id, _, _, _, _ in chunk_items:
                if mla_id not in snapshots_cache:
                    # No necesitamos el ID exacto en cache, solo saber que existe
                    snapshots_cache[mla_id] = -1  # placeholder

        except Exception as chunk_error:
            # Chunk falló → rollback y procesar individualmente
            db.rollback()
            mla_ids_chunk = [mla_id for mla_id, _, _, _, _ in chunk_items]
            errores_detalle.append(
                f"  ℹ️  Chunk falló ({mla_ids_chunk[0]}..{mla_ids_chunk[-1]}), "
                f"reintentando individual: {str(chunk_error)[:150]}"
            )

            for mla_id, item, campaign, seller_sku, item_id in chunk_items:
                try:
                    if mla_id in snapshots_cache:
                        existing = db.get(MLPublicationSnapshot, snapshots_cache[mla_id])
                        if existing:
                            aplicar_snapshot(existing, item, campaign, seller_sku, item_id)
                        else:
                            db.add(crear_snapshot(mla_id, item, campaign, seller_sku, item_id))
                    else:
                        db.add(crear_snapshot(mla_id, item, campaign, seller_sku, item_id))

                    db.commit()

                    if mla_id in snapshots_cache:
                        updated += 1
                    else:
                        saved += 1
                        snapshots_cache[mla_id] = -1

                except Exception as e:
                    db.rollback()
                    errors += 1
                    # Log detallado: MLA ID, tipo de error, y datos que causaron el problema
                    datos_debug = {
                        "price": item.get("price"),
                        "base_price": item.get("base_price"),
                        "available_quantity": item.get("available_quantity"),
                        "sold_quantity": item.get("sold_quantity"),
                        "item_id": item_id,
                        "seller_sku": seller_sku,
                    }
                    errores_detalle.append(
                        f"  ⚠️  {mla_id} [{type(e).__name__}]: {str(e)[:150]}\n      Datos: {datos_debug}"
                    )

        # Pausa para no saturar la API
        await asyncio.sleep(0.1)

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

        # 1b. Preflight: fail loudly si no hay token válido, en vez de entrar
        # al loop de batches y acumular miles de errores idénticos.
        await _ml_client.get_access_token()

        # 2. Precargar snapshots existentes del día
        today = datetime.now().date()
        snapshots_cache = precargar_snapshots_hoy(db, today)

        # 3. Dividir en batches grandes (1000 por batch)
        batch_size = 1000
        total_batches = (len(all_ids) + batch_size - 1) // batch_size

        print(f"Procesando en {total_batches} batches de {batch_size} publicaciones...")
        print()

        total_saved = 0
        total_updated = 0
        total_errors = 0
        todos_los_errores = []

        # 4. Reutilizar UN SOLO httpx client para todas las requests
        async with httpx.AsyncClient(timeout=30.0) as http_client:
            for batch_num in range(total_batches):
                start_idx = batch_num * batch_size
                end_idx = min(start_idx + batch_size, len(all_ids))
                batch_ids = all_ids[start_idx:end_idx]

                print(f"📦 Batch {batch_num + 1}/{total_batches} ({len(batch_ids)} publicaciones)...")

                saved, updated, errors, errores_detalle = await procesar_batch(
                    batch_ids, db, batch_num + 1, total_batches, http_client, snapshots_cache
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
                    await asyncio.sleep(0.5)

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

        # Fail-closed: si TODO falló (nada guardado/actualizado y hubo
        # errores), no reportar como si hubiera sido un éxito silencioso.
        if total_errors > 0 and (total_saved + total_updated) == 0:
            raise RuntimeError(
                f"Sincronización completa fallida: 0 publicaciones procesadas de {len(all_ids)}, {total_errors} errores"
            )

        return total_saved, total_updated, total_errors

    except Exception as e:
        print(f"❌ Error durante la sincronización: {str(e)}")
        raise
    finally:
        if not db_was_provided:
            db.close()


if __name__ == "__main__":
    asyncio.run(sync_ml_publications_full())
