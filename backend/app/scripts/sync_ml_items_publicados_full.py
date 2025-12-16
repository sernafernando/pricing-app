"""
Script para sincronización COMPLETA diaria de items publicados de MercadoLibre
Actualiza TODAS las publicaciones (no solo las nuevas/modificadas)

Estrategia:
- Sincronización completa: 1 vez al día (este script - trae todo del último año)
- Sincronización incremental: cada hora (sync_ml_items_publicados_incremental.py)

Ejecutar desde el directorio backend:
    cd /var/www/html/pricing-app/backend
    python -m app.scripts.sync_ml_items_publicados_full
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


async def sync_items_publicados_full(db: Session):
    """
    Sincroniza TODAS las publicaciones ACTIVAS de ML
    Filtra por optval_statusId = 2 (activas)
    """
    print(f"📅 Sincronizando todas las publicaciones activas (status=2)...")

    # Traer todas las publicaciones activas de GBP
    # Usamos un rango amplio de fechas para capturar todo
    params = {
        "strScriptLabel": "scriptMLItemsPublicados",
        "fromDate": "2020-01-01",
        "toDate": datetime.now().strftime('%Y-%m-%d')
    }

    try:
        async with httpx.AsyncClient(timeout=300.0) as client:  # 5 min timeout
            response = await client.get(API_URL, params=params)
            response.raise_for_status()
            data = response.json()

        if not data:
            print("   ⚠️  No se encontraron items publicados")
            return 0, 0, 0

        print(f"   📦 Recibidos {len(data)} items de GBP")

        # Filtrar solo publicaciones activas (optval_statusId = 2)
        data = [item for item in data if convertir_a_entero(item.get('optval_statusId')) == 2]
        print(f"   ✓ {len(data)} publicaciones activas (status=2)")

        insertados = 0
        actualizados = 0
        errores = 0

        for i, item_data in enumerate(data, 1):
            try:
                mlp_id = convertir_a_entero(item_data.get('mlp_id'))
                if not mlp_id:
                    continue

                # Buscar si existe
                item_existente = db.query(MercadoLibreItemPublicado).filter(
                    MercadoLibreItemPublicado.mlp_id == mlp_id
                ).first()

                # Preparar datos
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

                # Commit cada 100 items
                if i % 100 == 0:
                    try:
                        db.commit()
                        print(f"   ✓ {i}/{len(data)} items procesados...")
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

        print(f"\n✅ Sincronización completa finalizada!")
        print(f"   Insertados: {insertados}")
        print(f"   Actualizados: {actualizados}")
        print(f"   Errores: {errores}")

        return insertados, actualizados, errores

    except Exception as e:
        print(f"   ❌ Error en la petición: {str(e)}")
        db.rollback()
        return 0, 0, 1


if __name__ == "__main__":
    print("="*60)
    print("📦 Sincronización COMPLETA de Items Publicados ML")
    print(f"🕐 Inicio: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("="*60)

    db = SessionLocal()
    try:
        result = asyncio.run(sync_items_publicados_full(db))
    finally:
        db.close()

    print("="*60)
    print(f"🕐 Fin: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("="*60)
