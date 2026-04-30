"""
T-8.5 — Test manual: event listener de cambio en RRHHEmpleadoHorario.

Verifica el flujo de revisión 2 (Q3): cuando se modifica/inserta/elimina la
asignación de turno de un empleado, el hook `after_commit` dispara
`recalcular_por_cambio_turno`, que:
- Sobre bloques `aprobada`/`rechazada`: revierte a `detectada` (audit).
- Sobre bloques `liquidada`: NO modifica; INSERT alerta
  `liquidacion_afectada_por_cambio_turno` con severidad `critical`.

Flujo:
1. Crear empleado + horario + fichadas + bloque liquidado (periodo 202604).
2. Modificar la asignación del empleado (touch update) -> commit.
3. Verificar: bloque liquidado SIGUE liquidado, y se generó alerta
   `liquidacion_afectada_por_cambio_turno` con severidad='critical'.

Uso:
    cd /var/www/html/pricing-app/backend
    python -m app.scripts.test_manual_rrhh_he_listener_horario

Spec ref: revisión 2 Q3 (cambio empleado_horario afecta liquidados).
"""

from __future__ import annotations

import os
import sys
import time as time_mod
from datetime import date, datetime, time, timedelta
from pathlib import Path

if __name__ == "__main__":
    backend_path = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    if backend_path not in sys.path:
        sys.path.insert(0, backend_path)

    from dotenv import load_dotenv

    env_path = Path(backend_path) / ".env"
    load_dotenv(dotenv_path=env_path)

# Registrar listeners.
import app.events.rrhh_he_hooks  # noqa: F401

from app.core.database import SessionLocal
from app.models.rrhh_empleado import RRHHEmpleado
from app.models.rrhh_empleado_horario import RRHHEmpleadoHorario
from app.models.rrhh_fichada import RRHHFichada
from app.models.rrhh_horario import RRHHHorarioConfig
from app.models.rrhh_horas_extras import (
    EstadoHE,
    RRHHHorasExtras,
    RRHHHorasExtrasAlerta,
    RRHHHorasExtrasHistorial,
)
from app.services.rrhh_horas_extras_service import HorasExtrasService


SUFFIX = f"T85_{int(time_mod.time())}"
USUARIO_TEST_ID = 1
PERIODO_TEST = "202604"


def _ok(msg: str) -> None:
    print(f"  PASS - {msg}")


def _fail(msg: str) -> None:
    print(f"  FAIL - {msg}")


