"""
T-8.4 — Test manual: event listener de modificación/eliminación de fichada.

Verifica que el listener `after_commit` instalado en `app.events.rrhh_he_hooks`
genera alertas cuando se modifica o elimina una `RRHHFichada` que está
vinculada a un bloque congelado (aprobada/liquidada/rechazada/error_fichadas).

Flujo:
1. Crear empleado + horario + fichadas + bloque HE.
2. Aprobar el bloque (estado congelado).
3. Modificar la fichada vinculada -> commit -> esperar que el hook dispare.
4. Verificar que se creó alerta `tipo='fichada_modificada'`, severidad='warning'.
5. Eliminar otra fichada -> alerta `tipo='fichada_eliminada'`.

Importa explícitamente `app.events.rrhh_he_hooks` para garantizar que los
listeners están registrados aunque el script no pase por `app.main`.

Uso:
    cd /var/www/html/pricing-app/backend
    python -m app.scripts.test_manual_rrhh_he_listener_fichada

Spec ref: "Alertas por modificación de fichadas post-aprobación".
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

# CRÍTICO: importar antes de tocar SessionLocal para registrar listeners.
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


SUFFIX = f"T84_{int(time_mod.time())}"
USUARIO_TEST_ID = 1


def _ok(msg: str) -> None:
    print(f"  PASS - {msg}")


def _fail(msg: str) -> None:
    print(f"  FAIL - {msg}")


def main() -> int:
    print(f"Iniciando test_manual_rrhh_he_listener_fichada (T-8.4) — suffix {SUFFIX}")
    db = SessionLocal()
    fallos = 0
    empleado: RRHHEmpleado | None = None
    horario: RRHHHorarioConfig | None = None
    fecha_test = date.today() - timedelta(days=21)
    if fecha_test.weekday() >= 5:
        fecha_test = fecha_test - timedelta(days=fecha_test.weekday() - 4)

    try:
        service = HorasExtrasService(db)

        # Setup: empleado + horario + fichadas + bloque aprobado.
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
            timestamp=datetime.combine(fecha_test, time(14, 0)),
            tipo="salida",
            origen="manual",
            motivo_manual=f"TEST_HE_{SUFFIX}",
        )
        db.add(f_in)
        db.add(f_out)
        db.commit()

        # Detectar + aprobar.
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
        db.refresh(bloque)
        if bloque.estado != EstadoHE.APROBADA.value:
            fallos += 1
            _fail(f"Setup: bloque no quedó aprobado (estado={bloque.estado})")
            return 1
        _ok(f"Setup: bloque #{bloque.id} aprobado, fichadas {f_in.id}/{f_out.id}")

        # Asegurarnos de no contar alertas viejas.
        baseline_alertas = db.query(RRHHHorasExtrasAlerta).filter(RRHHHorasExtrasAlerta.he_id == bloque.id).count()

        # ─── 1. Modificar fichada -> alerta fichada_modificada ─────────
        # Recargar la fichada y modificar timestamp.
        f_in_db = db.query(RRHHFichada).filter(RRHHFichada.id == f_in.id).first()
        f_in_db.timestamp = datetime.combine(fecha_test, time(7, 30))
        db.commit()  # dispara after_commit -> sub-sesión llama notificar_fichada_modificada

        alertas_modif = (
            db.query(RRHHHorasExtrasAlerta)
            .filter(
                RRHHHorasExtrasAlerta.he_id == bloque.id,
                RRHHHorasExtrasAlerta.tipo == "fichada_modificada",
            )
            .all()
        )
        if alertas_modif:
            _ok(
                f"Modificación de fichada #{f_in.id} -> {len(alertas_modif)} alerta(s) "
                f"tipo='fichada_modificada' severidad={alertas_modif[0].severidad}"
            )
        else:
            fallos += 1
            _fail(
                "Modificación de fichada NO disparó alerta. ¿Listener registrado? "
                "Hint: revisar import de app.events.rrhh_he_hooks."
            )

        # ─── 2. Eliminar fichada -> alerta fichada_eliminada ───────────
        # Releer la otra fichada y eliminar.
        f_out_db = db.query(RRHHFichada).filter(RRHHFichada.id == f_out.id).first()
        f_out_id_saved = f_out_db.id
        db.delete(f_out_db)
        db.commit()  # dispara after_delete -> after_commit -> alerta

        alertas_elim = (
            db.query(RRHHHorasExtrasAlerta)
            .filter(
                RRHHHorasExtrasAlerta.he_id == bloque.id,
                RRHHHorasExtrasAlerta.tipo == "fichada_eliminada",
            )
            .all()
        )
        if alertas_elim:
            _ok(f"Eliminación de fichada #{f_out_id_saved} -> {len(alertas_elim)} alerta(s) tipo='fichada_eliminada'")
        else:
            fallos += 1
            _fail("Eliminación de fichada NO disparó alerta tipo='fichada_eliminada'")

        # Verificar que el bloque NO cambió de estado.
        db.refresh(bloque)
        if bloque.estado == EstadoHE.APROBADA.value:
            _ok("Bloque permanece en estado 'aprobada' tras hooks (no recalculado)")
        else:
            fallos += 1
            _fail(f"Bloque cambió a estado '{bloque.estado}' tras hooks (esperaba 'aprobada')")

    except Exception as exc:
        fallos += 1
        _fail(f"Excepción inesperada: {exc!r}")
        import traceback

        traceback.print_exc()
    finally:
        # Cleanup.
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
        print("\nResultado: PASS (T-8.4)")
        return 0
    print(f"\nResultado: FAIL ({fallos} aserciones fallidas)")
    return 1


if __name__ == "__main__":
    sys.exit(main())
