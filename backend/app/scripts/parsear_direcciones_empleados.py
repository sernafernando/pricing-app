"""
Parsear direcciones de empleados: separar calle, número y piso/depto.

El script de importación cargó todo en 'calle' (ej: "LLERENA 3125 PB A").
Este script separa en calle="LLERENA", numero="3125", piso_depto="PB A".

Solo actualiza empleados que tienen 'calle' con número y 'numero' vacío.

Uso:
  cd backend
  source venv/bin/activate
  python -m app.scripts.parsear_direcciones_empleados --dry-run
  python -m app.scripts.parsear_direcciones_empleados
"""

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import argparse

from app.core.database import SessionLocal
from app.models.rrhh_empleado import RRHHEmpleado

# Patrón: texto + espacio + número de calle (1-5 dígitos) + opcional piso/depto
ADDR_PATTERN = re.compile(r"^(.+?)\s+(\d{1,5})\s*(.*)$")


def parse_address(raw: str) -> tuple[str, str, str | None]:
    """
    Separa 'CALLE NOMBRE 1234 PB A' en (calle, numero, piso_depto).

    Returns:
        (calle, numero, piso_depto or None)
    """
    m = ADDR_PATTERN.match(raw.strip())
    if not m:
        return (raw.strip(), "", None)

    calle = m.group(1).strip()
    numero = m.group(2).strip()
    piso = m.group(3).strip() or None
    return (calle, numero, piso)


def main() -> None:
    parser = argparse.ArgumentParser(description="Parsear direcciones de empleados")
    parser.add_argument("--dry-run", action="store_true", help="Solo mostrar, no escribir")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        # Solo empleados que tienen algo en calle y numero vacío
        empleados = (
            db.query(RRHHEmpleado)
            .filter(
                RRHHEmpleado.calle.isnot(None),
                RRHHEmpleado.calle != "",
            )
            .order_by(RRHHEmpleado.id)
            .all()
        )

        print(f"Empleados con dirección: {len(empleados)}")
        print()

        cambios = 0
        for emp in empleados:
            raw = emp.calle or ""
            if not raw:
                continue

            # Si ya tiene número separado, saltear
            if emp.numero and emp.numero.strip():
                print(f"  SKIP {emp.legajo} {emp.apellido} — ya tiene numero='{emp.numero}'")
                continue

            calle, numero, piso = parse_address(raw)

            if not numero:
                print(f"  SKIP {emp.legajo} {emp.apellido} — no se pudo parsear: '{raw}'")
                continue

            cambios += 1
            print(f"  {emp.legajo} {emp.apellido}, {emp.nombre}")
            print(f"    ANTES:   calle='{raw}' | numero='{emp.numero or ''}' | piso='{emp.piso_depto or ''}'")
            print(f"    DESPUÉS: calle='{calle}' | numero='{numero}' | piso='{piso or ''}'")
            print()

            if not args.dry_run:
                emp.calle = calle
                emp.numero = numero
                if piso and not (emp.piso_depto and emp.piso_depto.strip()):
                    emp.piso_depto = piso

        if not args.dry_run and cambios > 0:
            db.commit()

        print(f"{'=' * 50}")
        if args.dry_run:
            print(f"DRY RUN: {cambios} direcciones a actualizar (no se guardó nada)")
        else:
            print(f"Actualizadas: {cambios} direcciones")

    except Exception as e:
        db.rollback()
        print(f"ERROR: {e}")
        sys.exit(1)
    finally:
        db.close()


if __name__ == "__main__":
    main()
