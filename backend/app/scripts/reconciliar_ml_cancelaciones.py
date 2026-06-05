"""
Reconciliación de cancelaciones ML (cron + barrido retroactivo).

Lee mlwebhook.ml_cancelled_orders y reconcilia las métricas locales: descongela
el header, marca ml_ventas_metricas.is_cancelled y revierte offsets.

Uso:
    # Incremental (cron, default: últimos 90 días de cancelaciones)
    python -m app.scripts.reconciliar_ml_cancelaciones

    # Barrido retroactivo completo (toda la historia de cancelaciones)
    python -m app.scripts.reconciliar_ml_cancelaciones --full

    # Simulación sin persistir (muestra qué haría)
    python -m app.scripts.reconciliar_ml_cancelaciones --full --dry-run

    # Ventana custom
    python -m app.scripts.reconciliar_ml_cancelaciones --lookback-days 30
"""

import argparse
import sys
from pathlib import Path

backend_dir = Path(__file__).parent.parent.parent
sys.path.insert(0, str(backend_dir))

from dotenv import load_dotenv

load_dotenv(dotenv_path=backend_dir / ".env")

from app.core.database import SessionLocal
from app.services.ml_cancelacion_reconciliacion_service import reconciliar_cancelaciones


def main() -> None:
    parser = argparse.ArgumentParser(description="Reconciliar cancelaciones ML contra ml_cancelled_orders")
    parser.add_argument("--full", action="store_true", help="Barrido retroactivo completo (sin ventana)")
    parser.add_argument("--lookback-days", type=int, default=90, help="Ventana de cancelaciones a revisar (default 90)")
    parser.add_argument("--dry-run", action="store_true", help="No persiste; solo muestra qué haría")
    args = parser.parse_args()

    lookback_days = None if args.full else args.lookback_days

    print("=" * 60)
    print("RECONCILIACIÓN DE CANCELACIONES ML")
    print("=" * 60)
    print(f"Modo: {'FULL (retroactivo)' if args.full else f'incremental ({lookback_days} días)'}")
    print(f"Dry-run: {args.dry_run}")

    db = SessionLocal()
    try:
        stats = reconciliar_cancelaciones(db, lookback_days=lookback_days, dry_run=args.dry_run)
        print("\n" + "=" * 60)
        print("✅ COMPLETADO" if not args.dry_run else "🧪 DRY-RUN (sin cambios)")
        print("=" * 60)
        for k, v in stats.items():
            print(f"  {k}: {v}")
        print()
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback

        traceback.print_exc()
        sys.exit(1)
    finally:
        db.close()


if __name__ == "__main__":
    main()
