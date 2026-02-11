"""
Script para sincronización incremental de envíos de órdenes de MercadoLibre
Sincroniza solo los envíos nuevos desde el último mlm_id sincronizado

Ejecutar desde el directorio backend:
    cd /var/www/html/pricing-app/backend
    python -m app.scripts.sync_ml_orders_shipping_incremental
"""
import sys
import os

if __name__ == "__main__":
    backend_path = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    if backend_path not in sys.path:
        sys.path.insert(0, backend_path)

import asyncio
import httpx
from datetime import datetime
from sqlalchemy.orm import Session
from sqlalchemy import func
from app.core.database import SessionLocal
# Importar todos los modelos para evitar problemas de dependencias circulares
import app.models  # noqa
from app.models.mercadolibre_order_shipping import MercadoLibreOrderShipping

async def sync_ml_orders_shipping_incremental(db: Session):
    """
    Sincroniza envíos de órdenes de MercadoLibre de forma incremental
    Solo trae los envíos nuevos desde el último mlm_id
    """
    print("\n📦 Sincronizando envíos ML incrementales...")

    try:
        # Obtener el último mlm_id sincronizado
        ultimo_mlm_id = db.query(func.max(MercadoLibreOrderShipping.mlm_id)).scalar()

        if ultimo_mlm_id is None:
            print("⚠️  No hay envíos sincronizados aún.")
            print("   Ejecuta primero sync_ml_orders_shipping_2025.py")
            return 0, 0, 0

        print(f"   Último mlm_id sincronizado: {ultimo_mlm_id}")

        # Llamar al endpoint externo
        url = "http://localhost:8002/api/gbp-parser"
        params = {
            "strScriptLabel": "scriptMLOrdersShipping",
            "mlmId": ultimo_mlm_id
        }

        print("   Consultando API...")

        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.get(url, params=params)
            response.raise_for_status()
            shipping_data = response.json()

        if not isinstance(shipping_data, list):
            print("❌ Respuesta inválida del endpoint externo")
            return 0, 0, 0

        # Verificar si el API devuelve error
        if len(shipping_data) == 1 and "Column1" in shipping_data[0]:
            print("   ⚠️  No hay datos disponibles")
            return 0, 0, 0

        if not shipping_data or len(shipping_data) == 0:
            print("✅ No hay envíos nuevos para sincronizar.")
            return 0, 0, 0

        print(f"   Procesando {len(shipping_data)} envíos nuevos...")

        # Insertar envíos
        shipping_insertados = 0
        shipping_actualizados = 0
        shipping_errores = 0

        def parse_date(date_str):
            if not date_str:
                return None
            try:
                if isinstance(date_str, str):
                    # Formato: 9/2/2025 12:00:00 AM
                    return datetime.strptime(date_str, "%m/%d/%Y %I:%M:%S %p")
                return date_str
            except:
                try:
                    # Intentar con formato ISO
                    return datetime.fromisoformat(date_str.replace("Z", "+00:00"))
                except:
                    return None

        def to_decimal(value):
            """Convierte a decimal, retorna None si no es válido"""
            if value is None or value == '':
                return None
            try:
                return float(value)
            except:
                return None

        def to_int(value):
            """Convierte a entero, retorna None si no es válido"""
            if value is None or value == '':
                return None
            try:
                return int(value)
            except:
                return None

        def to_string(value):
            """Convierte a string, retorna None si es None o vacío"""
            if value is None or value == '':
                return None
            return str(value).strip()

        for shipping_json in shipping_data:
            try:
                # Verificar que tenga mlm_id
                mlm_id = shipping_json.get("mlm_id")
                if mlm_id is None:
                    print("   ⚠️  Envío sin mlm_id, omitiendo...")
                    shipping_errores += 1
                    continue

                # Verificar si ya existe
                shipping_existente = db.query(MercadoLibreOrderShipping).filter(
                    MercadoLibreOrderShipping.mlm_id == mlm_id
                ).first()

                if shipping_existente:
                    shipping_actualizados += 1
                    continue  # Skip si ya existe

                # Crear nuevo envío
                shipping = MercadoLibreOrderShipping(
                    comp_id=to_int(shipping_json.get("comp_id")),
                    mlm_id=mlm_id,
                    mlo_id=to_int(shipping_json.get("mlo_id")),
                    mlshippingid=to_string(shipping_json.get("MLshippingID")),
                    mlshipment_type=to_string(shipping_json.get("MLshipment_type")),
                    mlshipping_mode=to_string(shipping_json.get("MLshipping_mode")),
                    mlm_json=to_string(shipping_json.get("mlm_JSON")),
                    mlcost=to_decimal(shipping_json.get("MLcost")),
                    mllogistic_type=to_string(shipping_json.get("MLlogistic_type")),
                    mlstatus=to_string(shipping_json.get("MLstatus")),
                    mlestimated_handling_limit=parse_date(shipping_json.get("MLestimated_handling_limit")),
                    mlestimated_delivery_final=parse_date(shipping_json.get("MLestimated_delivery_final")),
                    mlestimated_delivery_limit=parse_date(shipping_json.get("MLestimated_delivery_limit")),
                    mlreceiver_address=to_string(shipping_json.get("MLreceiver_address")),
                    mlstreet_name=to_string(shipping_json.get("MLstreet_name")),
                    mlstreet_number=to_string(shipping_json.get("MLstreet_number")),
                    mlcomment=to_string(shipping_json.get("MLcomment")),
                    mlzip_code=to_string(shipping_json.get("MLzip_code")),
                    mlcity_name=to_string(shipping_json.get("MLcity_name")),
                    mlstate_name=to_string(shipping_json.get("MLstate_name")),
                    mlcity_id=to_string(shipping_json.get("MLcity_id")),
                    mlstate_id=to_string(shipping_json.get("MLstate_id")),
                    mlconuntry_name=to_string(shipping_json.get("MLconuntry_name")),
                    mlreceiver_name=to_string(shipping_json.get("MLreceiver_name")),
                    mlreceiver_phone=to_string(shipping_json.get("MLreceiver_phone")),
                    mllist_cost=to_decimal(shipping_json.get("MLlist_cost")),
                    mldelivery_type=to_string(shipping_json.get("MLdelivery_type")),
                    mlshipping_method_id=to_string(shipping_json.get("MLshipping_method_id")),
                    mltracking_number=to_string(shipping_json.get("MLtracking_number")),
                    mlshippmentcost4buyer=to_decimal(shipping_json.get("MLShippmentCost4Buyer")),
                    mlshippmentcost4seller=to_decimal(shipping_json.get("MLShippmentCost4Seller")),
                    mlshippmentgrossamount=to_decimal(shipping_json.get("MLShippmentGrossAmount")),
                    mlfulfilled=to_string(shipping_json.get("MLfulfilled")),
                    mlcross_docking=to_string(shipping_json.get("MLCross_Docking")),
                    mlself_service=to_string(shipping_json.get("MLSelf_Service")),
                    ml_logistic_type=to_string(shipping_json.get("ML_logistic_type")),
                    ml_tracking_method=to_string(shipping_json.get("ML_tracking_method")),
                    ml_date_first_printed=parse_date(shipping_json.get("ML_date_first_printed")),
                    ml_base_cost=to_decimal(shipping_json.get("ML_base_cost")),
                    ml_estimated_delivery_time_date=parse_date(shipping_json.get("ML_estimated_delivery_time_date")),
                    ml_estimated_delivery_time_shipping=to_int(shipping_json.get("ML_estimated_delivery_time_shipping")),
                    mlos_lastupdate=parse_date(shipping_json.get("mlos_lastUpdate")),
                    mlshippmentcolectadaytime=parse_date(shipping_json.get("MLShippmentColectaDayTime")),
                    mlturbo=to_string(shipping_json.get("MLturbo"))
                )

                db.add(shipping)
                shipping_insertados += 1

                # Commit cada 50 envíos
                if shipping_insertados % 50 == 0:
                    db.commit()
                    print(f"   ✓ {shipping_insertados} envíos insertados...")

            except Exception as e:
                print(f"   ⚠️  Error procesando envío {shipping_json.get('mlm_id')}: {str(e)}")
                shipping_errores += 1
                db.rollback()
                continue

        # Commit final
        db.commit()

        # Obtener nuevo máximo
        nuevo_max = db.query(func.max(MercadoLibreOrderShipping.mlm_id)).scalar()

        print(f"\n   ✅ Insertados: {shipping_insertados} | Duplicados: {shipping_actualizados} | Errores: {shipping_errores}")
        print(f"   Nuevo mlm_id máximo: {nuevo_max}")

        return shipping_insertados, shipping_actualizados, shipping_errores

    except httpx.HTTPError as e:
        print(f"   ❌ Error al consultar API externa: {str(e)}")
        return 0, 0, 0
    except Exception as e:
        db.rollback()
        print(f"   ❌ Error en sincronización: {str(e)}")
        import traceback
        traceback.print_exc()
        return 0, 0, 0


async def main():
    """
    Sincronización incremental de envíos de órdenes de MercadoLibre
    """
    print("🚀 Sincronización incremental de envíos ML")
    print("=" * 60)

    db = SessionLocal()

    try:
        insertados, actualizados, errores = await sync_ml_orders_shipping_incremental(db)

        print("\n" + "=" * 60)
        print("📊 RESUMEN")
        print("=" * 60)
        print(f"✅ Total envíos insertados: {insertados}")
        print(f"⏭️  Total duplicados (omitidos): {actualizados}")
        print(f"❌ Total errores: {errores}")
        print(f"📦 Total procesados: {insertados + actualizados + errores}")
        print("=" * 60)

        if insertados > 0:
            print("🎉 Sincronización completada!")
        else:
            print("✅ Base de datos actualizada (sin cambios nuevos)")

    except Exception as e:
        print(f"\n❌ Error general: {str(e)}")
        import traceback
        traceback.print_exc()
    finally:
        db.close()


if __name__ == "__main__":
    asyncio.run(main())
