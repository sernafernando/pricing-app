"""
Script para sincronización standalone de impuestos por item (tb_item_taxes).

Pensado para correr solo, enganchado a un cron diario de madrugada, sin
cargar con el resto del sync completo de tablas maestras. Corrige el caso en
que el ERP actualiza el IVA de un producto (tb_item_taxes) sin tocar tb_item,
lo que hace que el sync incremental nunca vea el cambio.

Ejecutar:
    python -m app.scripts.sync_item_taxes
"""

import sys
import os

if __name__ == "__main__":
    backend_path = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    if backend_path not in sys.path:
        sys.path.insert(0, backend_path)

import asyncio
from datetime import datetime
from app.core.database import SessionLocal
import app.models  # noqa - importar todos los modelos
from app.services.erp_item_taxes_sync import sync_item_taxes_full


async def main_async():
    """Función principal async"""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print("=" * 60)
    print(f"SYNC IMPUESTOS POR ITEM - {timestamp}")
    print("=" * 60)

    db = SessionLocal()
    try:
        resultado = await sync_item_taxes_full(db)

        if "error" in resultado:
            print("\n" + "=" * 60)
            print(f"❌ SINCRONIZACIÓN DE IMPUESTOS FALLIDA: {resultado['error']}")
            print("=" * 60)
            sys.exit(1)

        print(
            f"  📦 Impuestos por item (TODOS)... ✓ ({resultado['insertados']} insertados, "
            f"{resultado['items_reemplazados']} items reemplazados)"
        )
        print("\n" + "=" * 60)
        print("✅ SINCRONIZACIÓN DE IMPUESTOS FINALIZADA")
        print("=" * 60)

    except Exception as e:
        print(f"\n❌ Error durante la sincronización: {str(e)}")
        import traceback

        traceback.print_exc()
        db.rollback()
        sys.exit(1)
    finally:
        db.close()


def main():
    asyncio.run(main_async())


if __name__ == "__main__":
    main()
