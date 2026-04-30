"""
T-8.2 — Test manual: cálculo HE turno mañana+tarde (3 scenarios del spec).

Verifica los 3 casos canónicos del spec con un empleado de prueba que tiene
turno 08:00-13:00 + 15:00-19:00 (teórico 9h = 540 min):

- Caso 1 — fichadas 08:00->13:00, 15:00->19:00 (4 fichadas, 9h trabajadas)
  -> NO debe persistir registro de HE (extras=0, descartado por tolerancia).
- Caso 2 — fichadas 08:00->19:00 (2 fichadas, 11h trabajadas, sin pausa)
  -> 1 bloque HE con extras_minutos=120 (120 = 11h-9h).
- Caso 3 — fichadas 08:00->13:00, 15:00->20:00 (4 fichadas, 10h trabajadas)
  -> 1 bloque HE con extras_minutos=60.

Toda la data creada (empleado, horarios, fichadas, bloques HE, historial) se
borra al final aunque haya fallos.

Uso:
    cd /var/www/html/pricing-app/backend
    python -m app.scripts.test_manual_rrhh_he_calculo_dia

Spec ref: "Detección automática de horas extras por bloque empleado-día-tipo_dia",
scenarios 1-3.
"""

from __future__ import annotations

import os
import sys
from datetime import date, datetime, time, timedelta
from pathlib import Path

if __name__ == "__main__":
    backend_path = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    if backend_path not in sys.path:
        sys.path.insert(0, backend_path)

    from dotenv import load_dotenv

    env_path = Path(backend_path) / ".env"
    load_dotenv(dotenv_path=env_path)

import time as time_mod

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


SUFFIX = f"T82_{int(time_mod.time())}"


def _ok(msg: str) -> None:
    print(f"  PASS - {msg}")


def _fail(msg: str) -> None:
    print(f"  FAIL - {msg}")


def _crear_empleado_test(db) -> RRHHEmpleado:
    emp = RRHHEmpleado(
        nombre="Test",
        apellido=f"TEST_HE_{SUFFIX}",
        legajo=f"TST{SUFFIX[:14]}",
        estado="activo",
        activo=True,
    )
    db.add(emp)
    db.commit()
    db.refresh(emp)
    return emp


def _crear_horario(db, nombre: str, hi: time, hf: time) -> RRHHHorarioConfig:
    h = RRHHHorarioConfig(
        nombre=nombre,
        hora_entrada=hi,
        hora_salida=hf,
        dias_semana="1,2,3,4,5",
        activo=True,
    )
    db.add(h)
    db.commit()
    db.refresh(h)
    return h


def _asignar_horario(db, empleado_id: int, horario_config_id: int) -> RRHHEmpleadoHorario:
    eh = RRHHEmpleadoHorario(
        empleado_id=empleado_id,
        horario_config_id=horario_config_id,
        prioridad=0,
    )
    db.add(eh)
    db.commit()
    return eh


def _crear_fichadas(db, empleado_id: int, fecha: date, pares: list[tuple[time, time]]) -> list[RRHHFichada]:
    """Crea fichadas alternando entrada/salida para los pares dados."""
    fichadas: list[RRHHFichada] = []
    for hi, hf in pares:
        f_in = RRHHFichada(
            empleado_id=empleado_id,
            timestamp=datetime.combine(fecha, hi),
            tipo="entrada",
            origen="manual",
            motivo_manual=f"TEST_HE_{SUFFIX}",
        )
        f_out = RRHHFichada(
            empleado_id=empleado_id,
            timestamp=datetime.combine(fecha, hf),
            tipo="salida",
            origen="manual",
            motivo_manual=f"TEST_HE_{SUFFIX}",
        )
        db.add(f_in)
        db.add(f_out)
        fichadas.append(f_in)
        fichadas.append(f_out)
    db.commit()
    return fichadas


def _limpiar_caso(db, empleado_id: int, fecha: date) -> None:
    """Borra fichadas + bloques HE + historial + alertas para (emp, fecha)."""
    # Alertas y historial primero (FK).
    he_ids = [
        b.id
        for b in db.query(RRHHHorasExtras)
        .filter(RRHHHorasExtras.empleado_id == empleado_id, RRHHHorasExtras.fecha == fecha)
        .all()
    ]
    if he_ids:
        db.query(RRHHHorasExtrasAlerta).filter(RRHHHorasExtrasAlerta.he_id.in_(he_ids)).delete(
            synchronize_session=False
        )
        db.query(RRHHHorasExtrasHistorial).filter(RRHHHorasExtrasHistorial.he_id.in_(he_ids)).delete(
            synchronize_session=False
        )
        db.query(RRHHHorasExtras).filter(RRHHHorasExtras.id.in_(he_ids)).delete(synchronize_session=False)
    db.query(RRHHFichada).filter(
        RRHHFichada.empleado_id == empleado_id,
        RRHHFichada.timestamp >= datetime.combine(fecha, time(0, 0)),
        RRHHFichada.timestamp < datetime.combine(fecha + timedelta(days=1), time(0, 0)),
    ).delete(synchronize_session=False)
    db.commit()


def _proximo_martes(base: date | None = None) -> date:
    base = base or date.today()
    # Buscamos un martes pasado (no futuro) para que las fichadas tengan sentido
    # con timestamps en datetime.now() puede que la fecha sea hoy.
    # Para test, usamos hoy si es martes, o martes pasado.
    delta_back = (base.weekday() - 1) % 7
    martes = base - timedelta(days=delta_back) if base.weekday() != 1 else base
    return martes


