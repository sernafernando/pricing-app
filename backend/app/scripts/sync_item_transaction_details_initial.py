"""
Script para sincronización inicial de item transaction details
Sincroniza por lotes de it_transaction para mejor rendimiento

Ejecutar desde el directorio backend:
    cd /var/www/html/pricing-app/backend
    python -m app.scripts.sync_item_transaction_details_initial
"""
import sys
import os

if __name__ == "__main__":
    backend_path = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    if backend_path not in sys.path:
        sys.path.insert(0, backend_path)

import asyncio
import httpx
from sqlalchemy.orm import Session
from sqlalchemy import func
from app.core.database import SessionLocal
from app.models.item_transaction import ItemTransaction
from app.models.item_transaction_detail import ItemTransactionDetail

async def sync_details_lote(db: Session, from_it: int, to_it: int):
    """
    Sincroniza item transaction details de un lote específico
    """
    print(f"\n📦 Sincronizando lote it_transaction: {from_it} - {to_it}...")

    try:
        # Llamar al endpoint externo
        url = "https://parser-worker-js.gaussonline.workers.dev/consulta"
        params = {
            "strScriptLabel": "scriptItemTransactionDetails",
            "fromItTransaction": from_it,
            "toItTransaction": to_it
        }

        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.get(url, params=params)
            response.raise_for_status()
            details_data = response.json()

        if not isinstance(details_data, list):
            print(f"❌ Respuesta inválida del endpoint externo")
            return 0, 0, 0

        # Verificar si el API devuelve error
        if len(details_data) == 1 and "Column1" in details_data[0]:
            print(f"   ⚠️  No hay datos disponibles para este lote")
            return 0, 0, 0

        if not details_data or len(details_data) == 0:
            print(f"   ℹ️  No hay detalles para este lote")
            return 0, 0, 0

        print(f"   Procesando {len(details_data)} item transaction details...")

        # Insertar detalles
        details_insertados = 0
        details_actualizados = 0
        details_errores = 0

        def to_int(value):
            """Convierte a entero, retorna None si no es válido"""
            if value is None or value == '':
                return None
            try:
                return int(value)
            except:
                return None

        for detail_json in details_data:
            try:
                itm_transaction = detail_json.get("itm_transaction")
                if itm_transaction is None:
                    details_errores += 1
                    continue

                # Verificar si ya existe
                detail_existente = db.query(ItemTransactionDetail).filter(
                    ItemTransactionDetail.itm_transaction == itm_transaction
                ).first()

                if detail_existente:
                    details_actualizados += 1
                    continue  # Skip si ya existe

                # Crear nuevo item transaction detail
                detail = ItemTransactionDetail(
                    comp_id=to_int(detail_json.get("comp_id")),
                    bra_id=to_int(detail_json.get("bra_id")),
                    ct_transaction=to_int(detail_json.get("ct_transaction")),
                    it_transaction=to_int(detail_json.get("it_transaction")),
                    itm_transaction=itm_transaction,
                    itm_desc=detail_json.get("itm_desc"),
                    itm_desc1=detail_json.get("itm_desc1"),
                    itm_desc2=detail_json.get("itm_desc2")
                )

                db.add(detail)
                details_insertados += 1

                # Commit cada 100 detalles
                if details_insertados % 100 == 0:
                    db.commit()
                    print(f"   ✓ {details_insertados} detalles insertados...")

            except Exception as e:
                print(f"   ⚠️  Error procesando detalle {detail_json.get('itm_transaction')}: {str(e)}")
                details_errores += 1
                db.rollback()
                continue

        # Commit final
        db.commit()

        print(f"   ✅ Insertados: {details_insertados} | Duplicados: {details_actualizados} | Errores: {details_errores}")
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
    Sincroniza todos los item transaction details por lotes
    """
    print("🚀 Sincronización inicial de item transaction details")
    print("=" * 60)

    db = SessionLocal()

    try:
        # Obtener rango de it_transaction de la tabla local
        min_it = db.query(func.min(ItemTransaction.it_transaction)).scalar()
        max_it = db.query(func.max(ItemTransaction.it_transaction)).scalar()

        if min_it is None or max_it is None:
            print("❌ No hay item transactions en la base de datos.")
            print("   Ejecuta primero sync_item_transactions_2025.py")
            return

        print(f"📊 Rango de it_transaction en BD local: {min_it} - {max_it}")

        # Tamaño del lote (ajustable según performance)
        BATCH_SIZE = 5000

        # Calcular número de lotes
        total_range = max_it - min_it + 1
        num_batches = (total_range + BATCH_SIZE - 1) // BATCH_SIZE

        print(f"📦 Se procesarán {num_batches} lotes de hasta {BATCH_SIZE} transacciones\n")

        total_insertados = 0
        total_actualizados = 0
        total_errores = 0

        current_from = min_it
        batch_num = 1

        while current_from <= max_it:
            current_to = min(current_from + BATCH_SIZE - 1, max_it)

            print(f"\n[Lote {batch_num}/{num_batches}] it_transaction {current_from} - {current_to}")

            insertados, actualizados, errores = await sync_details_lote(
                db,
                current_from,
                current_to
            )

            total_insertados += insertados
            total_actualizados += actualizados
            total_errores += errores

            current_from = current_to + 1
            batch_num += 1

            # Pequeña pausa entre lotes para no sobrecargar el servidor
            if current_from <= max_it:
                await asyncio.sleep(1)

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
