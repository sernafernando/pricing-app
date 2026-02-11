"""
Script para sincronizar detalles de órdenes de MercadoLibre del año 2025
Trae la data mes por mes para evitar timeouts

Ejecutar desde el directorio backend:
    cd /var/www/html/pricing-app/backend
    python -m app.scripts.sync_ml_orders_detail_2025
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
from app.models.mercadolibre_order_detail import MercadoLibreOrderDetail


async def sync_ml_orders_detail_mes(db: Session, from_date: str, to_date: str):
    """
    Sincroniza detalles de órdenes de MercadoLibre de un mes específico
    """
    print(f"\n📅 Sincronizando detalles ML desde {from_date} hasta {to_date}...")

    try:
        # Llamar al endpoint externo
        url = "http://localhost:8002/api/gbp-parser"
        params = {"strScriptLabel": "scriptMLOrdersDetail", "fromDate": from_date, "toDate": to_date}

        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.get(url, params=params)
            response.raise_for_status()
            details_data = response.json()

        if not isinstance(details_data, list):
            print("❌ Respuesta inválida del endpoint externo")
            return 0, 0, 0

        # Verificar si el API devuelve error
        if len(details_data) == 1 and "Column1" in details_data[0]:
            print("   ⚠️  No hay datos disponibles para este período")
            return 0, 0, 0

        print(f"   Procesando {len(details_data)} detalles...")

        # Insertar o actualizar detalles
        details_insertados = 0
        details_actualizados = 0
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
                return value.lower() in ("true", "1", "yes", "t")
            return False

        def to_decimal(value):
            """Convierte a decimal, retorna None si no es válido"""
            if value is None or value == "":
                return None
            try:
                return float(value)
            except:
                return None

        def to_int(value):
            """Convierte a entero, retorna None si no es válido"""
            if value is None or value == "":
                return None
            try:
                return int(value)
            except:
                return None

        def to_string(value):
            """Convierte a string, retorna None si es None"""
            if value is None or value == "":
                return None
            return str(value)

        for detail_json in details_data:
            try:
                # Verificar que tenga mlod_id
                mlod_id = detail_json.get("mlod_id")
                if mlod_id is None:
                    print("   ⚠️  Detalle sin mlod_id, omitiendo...")
                    details_errores += 1
                    continue

                # Verificar si ya existe
                detail_existente = (
                    db.query(MercadoLibreOrderDetail).filter(MercadoLibreOrderDetail.mlod_id == mlod_id).first()
                )

                if detail_existente:
                    details_actualizados += 1
                    continue  # Skip si ya existe

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
                    mlod_lastupdate=parse_date(detail_json.get("mlod_lastUpdate")),
                )

                db.add(detail)
                details_insertados += 1

                # Commit cada 100 detalles
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

        print(
            f"   ✅ Insertados: {details_insertados} | Actualizados: {details_actualizados} | Errores: {details_errores}"
        )
        return details_insertados, details_actualizados, details_errores

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
    Sincroniza todos los detalles de órdenes de MercadoLibre del año 2025 mes por mes
    """
    print("🚀 Iniciando sincronización de detalles de órdenes ML 2025")
    print("=" * 60)

    db = SessionLocal()

    try:
        hoy = datetime.now()

        if hoy.year == 2025:
            meses_a_sincronizar = []
            for mes in range(1, hoy.month + 1):
                primer_dia = datetime(2025, mes, 1)

                if mes == 12:
                    ultimo_dia = datetime(2025, 12, 31)
                else:
                    ultimo_dia = datetime(2025, mes + 1, 1) - timedelta(days=1)

                if mes == hoy.month:
                    ultimo_dia = hoy + timedelta(days=1)

                meses_a_sincronizar.append(
                    {
                        "from": primer_dia.strftime("%Y-%m-%d"),
                        "to": ultimo_dia.strftime("%Y-%m-%d"),
                        "nombre": primer_dia.strftime("%B %Y"),
                    }
                )

        print(f"📊 Se sincronizarán {len(meses_a_sincronizar)} meses\n")

        total_insertados = 0
        total_actualizados = 0
        total_errores = 0

        for i, mes in enumerate(meses_a_sincronizar, 1):
            print(f"\n[{i}/{len(meses_a_sincronizar)}] {mes['nombre']}")
            insertados, actualizados, errores = await sync_ml_orders_detail_mes(db, mes["from"], mes["to"])

            total_insertados += insertados
            total_actualizados += actualizados
            total_errores += errores

            if i < len(meses_a_sincronizar):
                await asyncio.sleep(2)

        print("\n" + "=" * 60)
        print("📊 RESUMEN FINAL")
        print("=" * 60)
        print(f"✅ Total detalles insertados: {total_insertados}")
        print(f"⏭️  Total duplicados (omitidos): {total_actualizados}")
        print(f"❌ Total errores: {total_errores}")
        print(f"📦 Total procesados: {total_insertados + total_actualizados + total_errores}")
        print("=" * 60)
        print("🎉 Sincronización completada!")

    except Exception as e:
        print(f"\n❌ Error general: {str(e)}")
        import traceback

        traceback.print_exc()
    finally:
        db.close()


if __name__ == "__main__":
    asyncio.run(main())
