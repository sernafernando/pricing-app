"""
Script para sincronización incremental de órdenes de MercadoLibre
Sincroniza solo las órdenes nuevas desde el último mlo_id

Ejecutar desde el directorio backend:
    cd /var/www/html/pricing-app/backend
    python -m app.scripts.sync_ml_orders_incremental
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
from app.models.mercadolibre_order_header import MercadoLibreOrderHeader

async def sync_ml_orders_incremental(db: Session):
    """
    Sincroniza órdenes de MercadoLibre de forma incremental
    Solo trae las órdenes nuevas desde el último mlo_id
    """

    # Obtener el último mlo_id sincronizado
    ultimo_mlo = db.query(func.max(MercadoLibreOrderHeader.mlo_id)).scalar()

    if ultimo_mlo is None:
        print("⚠️  No hay órdenes de MercadoLibre en la base de datos.")
        print("   Ejecuta primero sync_ml_orders_2025.py para la carga inicial")
        return 0, 0, 0

    print(f"📊 Último mlo_id en BD: {ultimo_mlo}")
    print(f"🔄 Buscando órdenes nuevas...\n")

    try:
        # Llamar al endpoint externo usando mloId
        url = "https://parser-worker-js.gaussonline.workers.dev/consulta"
        params = {
            "strScriptLabel": "scriptMLOrdersHeader",
            "mloId": ultimo_mlo
        }

        print(f"📅 Consultando API desde mlo_id > {ultimo_mlo}...")

        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.get(url, params=params)
            response.raise_for_status()
            orders_data = response.json()

        if not isinstance(orders_data, list):
            print(f"❌ Respuesta inválida del endpoint externo")
            return 0, 0, 0

        # Verificar si el API devuelve error
        if len(orders_data) == 1 and "Column1" in orders_data[0]:
            print(f"   ⚠️  No hay datos disponibles")
            return 0, 0, 0

        if not orders_data or len(orders_data) == 0:
            print(f"✅ No hay órdenes nuevas. Base de datos actualizada.")
            return 0, 0, 0

        print(f"   Encontradas {len(orders_data)} órdenes nuevas")
        print(f"   Rango: {min(o.get('mlo_id') for o in orders_data)} - {max(o.get('mlo_id') for o in orders_data)}\n")

        # Insertar órdenes nuevas
        orders_insertadas = 0
        orders_errores = 0

        def parse_date(date_str):
            if not date_str:
                return None
            try:
                if isinstance(date_str, str):
                    # Formato: 8/7/2025 9:12:12 PM
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

        for order_json in orders_data:
            try:
                mlo_id = order_json.get("mlo_id")

                # Crear nueva orden
                order = MercadoLibreOrderHeader(
                    comp_id=to_int(order_json.get("comp_id")),
                    mlo_id=mlo_id,
                    mluser_id=to_int(order_json.get("MLUser_Id")),
                    cust_id=to_int(order_json.get("cust_id")),
                    mlo_firstjson=order_json.get("mlo_firstJSON"),
                    mlo_lastjson=order_json.get("mlo_lastJSON"),
                    ml_id=to_string(order_json.get("ML_id")),
                    ml_date_created=parse_date(order_json.get("ML_date_created")),
                    ml_date_closed=parse_date(order_json.get("ML_date_closed")),
                    ml_last_updated=parse_date(order_json.get("ML_last_updated")),
                    mlo_shippingcost=to_decimal(order_json.get("mlo_shippingCost")),
                    mlo_transaction_amount=to_decimal(order_json.get("mlo_transaction_amount")),
                    mlo_cupon_amount=to_decimal(order_json.get("mlo_cupon_amount")),
                    mlo_overpaid_amount=to_decimal(order_json.get("mlo_overpaid_amount")),
                    mlo_total_paid_amount=to_decimal(order_json.get("mlo_total_paid_amount")),
                    mlo_status=order_json.get("mlo_status"),
                    mlorder_id=to_string(order_json.get("MLorder_id")),
                    mlo_issaleordergenerated=to_bool(order_json.get("mlo_isSaleOrderGenerated")),
                    mlo_email=order_json.get("mlo_email"),
                    identificationnumber=to_int(order_json.get("identificationNumber")),
                    identificationtype=order_json.get("identificationType"),
                    mlo_ispaid=to_bool(order_json.get("mlo_isPaid")),
                    mlo_isdelivered=to_bool(order_json.get("mlo_isDelivered")),
                    mlo_islabelprinted=to_bool(order_json.get("mlo_isLabelPrinted")),
                    mlo_isqualified=to_bool(order_json.get("mlo_isqualified")),
                    mlo_issaleorderemmited=to_bool(order_json.get("mlo_isSaleOrderEmmited")),
                    mlo_iscollected=to_bool(order_json.get("mlo_isCollected")),
                    mlo_iswithfraud=to_bool(order_json.get("mlo_isWithFraud")),
                    mluser_identificationtype=order_json.get("MLUser_identificationType"),
                    mluser_identificationnumber=to_int(order_json.get("MLUser_identificationNumber")),
                    mluser_address=order_json.get("MLUser_address"),
                    mluser_state=order_json.get("MLUser_state"),
                    mluser_citi=order_json.get("MLUser_citi"),
                    mluser_zip_code=order_json.get("MLUser_zip_code"),
                    mluser_phone=order_json.get("MLUser_phone"),
                    mluser_email=order_json.get("MLUser_email"),
                    mluser_receiver_name=order_json.get("MLUser_receiver_name"),
                    mluser_receiver_phone=order_json.get("MLUser_receiver_phone"),
                    mluser_alternative_phone=order_json.get("MLUser_alternative_phone"),
                    mlo_isorderreceiptmessage=to_bool(order_json.get("mlo_isorderReceiptMessage")),
                    mlo_iscancelled=to_bool(order_json.get("mlo_isCancelled")),
                    mlshippingid=to_string(order_json.get("MLShippingID")),
                    mlpickupid=to_string(order_json.get("MLPickUpID")),
                    mlpickupperson=order_json.get("MLPickUpPerson"),
                    mlbra_id=to_int(order_json.get("mlbra_id")),
                    ml_pack_id=to_string(order_json.get("ML_pack_id")),
                    mls_id=to_int(order_json.get("mls_id")),
                    mluser_first_name=order_json.get("MLUser_first_name"),
                    mluser_last_name=order_json.get("MLUser_last_name"),
                    mlo_ismshops=to_bool(order_json.get("mlo_ismshops")),
                    mlo_cd=parse_date(order_json.get("mlo_cd")),
                    mlo_me1_deliverystatus=str(order_json.get("mlo_ME1_deliveryStatus")) if order_json.get("mlo_ME1_deliveryStatus") is not None else None,
                    mlo_me1_deliverytracking=order_json.get("mlo_ME1_deliveryTracking"),
                    mlo_mustprintlabel=to_bool(order_json.get("mlo_mustPrintLabel")),
                    mlo_ismshops_invited=to_bool(order_json.get("mlo_ismshops_invited")),
                    mlo_orderswithdiscountcouponincludeinpricev2=to_bool(order_json.get("mlo_OrdersWithDiscountCouponIncludeInPriceV2"))
                )

                db.add(order)
                orders_insertadas += 1

                if orders_insertadas % 50 == 0:
                    db.commit()
                    print(f"   ✓ {orders_insertadas} órdenes insertadas...")

            except Exception as e:
                print(f"   ⚠️  Error procesando orden {order_json.get('mlo_id')}: {str(e)}")
                orders_errores += 1
                db.rollback()
                continue

        # Commit final
        db.commit()

        # Obtener nuevo máximo
        nuevo_max = db.query(func.max(MercadoLibreOrderHeader.mlo_id)).scalar()

        print(f"\n✅ Sincronización completada!")
        print(f"   Insertadas: {orders_insertadas}")
        print(f"   Errores: {orders_errores}")
        print(f"   Nuevo mlo_id máximo: {nuevo_max}")

        return orders_insertadas, 0, orders_errores

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
    Sincronización incremental de órdenes de MercadoLibre
    """
    print("🚀 Sincronización incremental de órdenes MercadoLibre")
    print("=" * 60)

    db = SessionLocal()

    try:
        await sync_ml_orders_incremental(db)
        print("=" * 60)

    except Exception as e:
        print(f"\n❌ Error general: {str(e)}")
    finally:
        db.close()


if __name__ == "__main__":
    asyncio.run(main())
