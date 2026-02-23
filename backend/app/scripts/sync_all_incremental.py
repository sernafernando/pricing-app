"""
Script para ejecutar todas las sincronizaciones incrementales en orden
Ejecuta todos los syncs de forma secuencial con manejo de errores

Ejecutar desde el directorio backend:
    cd /var/www/html/pricing-app/backend
    python -m app.scripts.sync_all_incremental
"""

import sys
import os
from datetime import datetime
from pathlib import Path

if __name__ == "__main__":
    backend_path = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    if backend_path not in sys.path:
        sys.path.insert(0, backend_path)

    # Cargar variables de entorno desde .env ANTES de importar settings
    from dotenv import load_dotenv

    env_path = Path(backend_path) / ".env"
    load_dotenv(dotenv_path=env_path)

import asyncio
from app.core.database import SessionLocal

# Importar todas las funciones de sincronización
from app.scripts.sync_erp_master_tables_incremental import main_async as sync_erp_master_tables
from app.scripts.sync_commercial_transactions_incremental import sync_transacciones_incrementales
from app.scripts.sync_item_transactions_incremental import sync_item_transactions_incremental
from app.scripts.sync_item_transaction_details_incremental import sync_details_incremental
from app.scripts.sync_ml_orders_incremental import sync_ml_orders_incremental
from app.scripts.sync_ml_orders_detail_incremental import sync_ml_orders_detail_incremental
from app.scripts.sync_ml_orders_shipping_updater import sync_ml_orders_shipping_updater
from app.scripts.sync_ml_items_publicados_incremental import sync_items_publicados_incremental

# ML Publications Snapshot removido - se ejecuta en cron separado
from app.scripts.sync_item_cost_history import sync_item_cost_history_incremental
from app.scripts.sync_item_cost_list import sync_item_cost_list_incremental
from app.scripts.sync_customers_incremental import sync_customers_incremental
from app.scripts.sync_ml_users_data_incremental import sync_ml_users_data_incremental


async def ejecutar_todas_sincronizaciones():
    """
    Ejecuta todas las sincronizaciones incrementales en orden
    """
    timestamp_inicio = datetime.now()
    print("\n" + "=" * 60)
    print(f"🔄 Inicio sincronización completa: {timestamp_inicio.strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    resultados = {"exitosos": [], "errores": []}

    # Lista de sincronizaciones a ejecutar
    sincronizaciones = [
        {
            "nombre": "Tablas Maestras ERP (tb_brand, tb_category, tb_subcategory, tb_tax_name, tb_item, tb_item_taxes)",
            "emoji": "📋",
            "funcion": sync_erp_master_tables,
            "args_batch": False,
            "skip_db": True,  # Esta función maneja su propia conexión
        },
        {
            "nombre": "Commercial Transactions",
            "emoji": "📊",
            "funcion": sync_transacciones_incrementales,
            "args_batch": True,  # Usa batch_size
        },
        {
            "nombre": "Item Transactions",
            "emoji": "📦",
            "funcion": sync_item_transactions_incremental,
            "args_batch": False,
        },
        {"nombre": "Item Transaction Details", "emoji": "📋", "funcion": sync_details_incremental, "args_batch": False},
        {"nombre": "Item Cost List", "emoji": "💵", "funcion": sync_item_cost_list_incremental, "args_batch": False},
        {
            "nombre": "Item Cost List History",
            "emoji": "💰",
            "funcion": sync_item_cost_history_incremental,
            "args_batch": False,
        },
        {"nombre": "ML Orders", "emoji": "🛒", "funcion": sync_ml_orders_incremental, "args_batch": False},
        {
            "nombre": "ML Orders Detail",
            "emoji": "📄",
            "funcion": sync_ml_orders_detail_incremental,
            "args_batch": False,
        },
        {
            "nombre": "ML Orders Shipping",
            "emoji": "🚚",
            "funcion": sync_ml_orders_shipping_updater,
            "args_batch": False,
        },
        {
            "nombre": "ML Items Publicados",
            "emoji": "📢",
            "funcion": sync_items_publicados_incremental,
            "args_batch": False,
        },
        {
            "nombre": "Customers (Clientes)",
            "emoji": "👥",
            "funcion": sync_customers_incremental,
            "args_batch": True,  # Usa batch_size
        },
        {
            "nombre": "ML Users Data",
            "emoji": "👤",
            "funcion": sync_ml_users_data_incremental,
            "args_batch": False,
        },
        # NOTA: ML Publications Snapshot se movió a un cron separado (cada 4-6 horas)
        # porque procesa 14k+ registros y hace que este script tarde demasiado
    ]

    for i, sync in enumerate(sincronizaciones, 1):
        skip_db = sync.get("skip_db", False)
        db = None if skip_db else SessionLocal()
        try:
            print(f"\n{sync['emoji']} [{i}/{len(sincronizaciones)}] Sincronizando {sync['nombre']}...")

            # Ejecutar la función según sus requerimientos
            if skip_db:
                # Función que maneja su propia conexión a DB
                result = await sync["funcion"]()
            elif sync["args_batch"]:
                result = await sync["funcion"](db, batch_size=1000)
            else:
                result = await sync["funcion"](db)

            print(f"✅ {sync['nombre']} completado")

            # Guardar resultado
            if isinstance(result, tuple):
                resultados["exitosos"].append(f"{sync['nombre']}: {result}")
            else:
                resultados["exitosos"].append(sync["nombre"])

        except Exception as e:
            error_msg = f"{sync['nombre']}: {str(e)}"
            print(f"❌ Error en {sync['nombre']}: {str(e)}")
            resultados["errores"].append(error_msg)
        finally:
            if db:
                db.close()

    # Resumen final
    timestamp_fin = datetime.now()
    duracion = (timestamp_fin - timestamp_inicio).total_seconds()

    print("\n" + "=" * 60)
    print(f"✨ Sincronización completa finalizada: {timestamp_fin.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"⏱️  Duración: {duracion:.2f} segundos")
    print("=" * 60)

    print("\n📊 Resumen:")
    print(f"   ✅ Exitosos: {len(resultados['exitosos'])}")
    print(f"   ❌ Errores: {len(resultados['errores'])}")

    if resultados["errores"]:
        print("\n⚠️  Errores encontrados:")
        for error in resultados["errores"]:
            print(f"   • {error}")

    return resultados


if __name__ == "__main__":
    print("🚀 Iniciando sincronización completa de datos ERP...")

    try:
        resultados = asyncio.run(ejecutar_todas_sincronizaciones())

        # Exit code basado en resultados
        if resultados["errores"]:
            sys.exit(1)
        else:
            sys.exit(0)

    except KeyboardInterrupt:
        print("\n\n⚠️  Sincronización interrumpida por el usuario")
        sys.exit(130)
    except Exception as e:
        print(f"\n\n❌ Error crítico: {str(e)}")
        sys.exit(1)
