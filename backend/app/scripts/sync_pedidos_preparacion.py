"""
Script para sincronización de pedidos en preparación desde la query 67 del ERP.
Trunca y actualiza la tabla pedido_preparacion_cache cada ejecución.

Ejecutar desde el directorio backend:
    cd /var/www/html/pricing-app/backend
    python -m app.scripts.sync_pedidos_preparacion

La query 67 devuelve:
- item_id
- item_code
- item_desc
- cantidad (SUM de mlo_quantity)
- ML_logistic_type (Turbo si MLshipping_method_id=515282)
- PreparaPaquete (COUNT de ML_pack_id)
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
from decimal import Decimal
from sqlalchemy.orm import Session
from sqlalchemy import text
from app.core.database import SessionLocal

# Importar todos los modelos para evitar problemas de dependencias circulares
import app.models  # noqa
from app.models.pedido_preparacion_cache import PedidoPreparacionCache


GBP_PARSER_URL = os.getenv("GBP_PARSER_URL", "http://localhost:8002/api/gbp-parser")

# Lock global para evitar múltiples sincronizaciones simultáneas
_sync_lock = asyncio.Lock()


async def fetch_query_67() -> list:
    """
    Llama al gbp-parser con intExpgr_id=67 para obtener los pedidos en preparación.
    """
    async with httpx.AsyncClient(timeout=60.0) as client:
        response = await client.get(GBP_PARSER_URL, params={"intExpgr_id": 67})
        response.raise_for_status()
        return response.json()


def truncate_cache(db: Session):
    """Trunca la tabla de cache con lock para evitar condiciones de carrera"""
    # Adquirir lock exclusivo en la tabla para evitar que múltiples workers ejecuten esto a la vez
    db.execute(text("LOCK TABLE pedido_preparacion_cache IN ACCESS EXCLUSIVE MODE"))
    # Usar DELETE en lugar de TRUNCATE para mejor compatibilidad
    db.execute(text("DELETE FROM pedido_preparacion_cache"))
    # Reiniciar la secuencia del autoincrement
    db.execute(text("ALTER SEQUENCE pedido_preparacion_cache_id_seq RESTART WITH 1"))
    db.commit()
    print("   Tabla truncada correctamente")


def insert_cache(db: Session, data: list) -> int:
    """
    Inserta los datos en la tabla de cache.
    Retorna la cantidad de registros insertados.
    """
    inserted = 0
    for row in data:
        try:
            cache_item = PedidoPreparacionCache(
                item_id=int(row.get("item_id")) if row.get("item_id") else None,
                item_code=str(row.get("item_code", ""))[:100] if row.get("item_code") else None,
                item_desc=str(row.get("item_desc", ""))[:500] if row.get("item_desc") else None,
                cantidad=Decimal(str(row.get("cantidad", 0))) if row.get("cantidad") else Decimal(0),
                ml_logistic_type=str(row.get("ML_logistic_type", ""))[:50] if row.get("ML_logistic_type") else None,
                prepara_paquete=int(row.get("PreparaPaquete", 0)) if row.get("PreparaPaquete") else 0,
            )
            db.add(cache_item)
            inserted += 1
        except Exception as e:
            print(f"   ⚠️ Error insertando fila: {row} - {e}")
            continue

    db.commit()
    return inserted


async def sync_pedidos_preparacion(db: Session = None) -> dict:
    """
    Sincroniza pedidos en preparación desde la query 67 del ERP.
    Trunca la tabla y la recarga con los datos nuevos.
    Usa un lock para evitar ejecuciones simultáneas.
    """
    # Intentar adquirir el lock - si otro proceso está sincronizando, retorna inmediatamente
    if _sync_lock.locked():
        print("\n⚠️ Ya hay una sincronización en progreso, saltando...")
        return {"status": "skipped", "message": "Sincronización ya en progreso", "count": 0}

    async with _sync_lock:
        print("\n📦 Sincronizando pedidos en preparación...")
        print(f"   Hora: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

        close_db = False
        if db is None:
            db = SessionLocal()
            close_db = True

        try:
            # 1. Obtener datos del ERP via gbp-parser
            print("   Consultando query 67 via gbp-parser...")
            data = await fetch_query_67()

            if not data:
                print("   ⚠️ No se obtuvieron datos de la query 67")
                return {"status": "warning", "message": "No data returned", "count": 0}

            print(f"   Recibidos {len(data)} registros")

            # 2. Truncar tabla
            print("   Truncando tabla cache...")
            truncate_cache(db)

            # 3. Insertar nuevos datos
            print("   Insertando datos...")
            inserted = insert_cache(db, data)

            print(f"   ✅ Sincronización completada: {inserted} registros insertados")

            return {"status": "success", "count": inserted, "timestamp": datetime.now().isoformat()}

        except httpx.HTTPStatusError as e:
            print(f"   ❌ Error HTTP: {e.response.status_code} - {e.response.text}")
            return {"status": "error", "message": f"HTTP error: {e.response.status_code}"}
        except Exception as e:
            print(f"   ❌ Error: {str(e)}")
            db.rollback()
            return {"status": "error", "message": str(e)}
        finally:
            if close_db:
                db.close()


async def main():
    """Punto de entrada para ejecución manual"""
    result = await sync_pedidos_preparacion()
    print(f"\nResultado: {result}")


if __name__ == "__main__":
    asyncio.run(main())
