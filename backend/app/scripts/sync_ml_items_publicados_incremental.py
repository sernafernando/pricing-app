"""
Script para sincronización incremental de items publicados de MercadoLibre
Sincroniza solo los items nuevos/actualizados desde el último mlp_id

Ejecutar desde el directorio backend:
    cd /var/www/html/pricing-app/backend
    python -m app.scripts.sync_ml_items_publicados_incremental
"""
import sys
import os

if __name__ == "__main__":
    backend_path = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    if backend_path not in sys.path:
        sys.path.insert(0, backend_path)

import asyncio
import httpx
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from sqlalchemy import func
from app.core.database import SessionLocal
# Importar todos los modelos para evitar problemas de dependencias circulares
import app.models  # noqa
from app.models.mercadolibre_item_publicado import MercadoLibreItemPublicado

API_URL = "https://parser-worker-js.gaussonline.workers.dev/consulta"

def convertir_a_numero(valor, default=None):
    """Convierte string a número, maneja decimales y nulos"""
    try:
        if valor is None or valor == '' or valor == ' ':
            return default
        if isinstance(valor, (int, float)):
            return valor
        valor_str = str(valor).strip().replace(',', '')
        if valor_str == '':
            return default
        return float(valor_str)
    except:
        return default

def convertir_a_entero(valor, default=None):
    """Convierte a entero, truncando decimales"""
    try:
        num = convertir_a_numero(valor, default)
        if num is None:
            return default
        return int(float(num))
    except:
        return default

def convertir_a_boolean(valor):
    """Convierte varios formatos a boolean"""
    if isinstance(valor, bool):
        return valor
    if valor is None or valor == '':
        return False
    if isinstance(valor, str):
        return valor.lower() in ('true', '1', 't', 'yes', 'y')
    return bool(valor)

def convertir_fecha(valor):
    """Convierte string a datetime"""
    if not valor or valor == '' or valor == ' ':
        return None
    try:
        if isinstance(valor, datetime):
            return valor
        # Formato: "5/1/2025 12:00:00 AM"
        return datetime.strptime(valor, "%m/%d/%Y %I:%M:%S %p")
    except:
        try:
            return datetime.fromisoformat(valor.replace('Z', '+00:00'))
        except:
            return None


