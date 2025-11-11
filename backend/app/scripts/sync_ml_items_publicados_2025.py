"""
Script para sincronizar items publicados de MercadoLibre del año 2025
Trae la data mes por mes para evitar timeouts

Ejecutar desde el directorio backend:
    cd /var/www/html/pricing-app/backend
    python -m app.scripts.sync_ml_items_publicados_2025
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

API_URL = "https://parser-worker-js.gaussonline.workers.dev/consulta"

def convertir_a_numero(valor, default=None):
    """Convierte string a número, maneja decimales y nulos"""
    try:
        if valor is None or valor == '' or valor == ' ':
            return default
        if isinstance(valor, (int, float)):
            return valor
        # Limpiar y convertir
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
            # Intentar otros formatos
            return datetime.fromisoformat(valor.replace('Z', '+00:00'))
        except:
            return None

async def sync_items_publicados_mes(db: Session, from_date: str, to_date: str):
    """
    Sincroniza items publicados de ML de un mes específico
    """
    print(f"\n📅 Sincronizando items publicados desde {from_date} hasta {to_date}...")

    params = {
        "strScriptLabel": "scriptMLItemsPublicados",
        "fromDate": from_date,
        "toDate": to_date
    }

    try:
        async with httpx.AsyncClient(timeout=180.0) as client:
            response = await client.get(API_URL, params=params)
            response.raise_for_status()
            data = response.json()

        if not data:
            print("   ⚠️  No se encontraron items publicados")
            return 0, 0

        print(f"   Encontrados {len(data)} items publicados")

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
                    'mls_id': convertir_a_entero(item_data.get('mls_id')),
                    'mlipc_id': convertir_a_entero(item_data.get('mlipc_id')),
                    'st_id': convertir_a_entero(item_data.get('st_id')),
                    'disc_id': convertir_a_entero(item_data.get('disc_id')),
                    'dl_id': convertir_a_entero(item_data.get('dl_id')),
                    'mlmp_id': convertir_a_entero(item_data.get('mlmp_id')),

                    # Datos de publicación
                    'mlp_publicationID': item_data.get('mlp_publicationID'),
                    'mlp_itemTitle': item_data.get('mlp_itemTitle'),
                    'mlp_itemSubTitle': item_data.get('mlp_itemSubTitle'),
                    'mlp_subTitle': item_data.get('mlp_subTitle'),
                    'mlp_itemDesc': item_data.get('mlp_itemDesc'),
                    'mlp_itemHTML': item_data.get('mlp_itemHTML'),
                    'mlp_itemHTML2': item_data.get('mlp_itemHTML2'),
                    'mlp_itemHTML3': item_data.get('mlp_itemHTML3'),
                    'mlp_family_name': item_data.get('mlp_family_name'),
                    'mlp_userProductID': item_data.get('mlp_userProductID'),

                    # Precios
                    'mlp_price': convertir_a_numero(item_data.get('mlp_price')),
                    'curr_id': convertir_a_entero(item_data.get('curr_id')),
                    'mlp_lastPublicatedPrice': convertir_a_numero(item_data.get('mlp_lastPublicatedPrice')),
                    'mlp_lastPublicatedCurrID': convertir_a_entero(item_data.get('mlp_lastPublicatedCurrID')),
                    'mlp_lastPublicatedExchange': convertir_a_numero(item_data.get('mlp_lastPublicatedExchange')),
                    'mlp_price4FreeShipping': convertir_a_numero(item_data.get('mlp_price4FreeShipping')),
                    'mlp_price4AdditionalCost': convertir_a_numero(item_data.get('mlp_price4AdditionalCost')),
                    'mlp_lastPriceInformedByML': convertir_a_numero(item_data.get('mlp_lastPriceInformedByML')),
                    'mlp_Price2WinLastPrice': convertir_a_numero(item_data.get('mlp_Price2WinLastPrice')),

                    # Cantidades
                    'mlp_initQty': convertir_a_entero(item_data.get('mlp_initQty')),
                    'mlp_minQty4Pause': convertir_a_entero(item_data.get('mlp_minQty4Pause')),
                    'mlp_sold_quantity': convertir_a_entero(item_data.get('mlp_sold_quantity')),
                    'mlp_lastPublicatedAvailableQTY': convertir_a_entero(item_data.get('mlp_lastPublicatedAvailableQTY')),

                    # Estados
                    'optval_statusId': convertir_a_entero(item_data.get('optval_statusId')),
                    'mlp_Active': convertir_a_boolean(item_data.get('mlp_Active')),
                    'mlp_4Revision': convertir_a_boolean(item_data.get('mlp_4Revision')),
                    'mlp_revisionMessage': item_data.get('mlp_revisionMessage'),
                    'mlp_lastStatusID': convertir_a_entero(item_data.get('mlp_lastStatusID')),
                    'mlp_variationError': item_data.get('mlp_variationError'),
                    'health': convertir_a_numero(item_data.get('health')),

                    # Tipo de publicación
                    'mlp_listing_type_id': item_data.get('mlp_listing_type_id'),
                    'mlp_buying_mode': item_data.get('mlp_buying_mode'),
                    'mlp_isFixedPrice': convertir_a_boolean(item_data.get('mlp_isFixedPrice')),

                    # Comisiones
                    'mlp_listing_fee_amount': convertir_a_numero(item_data.get('mlp_listing_fee_amount')),
                    'mlp_sale_fee_amount': convertir_a_numero(item_data.get('mlp_sale_fee_amount')),

                    # URLs
                    'mlp_permalink': item_data.get('mlp_permalink'),
                    'mlp_thumbnail': item_data.get('mlp_thumbnail'),
                    'mlp_video_id': item_data.get('mlp_video_id'),

                    # Fechas
                    'mlp_inicDate': convertir_fecha(item_data.get('mlp_inicDate')),
                    'mlp_endDate': convertir_fecha(item_data.get('mlp_endDate')),
                    'mlp_lastUpdate': convertir_fecha(item_data.get('mlp_lastUpdate')),
                    'mlp_start_time': convertir_fecha(item_data.get('mlp_start_time')),
                    'mlp_stop_time': convertir_fecha(item_data.get('mlp_stop_time')),
                    'mlp_creationDate': convertir_fecha(item_data.get('mlp_creationDate')),
                    'dateof_lastUpdate': convertir_fecha(item_data.get('dateof_lastUpdate')),
                    'dateof_lastUpdateFromMeLi': convertir_fecha(item_data.get('dateof_lastUpdateFromMeLi')),
                    'mlp_lastUpdateFromERP': convertir_fecha(item_data.get('mlp_lastUpdateFromERP')),
                    'userid_lastUpdate': convertir_a_entero(item_data.get('userid_lastUpdate')),

                    # Envíos
                    'mlp_accepts_mercadopago': convertir_a_boolean(item_data.get('mlp_accepts_mercadopago')),
                    'mlp_local_pick_up': convertir_a_boolean(item_data.get('mlp_local_pick_up')),
                    'mlp_free_shipping': convertir_a_boolean(item_data.get('mlp_free_shipping')),
                    'mlp_free_method': item_data.get('mlp_free_method'),
                    'mlp_free_shippingMShops': convertir_a_boolean(item_data.get('mlp_free_shippingMShops')),
                    'mlp_free_shippingMShops_Coeficient': convertir_a_numero(item_data.get('mlp_free_shippingMShops_Coeficient')),

                    # Categoría
                    'mlp_publicationCategoryID': item_data.get('mlp_publicationCategoryID'),

                    # Garantía
                    'mlp_warranty': item_data.get('mlp_warranty'),
                    'mlp_warranty_type': item_data.get('mlp_warranty_type'),
                    'mlp_warranty_time': item_data.get('mlp_warranty_time'),
                    'mlp_warranty_time_value': convertir_a_entero(item_data.get('mlp_warranty_time_value')),

                    # Catálogo
                    'mlp_catalog_product_id': item_data.get('mlp_catalog_product_id'),
                    'mlp_catalog_listing': convertir_a_boolean(item_data.get('mlp_catalog_listing')),
                    'mlp_catalog_isAvailable': convertir_a_boolean(item_data.get('mlp_catalog_isAvailable')),
                    'mlp_catalog_boost': convertir_a_numero(item_data.get('mlp_catalog_boost')),

                    # Ahora programas
                    'mlp_ahora3': convertir_a_boolean(item_data.get('mlp_ahora3')),
                    'mlp_ahora6': convertir_a_boolean(item_data.get('mlp_ahora6')),
                    'mlp_ahora12': convertir_a_boolean(item_data.get('mlp_ahora12')),
                    'mlp_ahora18': convertir_a_boolean(item_data.get('mlp_ahora18')),
                    'mlp_ahora24': convertir_a_boolean(item_data.get('mlp_ahora24')),
                    'mlp_ahora30': convertir_a_boolean(item_data.get('mlp_ahora30')),

                    # Fulfillment
                    'mlp_is4FulFillment': convertir_a_boolean(item_data.get('mlp_is4FulFillment')),
                    'mlp_is4FullAndFlex': convertir_a_boolean(item_data.get('mlp_is4FullAndFlex')),

                    # Estadísticas
                    'mlp_statistics_MinPrice4Category': convertir_a_numero(item_data.get('mlp_statistics_MinPrice4Category')),
                    'mlp_statistics_MaxPrice4Category': convertir_a_numero(item_data.get('mlp_statistics_MaxPrice4Category')),
                    'mlp_statistics_AvgPrice4Category': convertir_a_numero(item_data.get('mlp_statistics_AvgPrice4Category')),
                }

                if not item_existente:
                    # Insertar nuevo
                    nuevo_item = MercadoLibreItemPublicado(**item_dict)
                    db.add(nuevo_item)
                    insertados += 1
                else:
                    # Actualizar existente
                    for key, value in item_dict.items():
                        if key != 'mlp_id':  # No actualizar la PK
                            setattr(item_existente, key, value)
                    actualizados += 1

                # Commit cada 50 items
                if i % 50 == 0:
                    db.commit()
                    print(f"   ✓ {i} items procesados...")

            except Exception as e:
                errores += 1
                print(f"   ⚠️  Error procesando item {mlp_id}: {str(e)}")
                continue

        # Commit final
        db.commit()

        print(f"\n✅ Sincronización completada!")
        print(f"   Insertados: {insertados}")
        print(f"   Actualizados: {actualizados}")
        print(f"   Errores: {errores}")

        return insertados, actualizados

    except Exception as e:
        print(f"   ❌ Error en la petición: {str(e)}")
        db.rollback()
        return 0, 0


async def main():
    """
    Sincroniza todos los items publicados de ML del 2025 mes por mes
    """
    print("="*60)
    print("📦 Sincronización de Items Publicados ML - 2025")
    print("="*60)

    db = SessionLocal()

    try:
        # Definir meses de 2025
        meses = [
            ("2025-01-01", "2025-01-31"),
            ("2025-02-01", "2025-02-28"),
            ("2025-03-01", "2025-03-31"),
            ("2025-04-01", "2025-04-30"),
            ("2025-05-01", "2025-05-31"),
            ("2025-06-01", "2025-06-30"),
            ("2025-07-01", "2025-07-31"),
            ("2025-08-01", "2025-08-31"),
            ("2025-09-01", "2025-09-30"),
            ("2025-10-01", "2025-10-31"),
            ("2025-11-01", "2025-11-30"),
            ("2025-12-01", "2025-12-31"),
        ]

        total_insertados = 0
        total_actualizados = 0

        for from_date, to_date in meses:
            insertados, actualizados = await sync_items_publicados_mes(db, from_date, to_date)
            total_insertados += insertados
            total_actualizados += actualizados

            # Pequeña pausa entre meses
            await asyncio.sleep(1)

        print("\n" + "="*60)
        print("✨ RESUMEN FINAL")
        print("="*60)
        print(f"Total insertados: {total_insertados}")
        print(f"Total actualizados: {total_actualizados}")
        print("="*60)

    finally:
        db.close()


if __name__ == "__main__":
    asyncio.run(main())
