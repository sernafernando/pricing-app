"""
Helpers de días hábiles.

Define la semana hábil como **lunes a sábado**, saltando domingos y los
feriados/no laborables registrados en `rrhh_horarios_excepciones`
(`tipo='feriado'` y `es_laborable=False`).

Si en el futuro la operación se vuelve solo lunes-viernes, ajustar
`_es_dia_habil` para excluir el sábado (weekday == 5).
"""

from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy.orm import Session

from app.models.rrhh_horario import RRHHHorarioExcepcion


# Domingo en datetime.weekday() es 6. Sábado es 5.
_WEEKDAY_DOMINGO = 6


def _es_dia_habil(fecha: date, feriados: set[date]) -> bool:
    """True si la fecha es lun-sab y no está en el set de feriados no laborables."""
    if fecha.weekday() == _WEEKDAY_DOMINGO:
        return False
    if fecha in feriados:
        return False
    return True


def _cargar_feriados(db: Session, desde: date, hasta: date) -> set[date]:
    """Devuelve el set de fechas no laborables en el rango [desde, hasta]."""
    rows = (
        db.query(RRHHHorarioExcepcion.fecha)
        .filter(
            RRHHHorarioExcepcion.fecha >= desde,
            RRHHHorarioExcepcion.fecha <= hasta,
            RRHHHorarioExcepcion.es_laborable.is_(False),
        )
        .all()
    )
    return {r[0] for r in rows}


def next_business_day(desde: date, db: Session, *, max_dias: int = 14) -> date:
    """
    Retorna el próximo día hábil estrictamente posterior a ``desde``.

    Itera día por día hasta encontrar uno que cumpla `_es_dia_habil`.
    Carga los feriados en una sola query sobre la ventana de búsqueda.

    Args:
        desde: fecha base; el resultado siempre será > desde.
        db: sesión SQLAlchemy para consultar feriados.
        max_dias: tope de seguridad para evitar loops infinitos si la tabla
            de feriados tiene data corrupta. 14 cubre cualquier puente real.

    Raises:
        RuntimeError: si no se encuentra día hábil dentro de ``max_dias``.
    """
    desde_busqueda = desde + timedelta(days=1)
    hasta_busqueda = desde + timedelta(days=max_dias)
    feriados = _cargar_feriados(db, desde_busqueda, hasta_busqueda)

    candidato = desde_busqueda
    for _ in range(max_dias):
        if _es_dia_habil(candidato, feriados):
            return candidato
        candidato += timedelta(days=1)

    raise RuntimeError(
        f"No se encontró día hábil en los siguientes {max_dias} días desde {desde}. Revisar rrhh_horarios_excepciones."
    )
