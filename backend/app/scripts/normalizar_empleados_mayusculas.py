"""
Normalizar campos de empleados que quedaron en MAYÚSCULAS a Title Case.

Uso:
  cd backend
  source venv/bin/activate
  python -m app.scripts.normalizar_empleados_mayusculas --dry-run
  python -m app.scripts.normalizar_empleados_mayusculas
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import argparse

from app.core.database import SessionLocal
from app.models.rrhh_empleado import RRHHEmpleado


# Campos de texto a normalizar
CAMPOS_TITLE_CASE = [
    "nombre",
    "apellido",
    "calle",
    "localidad",
    "provincia",
    "puesto",
    "area",
    "domicilio",
    "contacto_emergencia",
]

# Preposiciones/artículos que quedan en minúscula (excepto si son la primera palabra)
LOWERCASE_WORDS = {"de", "del", "la", "las", "los", "el", "y", "e", "en", "a"}


def smart_title(text: str) -> str:
    """
    Title Case inteligente.

    - 'GUTIERREZ GONZALEZ' → 'Gutierrez Gonzalez'
    - 'DANIELA DE LOS ANGELES' → 'Daniela de los Angeles'
    - 'LLERENA 3125 PB A' → 'Llerena 3125 Pb A'
    - 'CABA' → 'CABA' (siglas se mantienen si son <= 4 chars y todas mayúsculas)
    """
    words = text.split()
    result = []
    for i, word in enumerate(words):
        lower = word.lower()
        # Mantener siglas cortas (CABA, PB, etc.)
        if len(word) <= 4 and word.isalpha() and word.isupper() and word not in ("ESTE", "ZONA"):
            # Pero si es una preposición conocida, bajarla
            if lower in LOWERCASE_WORDS and i > 0:
                result.append(lower)
            else:
                result.append(word)
        elif lower in LOWERCASE_WORDS and i > 0:
            result.append(lower)
        else:
            result.append(word.capitalize())

    return " ".join(result)


def main() -> None:
    parser = argparse.ArgumentParser(description="Normalizar mayúsculas en empleados")
    parser.add_argument("--dry-run", action="store_true", help="Solo mostrar cambios")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        empleados = db.query(RRHHEmpleado).order_by(RRHHEmpleado.id).all()
        print(f"Empleados en DB: {len(empleados)}")
        print()

        cambios = 0
        for emp in empleados:
            emp_cambios = []
            for campo in CAMPOS_TITLE_CASE:
                valor = getattr(emp, campo, None)
                if not valor or not isinstance(valor, str):
                    continue

                nuevo = smart_title(valor)
                if nuevo != valor:
                    emp_cambios.append((campo, valor, nuevo))
                    if not args.dry_run:
                        setattr(emp, campo, nuevo)

            # datos_custom (nacionalidad, estado_civil)
            if emp.datos_custom and isinstance(emp.datos_custom, dict):
                updated_custom = dict(emp.datos_custom)
                custom_changed = False
                for key in ("nacionalidad", "estado_civil"):
                    val = updated_custom.get(key)
                    if val and isinstance(val, str):
                        nuevo = smart_title(val)
                        if nuevo != val:
                            emp_cambios.append((f"datos_custom.{key}", val, nuevo))
                            updated_custom[key] = nuevo
                            custom_changed = True
                if custom_changed and not args.dry_run:
                    emp.datos_custom = updated_custom

            if emp_cambios:
                cambios += 1
                print(f"── {emp.legajo} {emp.apellido}, {emp.nombre} ──")
                for campo, antes, despues in emp_cambios:
                    print(f"  {campo}: {antes!r} → {despues!r}")
                print()

        if not args.dry_run and cambios > 0:
            db.commit()

        print(f"{'=' * 50}")
        if args.dry_run:
            print(f"DRY RUN: {cambios} empleados con cambios (no se guardó nada)")
        else:
            print(f"Normalizados: {cambios} empleados")

    except Exception as e:
        db.rollback()
        print(f"ERROR: {e}")
        sys.exit(1)
    finally:
        db.close()


if __name__ == "__main__":
    main()
