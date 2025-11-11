"""
Script para sincronizar publicaciones de MercadoLibre
Guarda snapshots de las publicaciones para comparar con los datos actuales del sistema
"""

import asyncio
import httpx
from datetime import datetime
from sqlalchemy.orm import Session
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


async def traer_todos_los_ids():
    """Obtiene todos los IDs de publicaciones usando el método scan (sin límite de 1050)"""
    user_id = settings.ML_USER_ID
    if not user_id:
        raise ValueError("ML_USER_ID no configurado en .env")

    all_ids = []
    url_path = f"/users/{user_id}/items/search?search_type=scan"

    print(f"Obteniendo IDs de publicaciones para user {user_id}...")

    while True:
        res = await call_meli(url_path)

        if not res or not res.get("results") or len(res["results"]) == 0:
            break

        all_ids.extend(res["results"])
        print(f"  Obtenidos {len(all_ids)} IDs hasta ahora...")

        # Preparar la siguiente página con scroll_id
        if res.get("scroll_id"):
            # URL encode del scroll_id
            scroll_id = res["scroll_id"].replace("+", "%2B").replace("/", "%2F").replace("=", "%3D")
            url_path = f"/users/{user_id}/items/search?search_type=scan&scroll_id={scroll_id}"
        else:
            break

    print(f"✓ Total de publicaciones encontradas: {len(all_ids)}")
    return all_ids


async def traer_detalles_batch(ids: list, db: Session):
    """Obtiene detalles de publicaciones en batches y los guarda en la DB"""
    chunk_size = 20
    total_saved = 0

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

                # Lógica condicional de campaña según las especificaciones:
                # - gold_special → Clásica (también aplica para su PVP correspondiente)
                # - gold_pro → 6 cuotas (6x_campaign)
                # - 3x_campaign → 3 cuotas
                # - 9x_campaign → 9 cuotas
                # - 12x_campaign → 12 cuotas
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

                # Crear registro de snapshot
                snapshot = MLPublicationSnapshot(
                    mla_id=item.get("id"),
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
            print(f"  Procesados {min(i + chunk_size, len(ids))}/{len(ids)} - Guardados: {total_saved}")

        except Exception as e:
            print(f"  Error en batch {i//chunk_size + 1}: {str(e)}")
            db.rollback()
            continue

        # Pequeña pausa para no saturar la API
        await asyncio.sleep(0.5)

    print(f"✓ Sincronización completada: {total_saved} publicaciones guardadas")
    return total_saved


async def sync_ml_publications():
    """Función principal de sincronización"""
    print("=" * 60)
    print("SINCRONIZACIÓN DE PUBLICACIONES DE MERCADOLIBRE")
    print("=" * 60)
    print(f"Inicio: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print()

    db = SessionLocal()
    try:
        # 1. Obtener todos los IDs
        ids = await traer_todos_los_ids()

        if not ids:
            print("No se encontraron publicaciones")
            return

        # 2. Limpiar snapshots antiguos del mismo día (opcional)
        # Puedes comentar esto si quieres mantener múltiples snapshots por día
        today = datetime.now().date()
        deleted = db.query(MLPublicationSnapshot).filter(
            MLPublicationSnapshot.snapshot_date >= today
        ).delete()
        db.commit()
        if deleted > 0:
            print(f"Eliminados {deleted} snapshots anteriores del día de hoy")
            print()

        # 3. Traer detalles y guardar
        await traer_detalles_batch(ids, db)

    except Exception as e:
        print(f"❌ Error durante la sincronización: {str(e)}")
        raise
    finally:
        db.close()

    print()
    print(f"Fin: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(sync_ml_publications())