def main() -> int:
    print(f"Iniciando test_manual_rrhh_he_listener_horario (T-8.5) — suffix {SUFFIX}")
    db = SessionLocal()
    fallos = 0
    empleado: RRHHEmpleado | None = None
    horario: RRHHHorarioConfig | None = None
    fecha_test = date.today() - timedelta(days=30)
    if fecha_test.weekday() >= 5:
        fecha_test = fecha_test - timedelta(days=fecha_test.weekday() - 4)

    try:
        service = HorasExtrasService(db)

        # Setup empleado + horario + fichadas + bloque LIQUIDADO.
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

        horario = RRHHHorarioConfig(
            nombre=f"TEST_HE_{SUFFIX}_F",
            hora_entrada=time(8, 0),
            hora_salida=time(13, 0),
            dias_semana="1,2,3,4,5",
            activo=True,
        )
        db.add(horario)
        db.commit()
        db.refresh(horario)

        eh = RRHHEmpleadoHorario(empleado_id=empleado.id, horario_config_id=horario.id, prioridad=0)
        db.add(eh)

        f_in = RRHHFichada(
            empleado_id=empleado.id,
            timestamp=datetime.combine(fecha_test, time(8, 0)),
            tipo="entrada",
            origen="manual",
            motivo_manual=f"TEST_HE_{SUFFIX}",
        )
        f_out = RRHHFichada(
            empleado_id=empleado.id,
            timestamp=datetime.combine(fecha_test, time(14, 30)),
            tipo="salida",
            origen="manual",
            motivo_manual=f"TEST_HE_{SUFFIX}",
        )
        db.add(f_in)
        db.add(f_out)
        db.commit()

        # Detectar -> aprobar -> liquidar.
        service.detectar_he_periodo(fecha_test, fecha_test, empleado_ids=[empleado.id])
        bloque = (
            db.query(RRHHHorasExtras)
            .filter(
                RRHHHorasExtras.empleado_id == empleado.id,
                RRHHHorasExtras.fecha == fecha_test,
            )
            .first()
        )
        if bloque is None:
            fallos += 1
            _fail("Setup: bloque HE no creado")
            return 1
        service.aprobar_bloque(bloque.id, USUARIO_TEST_ID)
        service.liquidar_periodo(periodo=PERIODO_TEST, ids=[bloque.id], usuario_id=USUARIO_TEST_ID)
        db.refresh(bloque)
        if bloque.estado != EstadoHE.LIQUIDADA.value:
            fallos += 1
            _fail(f"Setup: bloque no quedó liquidado (estado={bloque.estado})")
            return 1
        _ok(f"Setup: bloque #{bloque.id} liquidado periodo={PERIODO_TEST}")

        # ─── Modificar la asignación del empleado -> hook horario ──────
        # Hacemos un "touch" cambiando prioridad para que dispare after_update.
        eh_db = (
            db.query(RRHHEmpleadoHorario)
            .filter(
                RRHHEmpleadoHorario.empleado_id == empleado.id,
                RRHHEmpleadoHorario.horario_config_id == horario.id,
            )
            .first()
        )
        eh_db.prioridad = (eh_db.prioridad or 0) + 1
        db.commit()  # dispara after_update -> after_commit -> recalcular_por_cambio_turno

        # Verificar: bloque liquidado SIGUE liquidado.
        db.refresh(bloque)
        if bloque.estado == EstadoHE.LIQUIDADA.value:
            _ok("Tras cambio de turno: bloque liquidado permanece liquidado")
        else:
            fallos += 1
            _fail(f"Bloque liquidado cambió a '{bloque.estado}' tras hook horario")

        # Verificar alerta liquidacion_afectada_por_cambio_turno.
        alertas_critical = (
            db.query(RRHHHorasExtrasAlerta)
            .filter(
                RRHHHorasExtrasAlerta.he_id == bloque.id,
                RRHHHorasExtrasAlerta.tipo == "liquidacion_afectada_por_cambio_turno",
            )
            .all()
        )
        if alertas_critical:
            severidades = {a.severidad for a in alertas_critical}
            if "critical" in severidades:
                _ok(
                    f"Alerta 'liquidacion_afectada_por_cambio_turno' creada "
                    f"(count={len(alertas_critical)}, severidad=critical)"
                )
            else:
                fallos += 1
                _fail(f"Alerta creada pero severidades={severidades} (esperaba 'critical')")
        else:
            fallos += 1
            _fail(
                "NO se creó alerta 'liquidacion_afectada_por_cambio_turno'. ¿Listener registrado? ¿el hook se ejecutó?"
            )

    except Exception as exc:
        fallos += 1
        _fail(f"Excepción inesperada: {exc!r}")
        import traceback

        traceback.print_exc()
    finally:
        try:
            if empleado is not None:
                he_ids = [
                    b.id for b in db.query(RRHHHorasExtras).filter(RRHHHorasExtras.empleado_id == empleado.id).all()
                ]
                if he_ids:
                    db.query(RRHHHorasExtrasAlerta).filter(RRHHHorasExtrasAlerta.he_id.in_(he_ids)).delete(
                        synchronize_session=False
                    )
                    db.query(RRHHHorasExtrasHistorial).filter(RRHHHorasExtrasHistorial.he_id.in_(he_ids)).delete(
                        synchronize_session=False
                    )
                    db.query(RRHHHorasExtras).filter(RRHHHorasExtras.id.in_(he_ids)).delete(synchronize_session=False)
                db.query(RRHHFichada).filter(RRHHFichada.empleado_id == empleado.id).delete(synchronize_session=False)
                db.query(RRHHEmpleadoHorario).filter(RRHHEmpleadoHorario.empleado_id == empleado.id).delete(
                    synchronize_session=False
                )
                db.commit()
                if horario is not None:
                    row_h = db.query(RRHHHorarioConfig).filter(RRHHHorarioConfig.id == horario.id).first()
                    if row_h is not None:
                        db.delete(row_h)
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
        print("\nResultado: PASS (T-8.5)")
        return 0
    print(f"\nResultado: FAIL ({fallos} aserciones fallidas)")
    return 1


if __name__ == "__main__":
    sys.exit(main())
