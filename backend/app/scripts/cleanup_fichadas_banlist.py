"""
Elimina fichadas de employee_no baneados (ej: "0").

El Hikvision DS-K1T804AMF genera eventos con employeeNoString="0"
que corresponden a autenticaciones fallidas o lecturas fantasma.
Este script limpia las fichadas ya guardadas en la DB.

USO:
  cd backend
  source venv/bin/activate
  python -m app.scripts.cleanup_fichadas_banlist [--dry-run]
"""

import sys

from app.core.database import SessionLocal
from app.models.rrhh_fichada import RRHHFichada
from app.services.rrhh_hikvision_client import EMPLOYEE_NO_BANLIST


def cleanup_fichadas_banlist(dry_run: bool = True) -> dict:
    """Elimina fichadas cuyo hikvision_employee_no está en la banlist."""
    db = SessionLocal()
    try:
        fichadas = db.query(RRHHFichada).filter(RRHHFichada.hikvision_employee_no.in_(EMPLOYEE_NO_BANLIST)).all()

        total = len(fichadas)

        if total == 0:
            print("No se encontraron fichadas de employee_no baneados.")
            return {"eliminadas": 0}

        print(f"Encontradas {total} fichadas con employee_no en banlist {EMPLOYEE_NO_BANLIST}:")
        for f in fichadas:
            print(f"  ID={f.id}  Hik#{f.hikvision_employee_no}  {f.timestamp}  {f.tipo}")

        if not dry_run:
            for f in fichadas:
                db.delete(f)
            db.commit()

        mode = "DRY RUN" if dry_run else "APLICADO"
        print(f"\n[{mode}] Fichadas eliminadas: {total}")

        return {"eliminadas": total}

    finally:
        db.close()


if __name__ == "__main__":
    apply = "--apply" in sys.argv
    dry_run = not apply
    if dry_run:
        print("=== DRY RUN (usar --apply para ejecutar) ===\n")
    else:
        print("=== APLICANDO CAMBIOS ===\n")
    cleanup_fichadas_banlist(dry_run=dry_run)
