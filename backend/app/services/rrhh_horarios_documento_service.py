"""
Servicio del documento de horarios por empleado — RRHH.

Genera la grilla "un renglón por día trabajado" que se entrega al empleado
junto con el recibo de sueldo. El PDF se arma en el frontend con @pdfme
(contexto de documento `horarios_empleado`); acá sólo se produce el dato.

Reglas de negocio (decididas por RRHH, NO reinterpretar acá):

1. `entrada` = PRIMERA fichada del día, `salida` = ÚLTIMA fichada del día.
   Las fichadas intermedias se ignoran y NO se descuenta almuerzo. La columna
   `tipo` de `rrhh_fichadas` NO es confiable (el sync Hikvision alterna
   entrada/salida por orden de timestamp, así que con 3 fichadas la última
   puede quedar mal etiquetada), por eso nunca se filtra ni se agrupa por
   `tipo`. Es deliberadamente la MISMA regla que
   `HorasExtrasService._minutos_trabajados`, para que el documento coincida
   con lo que liquida nómina.

2. Sólo días hábiles: un día entra si está en los `dias_semana` de algún turno
   asignado al empleado Y no es feriado/día no laborable, MÁS cualquier día que
   tenga fichadas aunque no esté agendado (un sábado trabajado nunca se oculta).
   Fines de semana y feriados sin fichadas se omiten por completo.

3. Los días incluidos sin fichadas muestran su `estado`
   (ausente / vacaciones / art / licencia ...) en lugar de horarios.

4. El backend SIEMPRE devuelve horas (decimal y HH:MM). Que la columna de horas
   se imprima o no es decisión del frontend.

Zona horaria: `rrhh_fichadas.timestamp` es `timestamptz`. Todo el formateo y —
crítico — el agrupamiento "por día" se hace en hora Argentina (`ART_TZ`,
UTC-3); agrupar en UTC mandaría los turnos nocturnos al día equivocado.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, time, timedelta, timezone
from typing import Any

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models.rrhh_empleado import RRHHEmpleado
from app.models.rrhh_empleado_horario import RRHHEmpleadoHorario
from app.models.rrhh_fichada import RRHHFichada
from app.models.rrhh_horario import RRHHHorarioConfig, RRHHHorarioExcepcion
from app.models.rrhh_presentismo import EstadoPresentismo, RRHHPresentismoDiario
from app.services.rrhh_hikvision_client import ART_TZ

# Mismo tope que los reportes hermanos (`/rrhh/reportes/presentismo-diario`).
MAX_RANGO_DIAS = 62

# Fallback cuando el empleado no tiene ningún turno asignado: Lunes a Viernes.
# `isoweekday()`: 1=Lunes ... 7=Domingo (igual que `RRHHHorarioConfig.dias_semana`).
DIAS_LABORALES_FALLBACK: frozenset[int] = frozenset({1, 2, 3, 4, 5})

# Abreviaturas fijas (no dependemos del locale del server, que puede ser C/POSIX).
DIAS_SEMANA_ABREV: tuple[str, ...] = ("Lun", "Mar", "Mié", "Jue", "Vie", "Sáb", "Dom")


def _a_utc(ts: datetime) -> datetime:
    """
    Normaliza un timestamp de fichada a UTC *aware*.

    En PostgreSQL la columna es `timestamptz`, así que siempre vuelve aware.
    Filas legacy (y el SQLite de los tests, que descarta el offset) pueden
    volver naive: en ese caso se asumen UTC, que es como las escribe el sync.
    """
    if ts.tzinfo is None:
        return ts.replace(tzinfo=timezone.utc)
    return ts.astimezone(timezone.utc)


def _a_art(ts: datetime) -> datetime:
    """Convierte un timestamp de fichada a hora Argentina (UTC-3)."""
    return _a_utc(ts).astimezone(ART_TZ)


def _hhmm(minutos: int) -> str:
    """Formatea minutos como `HH:MM` (las horas no se truncan: 10590 → '176:30')."""
    minutos = max(minutos, 0)
    return f"{minutos // 60:02d}:{minutos % 60:02d}"


def _decimal(minutos: int) -> float:
    """Formatea minutos como horas decimales con 2 decimales (546 → 9.1)."""
    return round(max(minutos, 0) / 60, 2)


class HorariosDocumentoService:
    """Arma el documento imprimible de horarios diarios por empleado."""

    def __init__(self, db: Session) -> None:
        self.db = db

    # ──────────────────────────────────────────
    # API pública
    # ──────────────────────────────────────────

    def horarios_documento(
        self,
        fecha_desde: date,
        fecha_hasta: date,
        empleado_ids: list[int] | None = None,
    ) -> dict[str, Any]:
        """
        Devuelve, por empleado, un renglón por día hábil del rango con
        entrada / salida / horas / estado.

        Args:
            fecha_desde: primer día del rango (inclusive).
            fecha_hasta: último día del rango (inclusive).
            empleado_ids: si viene, limita a esos empleados y se emite el
                documento aunque estén dados de baja (hace falta para la
                liquidación final). Si no viene, se listan sólo los empleados
                vigentes (`activo=True` y `estado != 'baja'`), igual que el
                resto del módulo RRHH.

        Raises:
            HTTPException 400: si el rango está invertido o supera
                `MAX_RANGO_DIAS` días.
        """
        self._validar_rango(fecha_desde, fecha_hasta)

        empleados = self._empleados(empleado_ids)
        if not empleados:
            return {
                "fecha_desde": fecha_desde.isoformat(),
                "fecha_hasta": fecha_hasta.isoformat(),
                "empleados": [],
            }

        emp_ids = [e.id for e in empleados]

        # Todas las lecturas son bulk: 4 queries fijas, sin importar cuántos
        # empleados ni cuántos días tenga el rango (nada de N+1).
        fichadas_por_dia = self._fichadas_por_empleado_dia(emp_ids, fecha_desde, fecha_hasta)
        estados = self._estados_presentismo(emp_ids, fecha_desde, fecha_hasta)
        no_laborables = self._dias_no_laborables(fecha_desde, fecha_hasta)
        dias_laborales = self._dias_laborales_por_empleado(emp_ids)

        fechas = self._rango_fechas(fecha_desde, fecha_hasta)

        return {
            "fecha_desde": fecha_desde.isoformat(),
            "fecha_hasta": fecha_hasta.isoformat(),
            "empleados": [
                self._armar_empleado(
                    empleado=emp,
                    fechas=fechas,
                    fichadas_por_dia=fichadas_por_dia,
                    estados=estados,
                    no_laborables=no_laborables,
                    dias_laborales=dias_laborales.get(emp.id) or DIAS_LABORALES_FALLBACK,
                )
                for emp in empleados
            ],
        }

    # ──────────────────────────────────────────
    # Validación
    # ──────────────────────────────────────────

    @staticmethod
    def _validar_rango(fecha_desde: date, fecha_hasta: date) -> None:
        """Mismo contrato de error que `/rrhh/reportes/presentismo-diario`."""
        if fecha_hasta < fecha_desde:
            raise HTTPException(status_code=400, detail="fecha_hasta debe ser >= fecha_desde")
        if (fecha_hasta - fecha_desde).days > MAX_RANGO_DIAS:
            raise HTTPException(status_code=400, detail=f"Rango máximo: {MAX_RANGO_DIAS} días")

    @staticmethod
    def _rango_fechas(fecha_desde: date, fecha_hasta: date) -> list[date]:
        dias: list[date] = []
        actual = fecha_desde
        while actual <= fecha_hasta:
            dias.append(actual)
            actual += timedelta(days=1)
        return dias

    # ──────────────────────────────────────────
    # Lecturas bulk
    # ──────────────────────────────────────────

    def _empleados(self, empleado_ids: list[int] | None) -> list[RRHHEmpleado]:
        """
        Empleados a incluir, ordenados como en el resto del módulo.

        El filtro de vigencia (`activo=True` y `estado != 'baja'`) se aplica
        SÓLO en modo lote, para que la emisión masiva no arrastre bajas viejas.

        Cuando el caller nombra empleados explícitamente por `empleado_ids` el
        filtro se omite a propósito: el registro de horarios del último mes es
        parte del respaldo documental de la liquidación final, así que tiene
        que poder emitirse justamente para alguien que ya no está vigente.
        """
        query = self.db.query(RRHHEmpleado)
        if empleado_ids:
            query = query.filter(RRHHEmpleado.id.in_(empleado_ids))
        else:
            query = query.filter(
                RRHHEmpleado.activo.is_(True),
                RRHHEmpleado.estado != "baja",
            )
        return query.order_by(RRHHEmpleado.apellido, RRHHEmpleado.nombre).all()

    def _fichadas_por_empleado_dia(
        self,
        emp_ids: list[int],
        fecha_desde: date,
        fecha_hasta: date,
    ) -> dict[tuple[int, date], list[datetime]]:
        """
        UNA query con TODAS las fichadas del rango para TODOS los empleados,
        agrupadas en memoria por (empleado, día ART) y ordenadas ascendente.

        La ventana SQL se abre ±1 día porque el día ART va de las 03:00 UTC a
        las 03:00 UTC del día siguiente; el recorte fino se hace en Python
        después de convertir a ART, así el resultado no depende de cómo la
        sesión de PostgreSQL interprete un `datetime` naive.

        No se filtra por `tipo`: es un campo no confiable (ver docstring del
        módulo).
        """
        fichadas = (
            self.db.query(RRHHFichada.empleado_id, RRHHFichada.timestamp)
            .filter(
                RRHHFichada.empleado_id.in_(emp_ids),
                RRHHFichada.timestamp >= datetime.combine(fecha_desde - timedelta(days=1), time.min),
                RRHHFichada.timestamp <= datetime.combine(fecha_hasta + timedelta(days=1), time.max),
            )
            .order_by(RRHHFichada.empleado_id, RRHHFichada.timestamp)
            .all()
        )

        agrupadas: dict[tuple[int, date], list[datetime]] = defaultdict(list)
        for empleado_id, ts in fichadas:
            if ts is None:
                continue
            local = _a_art(ts)
            dia = local.date()
            if fecha_desde <= dia <= fecha_hasta:
                agrupadas[(empleado_id, dia)].append(local)

        for marcas in agrupadas.values():
            marcas.sort()
        return agrupadas

    def _estados_presentismo(
        self,
        emp_ids: list[int],
        fecha_desde: date,
        fecha_hasta: date,
    ) -> dict[tuple[int, date], str]:
        """UNA query con los estados manuales de presentismo del rango."""
        filas = (
            self.db.query(
                RRHHPresentismoDiario.empleado_id,
                RRHHPresentismoDiario.fecha,
                RRHHPresentismoDiario.estado,
            )
            .filter(
                RRHHPresentismoDiario.empleado_id.in_(emp_ids),
                RRHHPresentismoDiario.fecha >= fecha_desde,
                RRHHPresentismoDiario.fecha <= fecha_hasta,
            )
            .all()
        )
        return {(empleado_id, fecha): estado for empleado_id, fecha, estado in filas}

    def _dias_no_laborables(self, fecha_desde: date, fecha_hasta: date) -> set[date]:
        """
        UNA query con los feriados / días especiales no laborables del rango.

        Se usa `es_laborable is False` (y no `tipo == 'feriado'`) porque esa
        columna es justamente la que declara si se trabaja o no; un
        `dia_especial` no laborable también corresponde omitirlo.
        """
        filas = (
            self.db.query(RRHHHorarioExcepcion.fecha)
            .filter(
                RRHHHorarioExcepcion.fecha >= fecha_desde,
                RRHHHorarioExcepcion.fecha <= fecha_hasta,
                RRHHHorarioExcepcion.es_laborable.is_(False),
            )
            .all()
        )
        return {fila.fecha for fila in filas}

    def _dias_laborales_por_empleado(self, emp_ids: list[int]) -> dict[int, set[int]]:
        """
        UNA query (join) con los días de la semana cubiertos por los turnos
        activos de cada empleado.

        Devuelve `{empleado_id: {1..7}}` en formato `isoweekday` (1=Lunes).
        Los empleados sin turnos asignados NO aparecen en el dict: el caller
        aplica `DIAS_LABORALES_FALLBACK` (Lunes a Viernes).
        """
        filas = (
            self.db.query(RRHHEmpleadoHorario.empleado_id, RRHHHorarioConfig.dias_semana)
            .join(
                RRHHHorarioConfig,
                RRHHHorarioConfig.id == RRHHEmpleadoHorario.horario_config_id,
            )
            .filter(
                RRHHEmpleadoHorario.empleado_id.in_(emp_ids),
                RRHHHorarioConfig.activo.is_(True),
            )
            .all()
        )

        por_empleado: dict[int, set[int]] = defaultdict(set)
        for empleado_id, dias_semana in filas:
            for token in (dias_semana or "").split(","):
                token = token.strip()
                if token.isdigit():
                    por_empleado[empleado_id].add(int(token))
        # Un turno activo con `dias_semana` vacío no debe degradar al fallback
        # de forma silenciosa: si el set quedó vacío, se descarta la entrada.
        return {eid: dias for eid, dias in por_empleado.items() if dias}

    # ──────────────────────────────────────────
    # Armado
    # ──────────────────────────────────────────

    def _armar_empleado(
        self,
        empleado: RRHHEmpleado,
        fechas: list[date],
        fichadas_por_dia: dict[tuple[int, date], list[datetime]],
        estados: dict[tuple[int, date], str],
        no_laborables: set[date],
        dias_laborales: frozenset[int] | set[int],
    ) -> dict[str, Any]:
        dias: list[dict[str, Any]] = []
        total_minutos = 0
        dias_trabajados = 0

        for fecha in fechas:
            marcas = fichadas_por_dia.get((empleado.id, fecha), [])
            agendado = fecha.isoweekday() in dias_laborales and fecha not in no_laborables

            # Regla 2: entra si estaba agendado, o si igual hubo fichadas.
            if not marcas and not agendado:
                continue

            minutos, entrada, salida, incompleto = self._resolver_jornada(marcas)
            total_minutos += minutos
            if marcas:
                dias_trabajados += 1

            dias.append(
                {
                    "fecha": fecha.isoformat(),
                    "fecha_label": fecha.strftime("%d/%m"),
                    "dia_semana": DIAS_SEMANA_ABREV[fecha.weekday()],
                    "entrada": entrada,
                    "salida": salida,
                    "horas_decimal": _decimal(minutos),
                    "horas_hhmm": _hhmm(minutos),
                    "estado": self._resolver_estado(
                        estados.get((empleado.id, fecha)),
                        tiene_fichadas=bool(marcas),
                    ),
                    "sin_fichadas": not marcas,
                    "incompleto": incompleto,
                }
            )

        return {
            "empleado_id": empleado.id,
            "legajo": empleado.legajo or "",
            "nombre_completo": empleado.nombre_completo,
            "dni": empleado.dni or "",
            "cuil": empleado.cuil or "",
            "puesto": empleado.puesto or "",
            "area": empleado.area or "",
            "dias": dias,
            "total_horas_decimal": _decimal(total_minutos),
            "total_horas_hhmm": _hhmm(total_minutos),
            "total_dias": len(dias),
            "dias_trabajados": dias_trabajados,
        }

    @staticmethod
    def _resolver_jornada(marcas: list[datetime]) -> tuple[int, str, str, bool]:
        """
        Aplica la regla 1: primera fichada = entrada, última = salida.

        Returns:
            `(minutos, entrada, salida, incompleto)`. Con una sola fichada del
            día no hay jornada calculable: se informa la entrada, la salida
            queda vacía, las horas en 0 y `incompleto=True` para que el
            documento sea honesto (mismo criterio que `dias_incompletos` en
            `ReportesService.horas_trabajadas`).
        """
        if not marcas:
            return 0, "", "", False
        if len(marcas) == 1:
            return 0, marcas[0].strftime("%H:%M"), "", True
        minutos = int((marcas[-1] - marcas[0]).total_seconds() // 60)
        return max(minutos, 0), marcas[0].strftime("%H:%M"), marcas[-1].strftime("%H:%M"), False

    @staticmethod
    def _resolver_estado(estado_manual: str | None, tiene_fichadas: bool) -> str:
        """
        Estado a mostrar: gana siempre la marcación manual de presentismo.

        Sin fila de presentismo, el estado se infiere: hubo fichadas →
        `presente`; día hábil sin fichadas → `ausente`.
        """
        if estado_manual:
            return estado_manual
        if tiene_fichadas:
            return EstadoPresentismo.PRESENTE.value
        return EstadoPresentismo.AUSENTE.value
