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

API_URL = "http://localhost:8002/api/gbp-parser"

def convertir_a_numero(valor, default=None):
    """Convierte string a número, maneja decimales y nulos"""
    try:
        if valor is None or valor == '' or valor == ' ':
            return default
        if isinstance(valor, bool):
            # Si es boolean, convertir a 0 o devolver default
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
    if isinstance(valor, (int, float)):
        return valor != 0
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
    1. Trae items nuevos (mlp_id > ultimo_mlp_id)
    2. Actualiza items modificados recientemente (mlp_lastUpdate reciente)
    """

    # Obtener el último mlp_id sincronizado
    ultimo_mlp_id = db.query(func.max(MercadoLibreItemPublicado.mlp_id)).scalar()

    if ultimo_mlp_id is None:
        print("⚠️  No hay items publicados en la base de datos.")
        print("   Ejecuta primero sync_ml_items_publicados_2025.py para la carga inicial")
        return 0, 0, 0

    print(f"📊 Último mlp_id en BD: {ultimo_mlp_id}")
    print(f"🔄 Sincronizando items publicados...\n")

    insertados_total = 0
    actualizados_total = 0
    errores_total = 0

    try:
        hoy = datetime.now()

        # PASO 1: Traer items NUEVOS (mlp_id > ultimo_mlp_id)
        print("📦 Paso 1: Buscando items nuevos...")
        desde = (hoy - timedelta(days=30)).strftime('%Y-%m-%d')
        hasta = hoy.strftime('%Y-%m-%d')

        params_nuevos = {
            "strScriptLabel": "scriptMLItemsPublicados",
            "fromDate": desde,
            "toDate": hasta,
            "mlpId": str(ultimo_mlp_id)
        }

        async with httpx.AsyncClient(timeout=180.0) as client:
            response = await client.get(API_URL, params=params_nuevos)
            response.raise_for_status()
            items_nuevos = response.json()

        if items_nuevos:
            items_nuevos = [item for item in items_nuevos if convertir_a_entero(item.get('mlp_id'), 0) > ultimo_mlp_id]
            print(f"   Encontrados {len(items_nuevos)} items nuevos")
            ins, act, err = await procesar_items(db, items_nuevos, "nuevos")
            insertados_total += ins
            actualizados_total += act
            errores_total += err
        else:
            print("   ℹ️  No hay items nuevos")

        # PASO 2: Traer items MODIFICADOS en los últimos 7 días
        print("\n🔄 Paso 2: Buscando items modificados recientemente...")
        desde_modificados = (hoy - timedelta(days=7)).strftime('%Y-%m-%d')

        params_modificados = {
            "strScriptLabel": "scriptMLItemsPublicados",
            "fromDate": desde_modificados,
            "toDate": hasta
            # NO enviamos mlpId para que traiga todos
        }

        async with httpx.AsyncClient(timeout=180.0) as client:
            response = await client.get(API_URL, params=params_modificados)
            response.raise_for_status()
            items_modificados = response.json()

        if items_modificados:
            print(f"   Recibidos {len(items_modificados)} items del período")

            # Filtrar solo los que existen en BD y tienen mlp_lastUpdate reciente
            items_a_actualizar = []
            for item in items_modificados:
                mlp_id = convertir_a_entero(item.get('mlp_id'))
                if not mlp_id or mlp_id > ultimo_mlp_id:
                    continue  # Ya lo procesamos en paso 1

                mlp_lastUpdate = convertir_fecha(item.get('mlp_lastUpdate'))
                if not mlp_lastUpdate:
                    continue

                # Verificar si está desactualizado en BD
                item_bd = db.query(MercadoLibreItemPublicado).filter(
                    MercadoLibreItemPublicado.mlp_id == mlp_id
                ).first()

                if item_bd:
                    # Si el lastUpdate del ERP es más reciente, actualizar
                    if not item_bd.mlp_lastUpdate or mlp_lastUpdate > item_bd.mlp_lastUpdate:
                        items_a_actualizar.append(item)

            if items_a_actualizar:
                print(f"   Encontrados {len(items_a_actualizar)} items modificados a actualizar")
                ins, act, err = await procesar_items(db, items_a_actualizar, "modificados")
                insertados_total += ins
                actualizados_total += act
                errores_total += err
            else:
                print("   ℹ️  No hay items modificados para actualizar")
        else:
            print("   ℹ️  No hay items modificados")

        nuevo_maximo = db.query(func.max(MercadoLibreItemPublicado.mlp_id)).scalar()

        print(f"\n✅ Sincronización completada!")
        print(f"   Insertados: {insertados_total}")
        print(f"   Actualizados: {actualizados_total}")
        print(f"   Errores: {errores_total}")
        print(f"   Nuevo mlp_id máximo: {nuevo_maximo}")

        return insertados_total, actualizados_total, errores_total

    except Exception as e:
        print(f"   ❌ Error: {str(e)}")
        db.rollback()
        return 0, 0, 1


async def procesar_items(db: Session, items: list, tipo: str):
    """Procesa una lista de items y los inserta/actualiza en la BD"""
    insertados = 0
    actualizados = 0
    errores = 0

    for i, item_data in enumerate(items, 1):
        try:
            mlp_id = convertir_a_entero(item_data.get('mlp_id'))
            if not mlp_id:
                continue

            # Buscar si existe
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
                'mlp_official_store_id': convertir_a_entero(item_data.get('mlp_official_store_id')),
                'health': convertir_a_numero(item_data.get('health')),
                'optval_statusId': convertir_a_entero(item_data.get('optval_statusId')),
            }

            if not item_existente:
                # Insertar nuevo
                nuevo_item = MercadoLibreItemPublicado(**item_dict)
                db.add(nuevo_item)
                insertados += 1
            else:
                # Actualizar existente
                for key, value in item_dict.items():
                    if key != 'mlp_id':
                        setattr(item_existente, key, value)
                actualizados += 1

            # Commit cada 50 items
            if i % 50 == 0:
                try:
                    db.commit()
                    print(f"   ✓ {tipo}: {i} items procesados...")
                except Exception as e:
                    print(f"   ⚠️  Error en commit: {str(e)}")
                    db.rollback()

        except Exception as e:
            errores += 1
            print(f"   ⚠️  Error procesando item {mlp_id}: {str(e)}")
            db.rollback()
            continue

    # Commit final
    try:
        db.commit()
    except Exception as e:
        print(f"   ❌ Error en commit final: {str(e)}")
        db.rollback()

    return insertados, actualizados, errores


if __name__ == "__main__":
    print("🚀 Sincronización incremental de Items Publicados ML\n")

    db = SessionLocal()
    try:
        result = asyncio.run(sync_items_publicados_incremental(db))
    finally:
        db.close()
