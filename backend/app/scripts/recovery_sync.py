"""
Script de recuperación para re-ejecutar todos los syncs que fallaron
debido al error de mapper de SQLAlchemy (RolPermisoBase).

Ejecutar:
    cd /var/www/html/pricing-app/backend
    python -m app.scripts.recovery_sync
"""
import sys
import os
from pathlib import Path

if __name__ == "__main__":
    backend_path = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    if backend_path not in sys.path:
        sys.path.insert(0, backend_path)

    # Cargar variables de entorno desde .env ANTES de importar settings
    from dotenv import load_dotenv
    env_path = Path(backend_path) / '.env'
    load_dotenv(dotenv_path=env_path)

import asyncio
from datetime import datetime
from app.core.database import SessionLocal

# Importar todos los modelos PRIMERO para evitar el error de mapper
import app.models  # noqa

# Importar funciones de sync
from app.scripts.sync_erp_master_tables_incremental import main_async as sync_erp_master_tables
from app.scripts.sync_commercial_transactions_incremental import sync_transacciones_incrementales
from app.scripts.sync_item_transactions_incremental import sync_item_transactions_incremental
from app.scripts.sync_item_transaction_details_incremental import sync_details_incremental
from app.scripts.sync_ml_orders_incremental import sync_ml_orders_incremental
from app.scripts.sync_ml_orders_detail_incremental import sync_ml_orders_detail_incremental
from app.scripts.sync_ml_orders_shipping_incremental import sync_ml_orders_shipping_incremental
from app.scripts.sync_ml_items_publicados_incremental import sync_items_publicados_incremental
from app.scripts.sync_ml_items_publicados_full import sync_items_publicados_full
from app.scripts.sync_ml_publications_incremental import sync_ml_publications_incremental
from app.scripts.sync_item_cost_history import sync_item_cost_history_incremental
from app.scripts.sync_item_cost_list import sync_item_cost_list_incremental
from app.scripts.sync_customers_incremental import sync_customers_incremental


async def run_recovery():
    """Ejecuta todos los syncs de recuperación"""
    timestamp_inicio = datetime.now()
    print("=" * 70)
    print("RECUPERACIÓN DE SYNCS FALLIDOS - ÚLTIMAS 6 HORAS")
    print(f"Inicio: {timestamp_inicio.strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 70)

    resultados = {"exitosos": [], "errores": []}

    sincronizaciones = [
        # 1. Tablas maestras ERP
        {
            "nombre": "Tablas Maestras ERP",
            "emoji": "📋",
            "funcion": sync_erp_master_tables,
            "skip_db": True
        },
        # 2. Commercial Transactions (ventas)
        {
            "nombre": "Commercial Transactions (Ventas)",
            "emoji": "💵",
            "funcion": sync_transacciones_incrementales,
            "args_batch": True
        },
        # 3. Item Transactions
        {
            "nombre": "Item Transactions",
            "emoji": "📦",
            "funcion": sync_item_transactions_incremental
        },
        # 4. Item Transaction Details
        {
            "nombre": "Item Transaction Details",
            "emoji": "📋",
            "funcion": sync_details_incremental
        },
        # 5. Item Cost List
        {
            "nombre": "Item Cost List",
            "emoji": "💰",
            "funcion": sync_item_cost_list_incremental
        },
        # 6. Item Cost History
        {
            "nombre": "Item Cost History",
            "emoji": "📊",
            "funcion": sync_item_cost_history_incremental
        },
        # 7. ML Orders
        {
            "nombre": "ML Orders",
            "emoji": "🛒",
            "funcion": sync_ml_orders_incremental
        },
        # 8. ML Orders Detail
        {
            "nombre": "ML Orders Detail",
            "emoji": "📄",
            "funcion": sync_ml_orders_detail_incremental
        },
        # 9. ML Orders Shipping
        {
            "nombre": "ML Orders Shipping",
            "emoji": "🚚",
            "funcion": sync_ml_orders_shipping_incremental
        },
        # 10. ML Items Publicados FULL (todas las activas)
        {
            "nombre": "ML Items Publicados (FULL)",
            "emoji": "📢",
            "funcion": sync_items_publicados_full
        },
        # 11. ML Items Publicados Incremental
        {
            "nombre": "ML Items Publicados (Incremental)",
            "emoji": "📢",
            "funcion": sync_items_publicados_incremental
        },
        # 12. ML Publications Snapshots
        {
            "nombre": "ML Publications Snapshots",
            "emoji": "📸",
            "funcion": sync_ml_publications_incremental
        },
        # 13. Customers
        {
            "nombre": "Customers",
            "emoji": "👥",
            "funcion": sync_customers_incremental,
            "args_batch": True
        },
    ]

    for i, sync in enumerate(sincronizaciones, 1):
        skip_db = sync.get('skip_db', False)
        db = None if skip_db else SessionLocal()

        try:
            print(f"\n{sync['emoji']} [{i}/{len(sincronizaciones)}] {sync['nombre']}...")

            if skip_db:
                result = await sync['funcion']()
            elif sync.get('args_batch'):
                result = await sync['funcion'](db, batch_size=1000)
            else:
                result = await sync['funcion'](db)

            print(f"   ✅ Completado: {result}")
            resultados["exitosos"].append(sync['nombre'])

        except Exception as e:
            print(f"   ❌ Error: {str(e)}")
            resultados["errores"].append(f"{sync['nombre']}: {str(e)}")
        finally:
            if db:
                db.close()

    # Resumen
    timestamp_fin = datetime.now()
    duracion = (timestamp_fin - timestamp_inicio).total_seconds()

    print("\n" + "=" * 70)
    print("RESUMEN DE RECUPERACIÓN")
    print("=" * 70)
    print(f"Duración: {duracion:.0f} segundos ({duracion/60:.1f} minutos)")
    print(f"✅ Exitosos: {len(resultados['exitosos'])}")
    print(f"❌ Errores: {len(resultados['errores'])}")

    if resultados['errores']:
        print("\n⚠️  Errores:")
        for error in resultados['errores']:
            print(f"   • {error}")

    print("=" * 70)
    return resultados


if __name__ == "__main__":
    asyncio.run(run_recovery())