def main() -> int:
    print(f"Iniciando test_manual_rrhh_he_calculo_dia (T-8.2) — suffix {SUFFIX}")
    db = SessionLocal()
    fallos = 0
    empleado: RRHHEmpleado | None = None
    horario_manana: RRHHHorarioConfig | None = None
    horario_tarde: RRHHHorarioConfig | None = None
    fecha_test = _proximo_martes() - timedelta(days=7)  # martes pasado, lejos de hoy

    try:
        service = HorasExtrasService(db)

        # Setup: empleado + 2 turnos.
        empleado = _crear_empleado_test(db)
        horario_manana = _crear_horario(db, f"TEST_HE_{SUFFIX}_M", time(8, 0), time(13, 0))
        horario_tarde = _crear_horario(db, f"TEST_HE_{SUFFIX}_T", time(15, 0), time(19, 0))
        _asignar_horario(db, empleado.id, horario_manana.id)
        _asignar_horario(db, empleado.id, horario_tarde.id)
        print(
            f"  Setup OK: empleado_id={empleado.id}, turnos {horario_manana.id}+{horario_tarde.id}, fecha {fecha_test}"
        )

        # ─── CASO 1: Empleado cumple turno exacto, 4 fichadas, 0 HE ───
        _crear_fichadas(
            db,
            empleado.id,
            fecha_test,
            [(time(8, 0), time(13, 0)), (time(15, 0), time(19, 0))],
        )
        service.detectar_he_periodo(fecha_test, fecha_test, empleado_ids=[empleado.id])
        bloques = (
            db.query(RRHHHorasExtras)
            .filter(
                RRHHHorasExtras.empleado_id == empleado.id,
                RRHHHorasExtras.fecha == fecha_test,
            )
            .all()
        )
        if len(bloques) == 0:
            _ok("Caso 1: turno exacto 8-13/15-19 -> NO se persiste bloque (0 HE)")
        else:
            fallos += 1
            _fail(f"Caso 1 esperaba 0 bloques; got {len(bloques)} ({[(b.estado, b.extras_minutos) for b in bloques]})")
        _limpiar_caso(db, empleado.id, fecha_test)

        # ─── CASO 2: Sin pausa 08:00->19:00, 2 fichadas, 120 min HE ───
        _crear_fichadas(
            db,
            empleado.id,
            fecha_test,
            [(time(8, 0), time(19, 0))],
        )
        service.detectar_he_periodo(fecha_test, fecha_test, empleado_ids=[empleado.id])
        bloques = (
            db.query(RRHHHorasExtras)
            .filter(
                RRHHHorasExtras.empleado_id == empleado.id,
                RRHHHorasExtras.fecha == fecha_test,
            )
            .all()
        )
        if (
            len(bloques) == 1
            and bloques[0].extras_minutos == 120
            and bloques[0].estado == EstadoHE.DETECTADA.value
            and bloques[0].trabajado_minutos == 660
            and bloques[0].turno_esperado_minutos == 540
        ):
            _ok("Caso 2: sin pausa 8-19 -> 1 bloque detectada, extras=120, trabajado=660, esperado=540")
        else:
            fallos += 1
            _fail(
                f"Caso 2 esperaba 1 bloque(extras=120,trab=660,esp=540,detectada); "
                f"got {[(b.estado, b.extras_minutos, b.trabajado_minutos, b.turno_esperado_minutos) for b in bloques]}"
            )
        _limpiar_caso(db, empleado.id, fecha_test)

        # ─── CASO 3: Se queda hasta 20:00, 4 fichadas, 60 min HE ──────
        _crear_fichadas(
            db,
            empleado.id,
            fecha_test,
            [(time(8, 0), time(13, 0)), (time(15, 0), time(20, 0))],
        )
        service.detectar_he_periodo(fecha_test, fecha_test, empleado_ids=[empleado.id])
        bloques = (
            db.query(RRHHHorasExtras)
            .filter(
                RRHHHorasExtras.empleado_id == empleado.id,
                RRHHHorasExtras.fecha == fecha_test,
            )
            .all()
        )
        if (
            len(bloques) == 1
            and bloques[0].extras_minutos == 60
            and bloques[0].estado == EstadoHE.DETECTADA.value
            and bloques[0].trabajado_minutos == 600
            and bloques[0].turno_esperado_minutos == 540
        ):
            _ok("Caso 3: 8-13 + 15-20 -> 1 bloque detectada, extras=60, trabajado=600, esperado=540")
        else:
            fallos += 1
            _fail(
                f"Caso 3 esperaba 1 bloque(extras=60,trab=600,esp=540,detectada); "
                f"got {[(b.estado, b.extras_minutos, b.trabajado_minutos, b.turno_esperado_minutos) for b in bloques]}"
            )

    except Exception as exc:
        fallos += 1
        _fail(f"Excepción inesperada: {exc!r}")
        import traceback

        traceback.print_exc()
    finally:
        # Cleanup completo.
        try:
            if empleado is not None:
                _limpiar_caso(db, empleado.id, fecha_test)
                # Borrar asignaciones + horarios + empleado.
                db.query(RRHHEmpleadoHorario).filter(RRHHEmpleadoHorario.empleado_id == empleado.id).delete(
                    synchronize_session=False
                )
                db.commit()
            for h in (horario_manana, horario_tarde):
                if h is not None:
                    row = db.query(RRHHHorarioConfig).filter(RRHHHorarioConfig.id == h.id).first()
                    if row is not None:
                        db.delete(row)
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
        print("\nResultado: PASS (T-8.2)")
        return 0
    print(f"\nResultado: FAIL ({fallos} aserciones fallidas)")
    return 1


if __name__ == "__main__":
    sys.exit(main())
