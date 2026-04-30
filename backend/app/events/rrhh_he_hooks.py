"""
SQLAlchemy event listeners que mantienen consistencia entre fichadas /
asignaciones de turno y los bloques de Horas Extras (`rrhh_horas_extras`).

Decisión técnica (design §9):
- `after_update`/`after_delete`/`after_insert` sobre `RRHHFichada`
  encolan el `(fichada_id, evento)` en `session.info`.
- `after_insert`/`after_update`/`after_delete` sobre `RRHHEmpleadoHorario`
  encolan `(empleado_id, fecha_desde_minima)` en `session.info`.
- Un único listener `after_commit` a nivel `Session` consume ambas colas en
  una **sub-sesión** (`SessionLocal()`), invoca el service y commitea.
- NUNCA propaga excepciones al commit principal — sólo loggea.

Por qué `after_commit` + sub-sesión: si el hook corriera dentro del flush
y fallara, abortaría la edición original de la fichada / asignación, lo
cual es inaceptable. La alerta / recálculo puede llegar 1-2 segundos
después de la edición.

Importar este módulo (desde `app/main.py`) dispara los `@event.listens_for`.
"""

from __future__ import annotations

import logging
from datetime import date, timedelta

from sqlalchemy import event
from sqlalchemy.orm import Session

from app.models.rrhh_empleado_horario import RRHHEmpleadoHorario
from app.models.rrhh_fichada import RRHHFichada

logger = logging.getLogger(__name__)


# Claves usadas en `session.info` para encolar trabajo pendiente.
_FICHADAS_KEY = "_rrhh_he_pending"
_HORARIOS_KEY = "_rrhh_he_horarios_pending"

# Riesgo §12 — fichadas insertadas tarde (más de 1 día atrás respecto a hoy)
# pueden afectar bloques aprobados/liquidados existentes. Las inserciones
# del día de hoy son flujo normal y NO disparan alerta.
_FICHADA_TARDIA_THRESHOLD_DAYS = 1


# ───────────────────────── Helpers ─────────────────────────


def _enqueue_fichada(session: Session, fichada_id: int, evento: str) -> None:
    """Encola un evento de fichada al final de la transacción."""
    if fichada_id is None:
        return
    pending = session.info.setdefault(_FICHADAS_KEY, [])
    pending.append((fichada_id, evento))


def _enqueue_horario(session: Session, empleado_id: int | None, fecha_desde_minima: date) -> None:
    """Encola un evento de cambio de asignación de turno."""
    if empleado_id is None:
        return
    pending = session.info.setdefault(_HORARIOS_KEY, [])
    pending.append((empleado_id, fecha_desde_minima))


# ──────────────── Listeners — RRHHFichada (T-3.1) ────────────────


@event.listens_for(RRHHFichada, "after_update")
def _on_fichada_after_update(mapper, connection, target):
    """UPDATE sobre fichada → posible alerta sobre bloque congelado."""
    session = Session.object_session(target)
    if session is None:
        return
    _enqueue_fichada(session, target.id, "modificada")


@event.listens_for(RRHHFichada, "after_delete")
def _on_fichada_after_delete(mapper, connection, target):
    """DELETE sobre fichada → posible alerta sobre bloque congelado."""
    session = Session.object_session(target)
    if session is None:
        return
    _enqueue_fichada(session, target.id, "eliminada")


@event.listens_for(RRHHFichada, "after_insert")
def _on_fichada_after_insert(mapper, connection, target):
    """
    INSERT tardío de fichada → alerta si la fichada cae en un día anterior
    a `today - 1 día` (riesgo §12 "Fichadas tardías post-aprobación").
    Inserts del día de hoy son flujo normal y NO se alertan.
    """
    session = Session.object_session(target)
    if session is None:
        return
    ts = getattr(target, "timestamp", None)
    if ts is None:
        return
    fecha_fichada = ts.date() if hasattr(ts, "date") else ts
    if (date.today() - fecha_fichada).days <= _FICHADA_TARDIA_THRESHOLD_DAYS:
        return
    _enqueue_fichada(session, target.id, "insertada_tardia")


# ─────────────── Listeners — RRHHEmpleadoHorario (T-3.2) ───────────────


def _fecha_desde_minima_for_target(target: RRHHEmpleadoHorario) -> date:
    """
    `RRHHEmpleadoHorario` no tiene columnas `fecha_desde`/`fecha_hasta` — los
    rangos se infieren del `RRHHHorarioConfig` y de las fichadas existentes.

    El service (`recalcular_por_cambio_turno`) ya aplica el cap configurado
    (`cap_dias_recalculo_manual`, default 90 días) sobre `fecha_desde_minima`.
    Pasamos `today - 90` como ventana segura; el service clamps si hace falta.
    """
    return date.today() - timedelta(days=90)


@event.listens_for(RRHHEmpleadoHorario, "after_insert")
def _on_empleado_horario_after_insert(mapper, connection, target):
    session = Session.object_session(target)
    if session is None:
        return
    _enqueue_horario(session, target.empleado_id, _fecha_desde_minima_for_target(target))


@event.listens_for(RRHHEmpleadoHorario, "after_update")
def _on_empleado_horario_after_update(mapper, connection, target):
    session = Session.object_session(target)
    if session is None:
        return
    _enqueue_horario(session, target.empleado_id, _fecha_desde_minima_for_target(target))


@event.listens_for(RRHHEmpleadoHorario, "after_delete")
def _on_empleado_horario_after_delete(mapper, connection, target):
    session = Session.object_session(target)
    if session is None:
        return
    _enqueue_horario(session, target.empleado_id, _fecha_desde_minima_for_target(target))


# ─────────────── Listener `after_commit` — sub-sesión ───────────────


@event.listens_for(Session, "after_commit")
def _flush_he_pending(session: Session) -> None:
    """
    Al final del commit principal:
      1. Drena la cola de fichadas → `service.notificar_fichada_modificada`.
      2. Drena la cola de cambios de turno → `service.recalcular_por_cambio_turno`.
    Todo en una sub-sesión nueva (`SessionLocal()`) para no mezclar con la
    sesión principal ya commiteada. Errores se loggean — JAMÁS se propagan.
    """
    fichadas_pending = session.info.pop(_FICHADAS_KEY, None) or []
    horarios_pending = session.info.pop(_HORARIOS_KEY, None) or []

    if not fichadas_pending and not horarios_pending:
        return

    # Import local para evitar ciclos en el arranque del módulo.
    from app.core.database import SessionLocal
    from app.services.rrhh_horas_extras_service import HorasExtrasService

    sub = SessionLocal()
    try:
        service = HorasExtrasService(sub)

        # 1) Fichadas modificadas / eliminadas / insertadas tarde.
        for fichada_id, evento in fichadas_pending:
            try:
                service.notificar_fichada_modificada(fichada_id, evento=evento)
            except Exception:
                logger.exception(
                    "❌ Error en hook fichada (id=%s, evento=%s)",
                    fichada_id,
                    evento,
                )

        # 2) Cambios de asignación de turno.
        for empleado_id, fecha_desde_minima in horarios_pending:
            try:
                service.recalcular_por_cambio_turno(empleado_id, fecha_desde_minima)
            except Exception:
                logger.exception(
                    "❌ Error en hook cambio turno (empleado_id=%s, fecha_desde=%s)",
                    empleado_id,
                    fecha_desde_minima,
                )

        sub.commit()
    except Exception:
        sub.rollback()
        logger.exception("❌ Error general en _flush_he_pending — sub-sesión rollbackeada")
    finally:
        sub.close()
