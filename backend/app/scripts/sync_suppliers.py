"""
Script para sincronizar proveedores desde el ERP.

Es un wrapper delgado sobre `ProveedoresService.sync_desde_erp()`, la función
canónica que ejecuta la cadena completa: GBP → tb_supplier → proveedores →
rma_proveedores. El cliente HTTP es `erp_worker_client` (usa
`settings.GBP_PARSER_URL`, sin hosts hardcodeados).

Falla fuerte: si el ERP no responde o devuelve vacío, el script termina con
exit code 1 y la excepción se propaga al runner del cron. Lo mismo si ya hay
otra sincronización de proveedores en curso (`SyncEnCursoError`): el cron NO
puede reportar un sync exitoso que nunca llegó a persistir nada.

Modos de uso:
    # Full (toda la tabla)
    python -m app.scripts.sync_suppliers

    # Un proveedor específico
    python -m app.scripts.sync_suppliers --supp-id 456
"""

import sys
from pathlib import Path

# Add backend directory to path
backend_dir = Path(__file__).parent.parent.parent
sys.path.insert(0, str(backend_dir))

from dotenv import load_dotenv

env_path = backend_dir / ".env"
load_dotenv(dotenv_path=env_path)

import argparse
import asyncio

from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.services.proveedores_service import ErpSyncError, ProveedoresService, SyncEnCursoError


def sync_full(db: Session, supp_id: int | None = None) -> dict[str, int]:
    """
    Sincronización completa vía ProveedoresService.sync_desde_erp().

    Levanta ErpSyncError si el ERP no devolvió datos utilizables y
    SyncEnCursoError si otro sync ya está persistiendo. Ninguna de las dos se
    traga acá: el caller decide cómo reportarlas.
    """
    label = f"supp_id={supp_id}" if supp_id else "toda la tabla"
    print(f"\n🔄 Sincronización de proveedores ({label})")
    print("=" * 60)

    print("📡 Consultando ERP y proyectando a proveedores...")
    result = asyncio.run(ProveedoresService(db).sync_desde_erp(supp_id=supp_id))

    print("\n✅ Sincronización finalizada")
    print(f"   Recibidos del ERP:   {result['total_erp']}")
    print(f"   Proveedores nuevos:  {result['insertados']}")
    print(f"   Actualizados:        {result['actualizados']}")
    print(f"   RMA creados:         {result['rma_insertados']}")
    print(f"   RMA vinculados:      {result['vinculados_rma']}")

    return result


def sync_suppliers() -> tuple[int, int]:
    """
    Entry point para sync_master_tables_small (sin args, maneja su propia session).

    Retorna (insertados, actualizados) reales. Tanto ErpSyncError como
    SyncEnCursoError se propagan a propósito: `sync_master_tables_small` las
    registra en `resultados["errores"]` y devuelve exit code 1. Tragarlas acá
    reportaría un sync exitoso que nunca corrió.
    """
    db = SessionLocal()
    try:
        result = sync_full(db)
        return (result["insertados"], result["actualizados"])
    finally:
        db.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Sincronizar proveedores desde el ERP")
    parser.add_argument("--supp-id", type=int, default=None, help="Sincronizar un proveedor específico")

    args = parser.parse_args()

    db = SessionLocal()

    try:
        sync_full(db, supp_id=args.supp_id)
    except SyncEnCursoError as e:
        # Exit code 1, igual que cualquier otro fallo: el cron NO sincronizó.
        # Reportarlo como éxito (exit 0) escondería que los datos quedaron
        # viejos porque esta corrida no llegó a persistir nada.
        print(f"\n❌ Sincronización no ejecutada: {str(e)}")
        sys.exit(1)
    except ErpSyncError as e:
        print(f"\n❌ Error de sincronización con el ERP: {str(e)}")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ Error: {str(e)}")
        import traceback

        traceback.print_exc()
        sys.exit(1)
    finally:
        db.close()


if __name__ == "__main__":
    main()