async def sync_items_publicados_incremental(db: Session):
    """
    Sincroniza items publicados de ML de forma incremental
    Solo trae los items nuevos/actualizados desde el último mlp_id
    """

    # Obtener el último mlp_id sincronizado
    ultimo_mlp_id = db.query(func.max(MercadoLibreItemPublicado.mlp_id)).scalar()

    if ultimo_mlp_id is None:
        print("⚠️  No hay items publicados en la base de datos.")
        print("   Ejecuta primero sync_ml_items_publicados_2025.py para la carga inicial")
        return 0, 0, 0

    print(f"📊 Último mlp_id en BD: {ultimo_mlp_id}")
    print(f"🔄 Buscando items publicados nuevos...\n")

    try:
        # Buscar items de los últimos 30 días con mlp_id > ultimo_mlp_id
        hoy = datetime.now()
        desde = (hoy - timedelta(days=30)).strftime('%Y-%m-%d')
        hasta = hoy.strftime('%Y-%m-%d')

        params = {
            "strScriptLabel": "scriptMLItemsPublicados",
            "fromDate": desde,
            "toDate": hasta,
            "mlpId": str(ultimo_mlp_id)  # El API filtrará mlp_id > este valor
        }

        print(f"📅 Consultando API desde {desde} hasta {hasta} con mlp_id > {ultimo_mlp_id}...")

        async with httpx.AsyncClient(timeout=180.0) as client:
            response = await client.get(API_URL, params=params)
            response.raise_for_status()
            data = response.json()

        if not data:
            print("   ℹ️  No se encontraron items publicados nuevos")
            return 0, 0, 0

        # Filtrar solo items con mlp_id mayor al último que tenemos
        items_nuevos = [item for item in data if convertir_a_entero(item.get('mlp_id'), 0) > ultimo_mlp_id]

        if not items_nuevos:
            print("   ℹ️  No se encontraron items publicados nuevos después del filtrado")
            return 0, 0, 0

        print(f"   Encontrados {len(items_nuevos)} items publicados nuevos")
        if items_nuevos:
            mlp_ids = [convertir_a_entero(item.get('mlp_id')) for item in items_nuevos]
            print(f"   Rango: {min(mlp_ids)} - {max(mlp_ids)}")

        insertados = 0
        actualizados = 0
        errores = 0

        for i, item_data in enumerate(items_nuevos, 1):
            try:
                mlp_id = convertir_a_entero(item_data.get('mlp_id'))
                if not mlp_id:
                    continue

                # Buscar si existe (por si acaso)
                item_existente = db.query(MercadoLibreItemPublicado).filter(
                    MercadoLibreItemPublicado.mlp_id == mlp_id
                ).first()

                # Preparar datos (mismo mapping que en el script inicial)
                item_dict = {
                    'mlp_id': mlp_id,
                    'comp_id': convertir_a_entero(item_data.get('comp_id')),
                    'bra_id': convertir_a_entero(item_data.get('bra_id')),
                    'stor_id': convertir_a_entero(item_data.get('stor_id')),
                    'prli_id': convertir_a_entero(item_data.get('prli_id')),
                    'item_id': convertir_a_entero(item_data.get('item_id')),
                    'user_id': convertir_a_entero(item_data.get('user_id')),
                    'mlp_publicationID': item_data.get('mlp_publicationID'),
                    'mlp_itemTitle': item_data.get('mlp_itemTitle'),
                    'mlp_itemSubTitle': item_data.get('mlp_itemSubTitle'),
                    'mlp_price': convertir_a_numero(item_data.get('mlp_price')),
                    'curr_id': convertir_a_entero(item_data.get('curr_id')),
                    'mlp_sold_quantity': convertir_a_entero(item_data.get('mlp_sold_quantity')),
                    'mlp_Active': convertir_a_boolean(item_data.get('mlp_Active')),
                    'mlp_listing_type_id': item_data.get('mlp_listing_type_id'),
                    'mlp_permalink': item_data.get('mlp_permalink'),
                    'mlp_thumbnail': item_data.get('mlp_thumbnail'),
                    'mlp_lastUpdate': convertir_fecha(item_data.get('mlp_lastUpdate')),
                    'mlp_free_shipping': convertir_a_boolean(item_data.get('mlp_free_shipping')),
                    'mlp_catalog_product_id': item_data.get('mlp_catalog_product_id'),
                    'health': convertir_a_numero(item_data.get('health')),
                    # Agregar más campos según necesites...
                }

                if not item_existente:
                    # Insertar nuevo
                    nuevo_item = MercadoLibreItemPublicado(**item_dict)
                    db.add(nuevo_item)
                    insertados += 1
                else:
                    # Actualizar existente (aunque no debería pasar)
                    for key, value in item_dict.items():
                        if key != 'mlp_id':
                            setattr(item_existente, key, value)
                    actualizados += 1

                # Commit cada 50 items
                if i % 50 == 0:
                    try:
                        db.commit()
                        print(f"   ✓ {i} items procesados...")
                    except Exception as e:
                        print(f"   ⚠️  Error en commit: {str(e)}")
                        db.rollback()

            except Exception as e:
                errores += 1
                print(f"   ⚠️  Error procesando item {mlp_id}: {str(e)}")
                db.rollback()  # Rollback para limpiar la transacción
                continue

        # Commit final
        try:
            db.commit()
        except Exception as e:
            print(f"   ❌ Error en commit final: {str(e)}")
            db.rollback()

        nuevo_maximo = db.query(func.max(MercadoLibreItemPublicado.mlp_id)).scalar()

        print(f"\n✅ Sincronización completada!")
        print(f"   Insertados: {insertados}")
        print(f"   Actualizados: {actualizados}")
        print(f"   Errores: {errores}")
        print(f"   Nuevo mlp_id máximo: {nuevo_maximo}")

        return insertados, actualizados, errores

    except Exception as e:
        print(f"   ❌ Error: {str(e)}")
        db.rollback()
        return 0, 0, 1


if __name__ == "__main__":
    print("🚀 Sincronización incremental de Items Publicados ML\n")

    db = SessionLocal()
    try:
        result = asyncio.run(sync_items_publicados_incremental(db))
    finally:
        db.close()
