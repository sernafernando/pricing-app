"""
Script para sincronización incremental de item transaction details
Sincroniza solo los detalles de transacciones nuevas

Ejecutar desde el directorio backend:
    cd /var/www/html/pricing-app/backend
    python -m app.scripts.sync_item_transaction_details_incremental
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
# Importar todos los modelos para evitar problemas de dependencias circulares
import app.models  # noqa
from app.models.item_transaction import ItemTransaction
from app.models.item_transaction_detail import ItemTransactionDetail

async def sync_details_incremental(db: Session):
    """
    Sincroniza item transaction details de forma incremental
    Solo trae los detalles de transacciones que aún no tienen detalles
    """

    # Obtener el último it_transaction con detalles sincronizados
    ultimo_it_con_detalles = db.query(func.max(ItemTransactionDetail.it_transaction)).scalar()

    # Obtener el máximo it_transaction de item transactions
    max_it_transaction = db.query(func.max(ItemTransaction.it_transaction)).scalar()

    if max_it_transaction is None:
        print("⚠️  No hay item transactions en la base de datos.")
        return 0, 0, 0

    if ultimo_it_con_detalles is None:
        print("⚠️  No hay detalles sincronizados aún.")
        print("   Ejecuta primero sync_item_transaction_details_initial.py")
        return 0, 0, 0

    if ultimo_it_con_detalles >= max_it_transaction:
        print(f"✅ No hay item transactions nuevos para sincronizar.")
        print(f"   Último it_transaction con detalles: {ultimo_it_con_detalles}")
        print(f"   Último it_transaction disponible: {max_it_transaction}")
        return 0, 0, 0

    from_it = ultimo_it_con_detalles + 1
    to_it = max_it_transaction

    print(f"📊 Sincronizando detalles desde it_transaction {from_it} hasta {to_it}")
    print(f"🔄 Total de transacciones nuevas: {to_it - from_it + 1}\n")

    try:
        # Llamar al endpoint externo
        url = "https://parser-worker-js.gaussonline.workers.dev/consulta"
        params = {
            "strScriptLabel": "scriptItemTransactionDetails",
            "fromItTransaction": from_it,
            "toItTransaction": to_it
        }

        print(f"📅 Consultando API...")

        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.get(url, params=params)
            response.raise_for_status()
            details_data = response.json()

        if not isinstance(details_data, list):
            print(f"❌ Respuesta inválida del endpoint externo")
            return 0, 0, 0

        # Verificar si el API devuelve error
        if len(details_data) == 1 and "Column1" in details_data[0]:
            print(f"   ⚠️  No hay datos disponibles")
            return 0, 0, 0

        if not details_data or len(details_data) == 0:
            print(f"✅ No hay detalles nuevos para sincronizar.")
            return 0, 0, 0

        print(f"   Encontrados {len(details_data)} detalles nuevos\n")

        # Insertar detalles
        details_insertados = 0
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

        # Obtener nuevo máximo
        nuevo_max = db.query(func.max(ItemTransactionDetail.it_transaction)).scalar()

        print(f"\n✅ Sincronización completada!")
        print(f"   Insertados: {details_insertados}")
        print(f"   Errores: {details_errores}")
        print(f"   Nuevo it_transaction máximo con detalles: {nuevo_max}")

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
    Sincronización incremental de item transaction details
    """
    print("🚀 Sincronización incremental de item transaction details")
    print("=" * 60)

    db = SessionLocal()

    try:
        await sync_details_incremental(db)
        print("=" * 60)

    except Exception as e:
        print(f"\n❌ Error general: {str(e)}")
    finally:
        db.close()


if __name__ == "__main__":
    asyncio.run(main())
