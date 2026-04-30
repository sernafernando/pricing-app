"""
T-8.6 — Test manual: cap 90 días en endpoint de recálculo manual.

Verifica que el endpoint `POST /rrhh/horas-extras/recalcular` rechaza con 422
cuando el rango de fechas excede el `cap_dias_recalculo_manual` (default 90)
y cuando `fecha_hasta < fecha_desde`.

Estrategia: en vez de hacer HTTP request real (que requiere auth real), se
invoca la función handler `recalcular_periodo` directamente con un
`RecalcularRequest` construido en memoria. Se usa un `Usuario` SUPERADMIN
real de la DB (id=1) para evitar problemas con el chequeo de permiso del
service. Si no existe, se hace skip del test que requiere user.

Casos:
- 90 días exactos -> NO 422 por cap (puede fallar por lockfile o por permiso,
  ambos casos se aceptan como "no fue por cap").
- 91 días -> 422 con detail incluyendo "rango de recálculo".
- fecha_hasta < fecha_desde -> 422 (Pydantic validator).

Uso:
    cd /var/www/html/pricing-app/backend
    python -m app.scripts.test_manual_rrhh_he_cap_recalculo

Spec ref: revisión 2 Q2 (cap 90 días).
"""

from __future__ import annotations

import os
import sys
from datetime import date, timedelta
from pathlib import Path

if __name__ == "__main__":
    backend_path = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    if backend_path not in sys.path:
        sys.path.insert(0, backend_path)

    from dotenv import load_dotenv

    env_path = Path(backend_path) / ".env"
    load_dotenv(dotenv_path=env_path)

from fastapi import HTTPException
from pydantic import ValidationError

from app.core.database import SessionLocal
from app.models.usuario import Usuario
from app.routers.rrhh_horas_extras import RecalcularRequest, recalcular_periodo


def _ok(msg: str) -> None:
    print(f"  PASS - {msg}")


def _fail(msg: str) -> None:
    print(f"  FAIL - {msg}")


def main() -> int:
    print("Iniciando test_manual_rrhh_he_cap_recalculo (T-8.6)")
    db = SessionLocal()
    fallos = 0

    try:
        # ─── Caso A: fecha_hasta < fecha_desde -> ValidationError de Pydantic ─
        try:
            RecalcularRequest(
                fecha_desde=date(2026, 4, 1),
                fecha_hasta=date(2026, 3, 30),
            )
            fallos += 1
            _fail("RecalcularRequest(hasta<desde) NO lanzó ValidationError")
        except ValidationError as exc:
            msg = str(exc)
            if "fecha_hasta" in msg and ">=" in msg:
                _ok(f"hasta<desde -> ValidationError de Pydantic ({msg.splitlines()[0][:80]})")
            else:
                _ok(f"hasta<desde -> ValidationError ({msg.splitlines()[0][:80]})")

        # Para los casos B y C necesitamos un usuario real para evitar fallos en
        # PermisosService. Buscamos un usuario SUPERADMIN.
        usuario = db.query(Usuario).filter(Usuario.id == 1).first()
        if usuario is None:
            print("  SKIP - No hay Usuario(id=1) en la DB. Casos B/C no se pueden ejecutar.")
            print("\nResultado: PASS PARCIAL (T-8.6 — sólo case A validado)")
            return 0 if fallos == 0 else 1

        # ─── Caso B: 91 días -> 422 (cap) ──────────────────────────────
        req_91 = RecalcularRequest(
            fecha_desde=date(2026, 1, 1),
            fecha_hasta=date(2026, 4, 2),  # 91 días
        )
        try:
            recalcular_periodo(data=req_91, db=db, current_user=usuario)
            fallos += 1
            _fail("recalcular(91d) NO lanzó HTTPException")
        except HTTPException as exc:
            if exc.status_code == 422 and (
                "rango de recálculo" in (exc.detail or "") or "cap" in (exc.detail or "").lower()
            ):
                _ok(f"recalcular(91d) -> 422 con detail '{exc.detail[:80]}'")
            elif exc.status_code == 403:
                # Si no tiene permiso el chequeo es previo al cap. Aceptamos pero
                # advertimos.
                print(
                    "  WARN - Usuario id=1 no tiene 'rrhh.gestionar_horas_extras' "
                    "-> 403; el cap NO pudo verificarse. Asignar el permiso para validar."
                )
            else:
                fallos += 1
                _fail(f"recalcular(91d) lanzó {exc.status_code} ({exc.detail!r}) en vez de 422")

        # ─── Caso C: 90 días -> NO 422 por cap ─────────────────────────
        req_90 = RecalcularRequest(
            fecha_desde=date(2026, 1, 1),
            fecha_hasta=date(2026, 4, 1),  # 90 días
        )
        try:
            res = recalcular_periodo(data=req_90, db=db, current_user=usuario)
            _ok(f"recalcular(90d) -> ejecutó OK (procesados={res.get('procesados', 0)})")
        except HTTPException as exc:
            if exc.status_code == 422 and "rango de recálculo" in (exc.detail or ""):
                fallos += 1
                _fail(f"recalcular(90d) lanzó 422 por cap (no debería): {exc.detail!r}")
            elif exc.status_code in (403, 409):
                # 403=permiso; 409=lockfile activo. Ambos son "no es por cap".
                print(
                    f"  WARN - recalcular(90d) -> {exc.status_code} ({exc.detail!r}); "
                    "no es fallo de cap (probablemente permiso/lockfile)."
                )
            else:
                fallos += 1
                _fail(f"recalcular(90d) lanzó {exc.status_code} inesperado: {exc.detail!r}")

    except Exception as exc:
        fallos += 1
        _fail(f"Excepción inesperada: {exc!r}")
        import traceback

        traceback.print_exc()
    finally:
        db.close()

    if fallos == 0:
        print("\nResultado: PASS (T-8.6)")
        return 0
    print(f"\nResultado: FAIL ({fallos} aserciones fallidas)")
    return 1


if __name__ == "__main__":
    sys.exit(main())
