"""
Limpieza de fichadas duplicadas generadas por el Hikvision DS-K1T804AMF.

El dispositivo genera múltiples eventos (distintos serialNo) para una sola
autenticación física. Esto produce fichadas con el mismo employee_no y
timestamps dentro de 120 segundos.

Este script:
1. Agrupa fichadas por (hikvision_employee_no, DATE(timestamp))
2. Dentro de cada grupo, ordena por timestamp
3. Si dos fichadas consecutivas están separadas por menos de 120 segundos,
   elimina la segunda (mantiene la primera)
4. Recorre todos los días y empleados

USO:
  cd backend
  source venv/bin/activate
  python -m app.scripts.cleanup_fichadas_duplicadas [--dry-run]
"""

import sys
from datetime import timedelta

from sqlalchemy import func

from app.core.database import SessionLocal
from app.models.rrhh_fichada import RRHHFichada

PROXIMITY_SECONDS = 120


def cleanup_fichadas_duplicadas(dry_run: bool = True) -> dict:
    """Elimina fichadas duplicadas por proximidad temporal."""
    db = SessionLocal()
    try:
        # Obtener todos los pares únicos (employee_no, fecha)
        day_groups = (
            db.query(
                RRHHFichada.hikvision_employee_no,
                func.date(RRHHFichada.timestamp).label("dia"),
            )
            .filter(RRHHFichada.hikvision_employee_no.isnot(None))
            .group_by(
                RRHHFichada.hikvision_employee_no,
                func.date(RRHHFichada.timestamp),
            )
            .having(func.count(RRHHFichada.id) > 1)
            .all()
        )

        total_eliminadas = 0
        total_grupos = len(day_groups)

        for employee_no, dia in day_groups:
            fichadas = (
                db.query(RRHHFichada)
                .filter(
                    RRHHFichada.hikvision_employee_no == employee_no,
                    func.date(RRHHFichada.timestamp) == dia,
                )
                .order_by(RRHHFichada.timestamp.asc())
                .all()
            )

            # Mantener solo una fichada por ventana de PROXIMITY_SECONDS
            to_delete = []
            kept_timestamps = []
            for f in fichadas:
                is_near = any(abs((f.timestamp - kt).total_seconds()) < PROXIMITY_SECONDS for kt in kept_timestamps)
                if is_near:
                    to_delete.append(f)
                else:
                    kept_timestamps.append(f.timestamp)

            for f in to_delete:
                if not dry_run:
                    db.delete(f)
                total_eliminadas += 1

            if to_delete:
                print(
                    f"  Hik#{employee_no} {dia}: "
                    f"{len(fichadas)} fichadas -> {len(fichadas) - len(to_delete)} "
                    f"(eliminadas: {len(to_delete)})"
                )

        if not dry_run and total_eliminadas > 0:
            db.commit()
            # Reclasificar entrada/salida después de limpiar
            print("\nReclasificando entrada/salida...")
            from app.services.rrhh_hikvision_client import HikvisionClient

            client = HikvisionClient.__new__(HikvisionClient)
            client.db = db
            client._classify_entry_exit(None, None)
            db.commit()

        mode = "DRY RUN" if dry_run else "APLICADO"
        print(f"\n[{mode}] Grupos analizados: {total_grupos}")
        print(f"[{mode}] Fichadas a eliminar: {total_eliminadas}")

        return {"grupos": total_grupos, "eliminadas": total_eliminadas}

    finally:
        db.close()


if __name__ == "__main__":
    dry_run = "--dry-run" in sys.argv or len(sys.argv) == 1
    if dry_run:
        print("=== DRY RUN (usar sin --dry-run para aplicar) ===\n")
    else:
        print("=== APLICANDO CAMBIOS ===\n")
    cleanup_fichadas_duplicadas(dry_run=dry_run)
