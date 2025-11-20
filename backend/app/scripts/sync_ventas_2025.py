"""
Script para sincronizar ventas de MercadoLibre del año 2025
Trae la data mes por mes para evitar timeouts

Ejecutar desde el directorio backend:
    cd /var/www/html/pricing-app/backend
    python -m app.scripts.sync_ventas_2025
"""
import sys
import os

# Agregar el directorio backend al path si se ejecuta directamente
if __name__ == "__main__":
    backend_path = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    if backend_path not in sys.path:
        sys.path.insert(0, backend_path)

import asyncio
import httpx
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from app.core.database import SessionLocal
from app.models.venta_ml import VentaML

async def sync_ventas_mes(db: Session, from_date: str, to_date: str):
    """
    Sincroniza ventas de un mes específico
    """
    print(f"\n📅 Sincronizando ventas desde {from_date} hasta {to_date}...")

    try:
        # Llamar al endpoint externo
        url = "http://localhost:8002/api/gbp-parser"
        params = {
            "strScriptLabel": "scriptDashboard",
            "fromDate": from_date,
            "toDate": to_date
        }

        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.get(url, params=params)
            response.raise_for_status()
            ventas_data = response.json()

        if not isinstance(ventas_data, list):
            print(f"❌ Respuesta inválida del endpoint externo")
            return 0, 0, 0

        # Verificar si el API devuelve error (ej: {"Column1": "-9"})
        if len(ventas_data) == 1 and "Column1" in ventas_data[0]:
            print(f"   ⚠️  No hay datos disponibles para este período")
            return 0, 0, 0

        print(f"   Procesando {len(ventas_data)} ventas...")

        # Insertar o actualizar ventas
        ventas_insertadas = 0
        ventas_duplicadas = 0
        ventas_errores = 0

        for venta_json in ventas_data:
            try:
                # Verificar que tenga ID_de_Operación
                id_operacion = venta_json.get("ID_de_Operación")
                if id_operacion is None:
                    print(f"   ⚠️  Venta sin ID_de_Operación, omitiendo...")
                    ventas_errores += 1
                    continue

                # Verificar si ya existe
                venta_existente = db.query(VentaML).filter(
                    VentaML.id_operacion == id_operacion
                ).first()

                if venta_existente:
                    ventas_duplicadas += 1
                    continue  # Skip si ya existe

                # Crear nueva venta
                venta = VentaML(
                    id_operacion=id_operacion,
                    item_id=venta_json.get("item_id"),
                    fecha=datetime.fromisoformat(venta_json.get("Fecha").replace("Z", "+00:00")),
                    marca=venta_json.get("Marca"),
                    categoria=venta_json.get("Categoría"),
                    subcategoria=venta_json.get("SubCategoría"),
                    subcat_id=venta_json.get("subcat_id"),
                    codigo_item=venta_json.get("Código_Item"),
                    descripcion=venta_json.get("Descripción"),
                    cantidad=venta_json.get("Cantidad"),
                    monto_unitario=venta_json.get("Monto_Unitario"),
                    monto_total=venta_json.get("Monto_Total"),
                    moneda_costo=venta_json.get("Moneda_Costo"),
                    costo_sin_iva=venta_json.get("Costo_sin_IVA"),
                    iva=venta_json.get("IVA"),
                    cambio_al_momento=venta_json.get("Cambio_al_Momento"),
                    ml_logistic_type=venta_json.get("ML_logistic_type"),
                    ml_id=venta_json.get("ML_id"),
                    ml_shipping_id=venta_json.get("MLShippingID"),
                    ml_shipment_cost_seller=venta_json.get("MLShippmentCost4Seller"),
                    ml_price_free_shipping=venta_json.get("mlp_price4FreeShipping"),
                    ml_base_cost=venta_json.get("ML_base_cost"),
                    ml_pack_id=venta_json.get("ML_pack_id"),
                    price_list=venta_json.get("priceList")
                )

                db.add(venta)
                ventas_insertadas += 1

                # Commit cada 100 ventas para no perder todo si hay error
                if ventas_insertadas % 100 == 0:
                    db.commit()
                    print(f"   ✓ {ventas_insertadas} ventas insertadas...")

            except Exception as e:
                print(f"   ⚠️  Error procesando venta {venta_json.get('ID_de_Operación')}: {str(e)}")
                ventas_errores += 1
                continue

        # Commit final
        db.commit()

        print(f"   ✅ Insertadas: {ventas_insertadas} | Duplicadas: {ventas_duplicadas} | Errores: {ventas_errores}")
        return ventas_insertadas, ventas_duplicadas, ventas_errores

    except httpx.HTTPError as e:
        print(f"   ❌ Error al consultar API externa: {str(e)}")
        return 0, 0, 0
    except Exception as e:
        db.rollback()
        print(f"   ❌ Error en sincronización: {str(e)}")
        return 0, 0, 0


async def main():
    """
    Sincroniza todas las ventas del año 2025 mes por mes
    """
    print("🚀 Iniciando sincronización de ventas 2025")
    print("=" * 60)

    db = SessionLocal()

    try:
        # Definir meses a sincronizar (desde enero 2025 hasta hoy)
        hoy = datetime.now()

        # Si estamos en 2025, sincronizar hasta el mes actual
        if hoy.year == 2025:
            meses_a_sincronizar = []
            for mes in range(1, hoy.month + 1):
                # Primer día del mes
                primer_dia = datetime(2025, mes, 1)

                # Último día del mes
                if mes == 12:
                    ultimo_dia = datetime(2025, 12, 31)
                else:
                    ultimo_dia = datetime(2025, mes + 1, 1) - timedelta(days=1)

                # Si es el mes actual, usar fecha de hoy + 1 día
                if mes == hoy.month:
                    ultimo_dia = hoy + timedelta(days=1)

                meses_a_sincronizar.append({
                    'from': primer_dia.strftime('%Y-%m-%d'),
                    'to': ultimo_dia.strftime('%Y-%m-%d'),
                    'nombre': primer_dia.strftime('%B %Y')
                })

        print(f"📊 Se sincronizarán {len(meses_a_sincronizar)} meses\n")

        # Totales generales
        total_insertadas = 0
        total_duplicadas = 0
        total_errores = 0

        # Sincronizar mes por mes
        for i, mes in enumerate(meses_a_sincronizar, 1):
            print(f"\n[{i}/{len(meses_a_sincronizar)}] {mes['nombre']}")
            insertadas, duplicadas, errores = await sync_ventas_mes(
                db,
                mes['from'],
                mes['to']
            )

            total_insertadas += insertadas
            total_duplicadas += duplicadas
            total_errores += errores

            # Pausa breve entre meses para no saturar el servidor
            if i < len(meses_a_sincronizar):
                await asyncio.sleep(2)

        # Resumen final
        print("\n" + "=" * 60)
        print("📊 RESUMEN FINAL")
        print("=" * 60)
        print(f"✅ Total ventas insertadas: {total_insertadas}")
        print(f"⏭️  Total duplicadas (omitidas): {total_duplicadas}")
        print(f"❌ Total errores: {total_errores}")
        print(f"📦 Total procesadas: {total_insertadas + total_duplicadas + total_errores}")
        print("=" * 60)
        print("🎉 Sincronización completada!")

    except Exception as e:
        print(f"\n❌ Error general: {str(e)}")
    finally:
        db.close()


if __name__ == "__main__":
    asyncio.run(main())
