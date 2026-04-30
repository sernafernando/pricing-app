"""
T-8.3 — Test manual: transiciones de estado del bloque HE (state machine).

Crea un bloque `detectada` y verifica las transiciones del workflow:
- aprobar(detectada) -> aprobada, registra historial.
- aprobar(aprobada) -> 422 (ya aprobado).
- reabrir(aprobada) -> detectada, setea reabierto_por/at, historial.
- rechazar(motivo='') -> 422 (motivo obligatorio).
- rechazar(detectada, motivo válido) -> rechazada, historial.
- liquidar(detectada) -> queda en detalle_rechazos (no se liquida).
- liquidar(aprobada) -> liquidada, registra liquidacion_periodo.
- reabrir(liquidada) -> aprobada (flujo permitido en service; el control de
  permiso queda al router).

Toda la data creada se borra al final (empleado, horario, fichadas, bloque,
historial, alertas).

Uso:
    cd /var/www/html/pricing-app/backend
    python -m app.scripts.test_manual_rrhh_he_state_machine

Spec ref: "Workflow de estados con permisos diferenciados", "Reapertura manual",
"Liquidación mensual de bloques aprobados".
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

from fastapi import HTTPException

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


SUFFIX = f"T83_{int(time_mod.time())}"
USUARIO_TEST_ID = 1  # Asume que existe usuario id=1 (admin); si no, el FK falla.


def _ok(msg: str) -> None:
    print(f"  PASS - {msg}")


def _fail(msg: str) -> None:
    print(f"  FAIL - {msg}")


def main() -> int:
    print(f"Iniciando test_manual_rrhh_he_state_machine (T-8.3) — suffix {SUFFIX}")
    db = SessionLocal()
    fallos = 0
    empleado: RRHHEmpleado | None = None
    horario: RRHHHorarioConfig | None = None
    fecha_test = date.today() - timedelta(days=14)
    if fecha_test.weekday() >= 5:
        # Empujamos a un día hábil.
        fecha_test = fecha_test - timedelta(days=fecha_test.weekday() - 4)

    try:
        service = HorasExtrasService(db)

        # Setup empleado + turno + fichadas que generen 60 min HE.
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

        # Fichadas 08:00 -> 14:00 (6h trabajadas, 1h HE = 60 min).
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

        # Detectar -> bloque detectada.
        service.detectar_he_periodo(fecha_test, fecha_test, empleado_ids=[empleado.id])
        bloque = (
            db.query(RRHHHorasExtras)
            .filter(
                RRHHHorasExtras.empleado_id == empleado.id,
                RRHHHorasExtras.fecha == fecha_test,
            )
            .first()
        )
        if bloque is None or bloque.estado != EstadoHE.DETECTADA.value:
            fallos += 1
            _fail(f"Setup: bloque inicial no quedó en 'detectada' (got {bloque.estado if bloque else 'None'})")
            return 1

        he_id = bloque.id
        _ok(f"Setup OK: bloque #{he_id} en estado detectada (extras={bloque.extras_minutos})")

        # ─── 1. aprobar(detectada) -> aprobada ─────────────────────────
        b = service.aprobar_bloque(he_id, USUARIO_TEST_ID)
        if b.estado == EstadoHE.APROBADA.value and b.aprobado_por_id == USUARIO_TEST_ID:
            _ok("aprobar(detectada) -> aprobada con aprobado_por_id seteado")
        else:
            fallos += 1
            _fail(f"aprobar(detectada): estado={b.estado}, aprobado_por={b.aprobado_por_id}")

        n_hist = (
            db.query(RRHHHorasExtrasHistorial)
            .filter(
                RRHHHorasExtrasHistorial.he_id == he_id,
                RRHHHorasExtrasHistorial.accion == "aprobada",
            )
            .count()
        )
        if n_hist >= 1:
            _ok(f"Historial: {n_hist} fila(s) accion='aprobada' insertada(s)")
        else:
            fallos += 1
            _fail(f"Historial: esperaba >=1 fila accion='aprobada'; got {n_hist}")

        # ─── 2. aprobar(aprobada) -> 422 ──────────────────────────────
        try:
            service.aprobar_bloque(he_id, USUARIO_TEST_ID)
            fallos += 1
            _fail("aprobar(aprobada) NO lanzó 422")
        except HTTPException as exc:
            if exc.status_code == 422:
                _ok(f"aprobar(aprobada) -> 422 ({exc.detail[:60]})")
            else:
                fallos += 1
                _fail(f"aprobar(aprobada) lanzó {exc.status_code} en vez de 422")

        # ─── 3. reabrir(aprobada) sin motivo -> 422 ────────────────────
        try:
            service.reabrir_bloque(he_id, USUARIO_TEST_ID, motivo="")
            fallos += 1
            _fail("reabrir(motivo='') NO lanzó 422")
        except HTTPException as exc:
            if exc.status_code == 422:
                _ok("reabrir(motivo='') -> 422")
            else:
                fallos += 1
                _fail(f"reabrir(motivo='') lanzó {exc.status_code} en vez de 422")

        # ─── 4. reabrir(aprobada, motivo válido) -> detectada ──────────
        b = service.reabrir_bloque(he_id, USUARIO_TEST_ID, motivo="prueba reapertura T-8.3")
        if (
            b.estado == EstadoHE.DETECTADA.value
            and b.reabierto_por_id == USUARIO_TEST_ID
            and b.reabierto_at is not None
            and (b.motivo_reapertura or "").startswith("prueba reapertura")
        ):
            _ok("reabrir(aprobada) -> detectada con reabierto_*; motivo registrado")
        else:
            fallos += 1
            _fail(
                f"reabrir(aprobada): estado={b.estado}, reabierto_por={b.reabierto_por_id}, "
                f"motivo={b.motivo_reapertura!r}"
            )

        # ─── 5. rechazar(motivo='') -> 422 ─────────────────────────────
        try:
            service.rechazar_bloque(he_id, USUARIO_TEST_ID, motivo="")
            fallos += 1
            _fail("rechazar(motivo='') NO lanzó 422")
        except HTTPException as exc:
            if exc.status_code == 422:
                _ok("rechazar(motivo='') -> 422")
            else:
                fallos += 1
                _fail(f"rechazar(motivo='') lanzó {exc.status_code} en vez de 422")

        # ─── 6. rechazar con motivo válido -> rechazada ────────────────
        # Re-aprobamos primero para devolverlo a un estado limpio, después rechazamos.
        b = service.aprobar_bloque(he_id, USUARIO_TEST_ID)
        b = service.rechazar_bloque(he_id, USUARIO_TEST_ID, motivo="prueba rechazo T-8.3")
        if b.estado == EstadoHE.RECHAZADA.value and (b.motivo_rechazo or "").startswith("prueba rechazo"):
            _ok("rechazar(aprobada) -> rechazada con motivo persistido")
        else:
            fallos += 1
            _fail(f"rechazar: estado={b.estado}, motivo={b.motivo_rechazo!r}")

        # ─── 7. liquidar bloque NO aprobado -> rechazado en bulk ───────
        # Reabrimos el rechazado para volver a detectada y luego intentamos liquidar.
        service.reabrir_bloque(he_id, USUARIO_TEST_ID, motivo="restore para liquidar")
        # ahora bloque está detectada
        res = service.liquidar_periodo(periodo="202604", ids=[he_id], usuario_id=USUARIO_TEST_ID)
        if res["liquidados"] == 0 and res["rechazados"] == 1:
            _ok(f"liquidar(detectada) -> rechazado individual ({res['detalle_rechazos'][0]['motivo'][:60]})")
        else:
            fallos += 1
            _fail(f"liquidar(detectada): res={res}")

        # ─── 8. liquidar bloque aprobado -> liquidada ──────────────────
        service.aprobar_bloque(he_id, USUARIO_TEST_ID)
        res = service.liquidar_periodo(periodo="202604", ids=[he_id], usuario_id=USUARIO_TEST_ID)
        bloque_liq = db.query(RRHHHorasExtras).filter(RRHHHorasExtras.id == he_id).first()
        if (
            res["liquidados"] == 1
            and bloque_liq is not None
            and bloque_liq.estado == EstadoHE.LIQUIDADA.value
            and bloque_liq.liquidacion_periodo == "202604"
            and bloque_liq.liquidado_por_id == USUARIO_TEST_ID
        ):
            _ok("liquidar(aprobada) -> liquidada con periodo=202604, liquidado_por")
        else:
            fallos += 1
            _fail(f"liquidar(aprobada): res={res}, estado_actual={bloque_liq.estado if bloque_liq else None}")

        # ─── 9. reabrir(liquidada) -> aprobada (service permite) ───────
        b = service.reabrir_bloque(he_id, USUARIO_TEST_ID, motivo="reapertura post-liquidacion T-8.3")
        if b.estado == EstadoHE.APROBADA.value and b.liquidacion_periodo is None and b.liquidado_por_id is None:
            _ok("reabrir(liquidada) -> aprobada con liquidacion_* limpiados")
        else:
            fallos += 1
            _fail(
                f"reabrir(liquidada): estado={b.estado}, periodo={b.liquidacion_periodo}, liq_por={b.liquidado_por_id}"
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
        print("\nResultado: PASS (T-8.3)")
        return 0
    print(f"\nResultado: FAIL ({fallos} aserciones fallidas)")
    return 1


if __name__ == "__main__":
    sys.exit(main())
