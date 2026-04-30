"""
T-8.7 — Test manual: purga de alertas leídas viejas.

Verifica que `HorasExtrasService.purgar_alertas_viejas(dias=15)`:
- Hard-deletea alertas LEÍDAS (`leida_at IS NOT NULL`) cuyo `created_at` es
  más viejo que `today - dias`.
- NUNCA borra alertas no leídas (sin importar antigüedad).
- Conserva alertas leídas recientes.

Setup:
- Crea un bloque HE de prueba.
- Inserta 5 alertas con `created_at = now - 20 días` y `leida_at = now - 19 días`
  (leídas + viejas) -> deben purgarse.
- Inserta 3 alertas con `created_at = now - 5 días` y `leida_at = now - 4 días`
  (leídas + recientes) -> NO deben purgarse.
- Inserta 2 alertas con `created_at = now - 30 días` y `leida_at = NULL`
  (no leídas, viejas) -> NO deben purgarse.

Ejecuta `purgar_alertas_viejas(dias=15)` y verifica los counts.

Uso:
    cd /var/www/html/pricing-app/backend
    python -m app.scripts.test_manual_rrhh_he_purga

Spec ref: revisión 2 Q4 (purga de alertas).
"""

from __future__ import annotations

import os
import sys
import time as time_mod
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from pathlib import Path

if __name__ == "__main__":
    backend_path = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    if backend_path not in sys.path:
        sys.path.insert(0, backend_path)

    from dotenv import load_dotenv

    env_path = Path(backend_path) / ".env"
    load_dotenv(dotenv_path=env_path)

from app.core.database import SessionLocal
from app.models.rrhh_empleado import RRHHEmpleado
from app.models.rrhh_horas_extras import (
    EstadoHE,
    GeneradaPorHE,
    RRHHHorasExtras,
    RRHHHorasExtrasAlerta,
    RRHHHorasExtrasHistorial,
    TipoDiaHE,
)
from app.services.rrhh_horas_extras_service import HorasExtrasService


SUFFIX = f"T87_{int(time_mod.time())}"


def _ok(msg: str) -> None:
    print(f"  PASS - {msg}")


def _fail(msg: str) -> None:
    print(f"  FAIL - {msg}")


