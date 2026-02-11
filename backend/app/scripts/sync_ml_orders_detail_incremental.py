"""
Script para sincronización incremental de detalles de órdenes de MercadoLibre
Sincroniza solo los detalles nuevos desde el último mlod_id

Ejecutar desde el directorio backend:
    cd /var/www/html/pricing-app/backend
    python -m app.scripts.sync_ml_orders_detail_incremental
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
from app.models.mercadolibre_order_detail import MercadoLibreOrderDetail

async def sync_ml_orders_detail_incremental(db: Session):
    """
    Sincroniza detalles de órdenes de MercadoLibre de forma incremental
    Solo trae los detalles nuevos desde el último mlod_id
    """

    # Obtener el último mlod_id sincronizado
    ultimo_mlod = db.query(func.max(MercadoLibreOrderDetail.mlod_id)).scalar()

    if ultimo_mlod is None:
        print("⚠️  No hay detalles de órdenes ML en la base de datos.")
        print("   Ejecuta primero sync_ml_orders_detail_2025.py para la carga inicial")
        return 0, 0, 0

    print(f"📊 Último mlod_id en BD: {ultimo_mlod}")
    print("🔄 Buscando detalles nuevos...\n")

    try:
        # Llamar al endpoint externo usando mlodId
        url = "http://localhost:8002/api/gbp-parser"
        params = {
            "strScriptLabel": "scriptMLOrdersDetail",
            "mlodId": ultimo_mlod
        }

        print(f"📅 Consultando API desde mlod_id > {ultimo_mlod}...")

        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.get(url, params=params)
            response.raise_for_status()
            details_data = response.json()

        if not isinstance(details_data, list):
            print("❌ Respuesta inválida del endpoint externo")
            return 0, 0, 0

        # Verificar si el API devuelve error
        if len(details_data) == 1 and "Column1" in details_data[0]:
            print("   ⚠️  No hay datos disponibles")
            return 0, 0, 0

        if not details_data or len(details_data) == 0:
            print("✅ No hay detalles nuevos. Base de datos actualizada.")
            return 0, 0, 0

        print(f"   Encontrados {len(details_data)} detalles nuevos")
        print(f"   Rango: {min(d.get('mlod_id') for d in details_data)} - {max(d.get('mlod_id') for d in details_data)}\n")

        # Insertar detalles nuevos
        details_insertados = 0
        details_errores = 0

        def parse_date(date_str):
            if not date_str:
                return None
            try:
                if isinstance(date_str, str):
                    # Formato: 11/3/2025 10:09:26 AM
                    return datetime.strptime(date_str, "%m/%d/%Y %I:%M:%S %p")
                return date_str
            except:
                try:
                    # Intentar con formato ISO
                    return datetime.fromisoformat(date_str.replace("Z", "+00:00"))
                except:
                    return None

        def to_bool(value):
            """Convierte cualquier valor a booleano"""
            if value is None:
                return False
            if isinstance(value, bool):
                return value
            if isinstance(value, (int, float)):
                return bool(value)
            if isinstance(value, str):
                return value.lower() in ('true', '1', 'yes', 't')
            return False

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
            """Convierte a string, retorna None si es None"""
            if value is None or value == '':
                return None
            return str(value)

        for detail_json in details_data:
            try:
                mlod_id = detail_json.get("mlod_id")

                # Crear nuevo detalle
                detail = MercadoLibreOrderDetail(
                    comp_id=to_int(detail_json.get("comp_id")),
                    mlo_id=to_int(detail_json.get("mlo_id")),
                    mlod_id=mlod_id,
                    mlp_id=to_int(detail_json.get("mlp_id")),
                    item_id=to_int(detail_json.get("item_id")),
                    mlo_unit_price=to_decimal(detail_json.get("mlo_unit_price")),
                    mlo_quantity=to_decimal(detail_json.get("mlo_quantity")),
                    mlo_currency_id=detail_json.get("mlo_currency_id"),
                    mlo_cd=parse_date(detail_json.get("mlo_cd")),
                    mlo_note=detail_json.get("mlo_note"),
                    mlo_is4availablestock=to_bool(detail_json.get("mlo_is4AvailableStock")),
                    stor_id=to_int(detail_json.get("stor_id")),
                    mlo_listing_fee_amount=to_decimal(detail_json.get("mlo_listing_fee_amount")),
                    mlo_sale_fee_amount=to_decimal(detail_json.get("mlo_sale_fee_amount")),
                    mlo_title=detail_json.get("mlo_title"),
                    mlvariationid=to_string(detail_json.get("MLVariationID")),
                    mlod_lastupdate=parse_date(detail_json.get("mlod_lastUpdate"))
                )

                db.add(detail)
                details_insertados += 1

                if details_insertados % 100 == 0:
                    db.commit()
                    print(f"   ✓ {details_insertados} detalles insertados...")

            except Exception as e:
                print(f"   ⚠️  Error procesando detalle {detail_json.get('mlod_id')}: {str(e)}")
                details_errores += 1
                db.rollback()
                continue

        # Commit final
        db.commit()

        # Obtener nuevo máximo
        nuevo_max = db.query(func.max(MercadoLibreOrderDetail.mlod_id)).scalar()

        print("\n✅ Sincronización completada!")
        print(f"   Insertados: {details_insertados}")
        print(f"   Errores: {details_errores}")
        print(f"   Nuevo mlod_id máximo: {nuevo_max}")

        return details_insertados, 0, details_errores

    except httpx.HTTPError as e:
        print(f"❌ Error al consultar API externa: {str(e)}")
        return 0, 0, 0
    except Exception as e:
        db.rollback()
        print(f"❌ Error en sincronización: {str(e)}")
        import traceback
        traceback.print_exc()
        return 0, 0, 0


async def main():
    """
    Sincronización incremental de detalles de órdenes ML
    """
    print("🚀 Sincronización incremental de detalles de órdenes ML")
    print("=" * 60)

    db = SessionLocal()

    try:
        await sync_ml_orders_detail_incremental(db)
        print("=" * 60)

    except Exception as e:
        print(f"\n❌ Error general: {str(e)}")
    finally:
        db.close()


if __name__ == "__main__":
    asyncio.run(main())