def main() -> int:
    print(f"Iniciando test_manual_rrhh_he_purga (T-8.7) — suffix {SUFFIX}")
    db = SessionLocal()
    fallos = 0
    empleado: RRHHEmpleado | None = None
    bloque: RRHHHorasExtras | None = None
    alerta_ids_creadas: list[int] = []
    fecha_test = date.today() - timedelta(days=60)
    if fecha_test.weekday() >= 5:
        fecha_test = fecha_test - timedelta(days=fecha_test.weekday() - 4)

    try:
        service = HorasExtrasService(db)

        # Setup empleado + bloque mínimo (para FK he_id de las alertas).
        empleado = RRHHEmpleado(
            nombre="Test",
            apellido=f"TEST_HE_{SUFFIX}",
            legajo=f"TST{SUFFIX[:14]}",
            estado="activo",
            activo=True,
        )
        db.add(empleado)
        db.commit()
        db.refresh(empleado)

        bloque = RRHHHorasExtras(
            empleado_id=empleado.id,
            fecha=fecha_test,
            turno_esperado_minutos=480,
            trabajado_minutos=540,
            extras_minutos=60,
            tipo_dia=TipoDiaHE.HABIL_50.value,
            porcentaje_recargo=Decimal("50.00"),
            estado=EstadoHE.DETECTADA.value,
            generada_por=GeneradaPorHE.SISTEMA.value,
        )
        db.add(bloque)
        db.commit()
        db.refresh(bloque)
        _ok(f"Setup: empleado #{empleado.id}, bloque #{bloque.id}")

        ahora = datetime.now()

        # ─── 5 alertas LEÍDAS + VIEJAS (deben purgarse) ───────────────
        for i in range(5):
            a = RRHHHorasExtrasAlerta(
                he_id=bloque.id,
                tipo="fichada_modificada",
                severidad="warning",
                mensaje=f"TEST_HE_{SUFFIX} vieja_leida #{i}",
                contexto={"test": SUFFIX, "grupo": "vieja_leida", "i": i},
                leida_at=ahora - timedelta(days=19),
            )
            db.add(a)
        db.flush()
        # Override created_at via UPDATE (default es ahora).
        for a in (
            db.query(RRHHHorasExtrasAlerta)
            .filter(RRHHHorasExtrasAlerta.mensaje.like(f"TEST_HE_{SUFFIX} vieja_leida%"))
            .all()
        ):
            a.created_at = ahora - timedelta(days=20)
            alerta_ids_creadas.append(a.id)
        db.commit()

        # ─── 3 alertas LEÍDAS + RECIENTES (NO purgar) ──────────────────
        for i in range(3):
            a = RRHHHorasExtrasAlerta(
                he_id=bloque.id,
                tipo="fichada_modificada",
                severidad="warning",
                mensaje=f"TEST_HE_{SUFFIX} reciente_leida #{i}",
                contexto={"test": SUFFIX, "grupo": "reciente_leida", "i": i},
                leida_at=ahora - timedelta(days=4),
            )
            db.add(a)
        db.flush()
        for a in (
            db.query(RRHHHorasExtrasAlerta)
            .filter(RRHHHorasExtrasAlerta.mensaje.like(f"TEST_HE_{SUFFIX} reciente_leida%"))
            .all()
        ):
            a.created_at = ahora - timedelta(days=5)
            alerta_ids_creadas.append(a.id)
        db.commit()

        # ─── 2 alertas NO LEÍDAS + VIEJAS (NO purgar) ──────────────────
        for i in range(2):
            a = RRHHHorasExtrasAlerta(
                he_id=bloque.id,
                tipo="fichada_modificada",
                severidad="warning",
                mensaje=f"TEST_HE_{SUFFIX} no_leida_vieja #{i}",
                contexto={"test": SUFFIX, "grupo": "no_leida_vieja", "i": i},
                leida_at=None,
            )
            db.add(a)
        db.flush()
        for a in (
            db.query(RRHHHorasExtrasAlerta)
            .filter(RRHHHorasExtrasAlerta.mensaje.like(f"TEST_HE_{SUFFIX} no_leida_vieja%"))
            .all()
        ):
            a.created_at = ahora - timedelta(days=30)
            alerta_ids_creadas.append(a.id)
        db.commit()

        _ok("Setup: 10 alertas insertadas (5 vieja_leida + 3 reciente_leida + 2 no_leida_vieja)")

        # Snapshots PRE-purga.
        pre_total = db.query(RRHHHorasExtrasAlerta).filter(RRHHHorasExtrasAlerta.he_id == bloque.id).count()
        if pre_total != 10:
            print(f"  WARN - Pre-purga: {pre_total} alertas (esperaba 10)")

        # ─── Ejecutar purga ────────────────────────────────────────────
        res = service.purgar_alertas_viejas(dias=15)

        # Verificar contadores reportados por el método.
        # purgadas debe ser 5; retenidas debe ser >= 2 (las no leídas; cuenta global).
        if res.get("purgadas", -1) >= 5:
            _ok(f"purgar(dias=15) reporta purgadas={res['purgadas']} (>= 5 esperadas)")
        else:
            fallos += 1
            _fail(f"purgar reportó purgadas={res.get('purgadas')} (esperaba >=5)")

        # ─── Verificar estado en DB ────────────────────────────────────
        # 1. 5 vieja_leida deben estar BORRADAS.
        vieja_leida = (
            db.query(RRHHHorasExtrasAlerta)
            .filter(RRHHHorasExtrasAlerta.mensaje.like(f"TEST_HE_{SUFFIX} vieja_leida%"))
            .count()
        )
        if vieja_leida == 0:
            _ok("5 alertas (leídas + viejas) eliminadas de la DB")
        else:
            fallos += 1
            _fail(f"Quedaron {vieja_leida} alertas vieja_leida (esperaba 0)")

        # 2. 3 reciente_leida deben SEGUIR.
        reciente_leida = (
            db.query(RRHHHorasExtrasAlerta)
            .filter(RRHHHorasExtrasAlerta.mensaje.like(f"TEST_HE_{SUFFIX} reciente_leida%"))
            .count()
        )
        if reciente_leida == 3:
            _ok("3 alertas leídas pero recientes (-5d) NO purgadas")
        else:
            fallos += 1
            _fail(f"Quedaron {reciente_leida} alertas reciente_leida (esperaba 3)")

        # 3. 2 no_leida_vieja deben SEGUIR.
        no_leida_vieja = (
            db.query(RRHHHorasExtrasAlerta)
            .filter(RRHHHorasExtrasAlerta.mensaje.like(f"TEST_HE_{SUFFIX} no_leida_vieja%"))
            .count()
        )
        if no_leida_vieja == 2:
            _ok("2 alertas NO leídas (aunque viejas) preservadas")
        else:
            fallos += 1
            _fail(f"Quedaron {no_leida_vieja} alertas no_leida_vieja (esperaba 2)")

    except Exception as exc:
        fallos += 1
        _fail(f"Excepción inesperada: {exc!r}")
        import traceback

        traceback.print_exc()
    finally:
        try:
            if bloque is not None:
                db.query(RRHHHorasExtrasAlerta).filter(RRHHHorasExtrasAlerta.he_id == bloque.id).delete(
                    synchronize_session=False
                )
                db.query(RRHHHorasExtrasHistorial).filter(RRHHHorasExtrasHistorial.he_id == bloque.id).delete(
                    synchronize_session=False
                )
                row_b = db.query(RRHHHorasExtras).filter(RRHHHorasExtras.id == bloque.id).first()
                if row_b is not None:
                    db.delete(row_b)
            if empleado is not None:
                row_emp = db.query(RRHHEmpleado).filter(RRHHEmpleado.id == empleado.id).first()
                if row_emp is not None:
                    db.delete(row_emp)
            db.commit()
            print("  Cleanup OK")
        except Exception as cleanup_exc:
            print(f"  WARN - Cleanup falló: {cleanup_exc!r}")
        finally:
            db.close()

    if fallos == 0:
        print("\nResultado: PASS (T-8.7)")
        return 0
    print(f"\nResultado: FAIL ({fallos} aserciones fallidas)")
    return 1


if __name__ == "__main__":
    sys.exit(main())
