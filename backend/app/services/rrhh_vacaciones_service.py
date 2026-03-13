"""
Servicio de cálculo y gestión de vacaciones — Ley 20.744 Art. 150.

Tiers de antigüedad (medidos al 31/dic del año del período):
  < 5 años   → 14 días corridos
  5-10 años  → 21 días corridos
  10-20 años → 28 días corridos
  > 20 años  → 35 días corridos
"""

from datetime import date

from sqlalchemy import and_
from sqlalchemy.orm import Session

from app.models.rrhh_empleado import RRHHEmpleado
from app.models.rrhh_vacaciones import (
    RRHHVacacionesPeriodo,
    RRHHVacacionesSolicitud,
)


class VacacionesService:
    def __init__(self, db: Session):
        self.db = db

    # ──────────────────────────────────────────
    # Cálculo de días por ley
    # ──────────────────────────────────────────

    @staticmethod
    def calcular_dias_correspondientes(fecha_ingreso: date, anio: int) -> tuple[int, int]:
        """
        Calcula días de vacaciones y antigüedad para un año dado.

        La antigüedad se mide al 31/dic del año del período.

        Returns:
            (dias_correspondientes, antiguedad_anios)
        """
        corte = date(anio, 12, 31)
        antiguedad = corte.year - fecha_ingreso.year
        if (corte.month, corte.day) < (fecha_ingreso.month, fecha_ingreso.day):
            antiguedad -= 1
        antiguedad = max(antiguedad, 0)

        if antiguedad > 20:
            dias = 35
        elif antiguedad > 10:
            dias = 28
        elif antiguedad >= 5:
            dias = 21
        else:
            dias = 14

        return dias, antiguedad

    # ──────────────────────────────────────────
    # Generación de períodos anuales
    # ──────────────────────────────────────────

    def generar_periodos_anuales(self, anio: int) -> dict[str, int]:
        """
        Genera períodos de vacaciones para TODOS los empleados activos.

        Salta empleados que ya tienen período para ese año.
        No incluye empleados en estado 'baja'.

        Returns:
            { "generados": int, "existentes": int }
        """
        empleados = (
            self.db.query(RRHHEmpleado)
            .filter(
                RRHHEmpleado.activo.is_(True),
                RRHHEmpleado.estado == "activo",
            )
            .all()
        )

        generados = 0
        existentes = 0

        for emp in empleados:
            existing = (
                self.db.query(RRHHVacacionesPeriodo)
                .filter(
                    RRHHVacacionesPeriodo.empleado_id == emp.id,
                    RRHHVacacionesPeriodo.anio == anio,
                )
                .first()
            )
            if existing:
                existentes += 1
                continue

            dias, antiguedad = self.calcular_dias_correspondientes(emp.fecha_ingreso, anio)
            periodo = RRHHVacacionesPeriodo(
                empleado_id=emp.id,
                anio=anio,
                dias_correspondientes=dias,
                dias_gozados=0,
                dias_pendientes=dias,
                antiguedad_anios=antiguedad,
            )
            self.db.add(periodo)
            generados += 1

        if generados > 0:
            self.db.commit()

        return {"generados": generados, "existentes": existentes}

    # ──────────────────────────────────────────
    # Validación de solicitud
    # ──────────────────────────────────────────

    def validar_solicitud(
        self,
        empleado_id: int,
        periodo_id: int,
        fecha_desde: date,
        fecha_hasta: date,
    ) -> tuple[bool, str | None, int]:
        """
        Valida una nueva solicitud de vacaciones.

        Checks:
        1. El período existe y pertenece al empleado.
        2. fecha_hasta >= fecha_desde.
        3. Hay días pendientes suficientes.
        4. No hay superposición con solicitudes activas (pendiente/aprobada/gozada).

        Returns:
            (es_valida, mensaje_error, dias_solicitados)
        """
        # 1. Período existe y es del empleado
        periodo = (
            self.db.query(RRHHVacacionesPeriodo)
            .filter(
                RRHHVacacionesPeriodo.id == periodo_id,
                RRHHVacacionesPeriodo.empleado_id == empleado_id,
            )
            .first()
        )
        if not periodo:
            return False, "Período no encontrado para este empleado", 0

        # 2. Rango de fechas válido
        if fecha_hasta < fecha_desde:
            return False, "La fecha hasta debe ser mayor o igual a fecha desde", 0

        dias = (fecha_hasta - fecha_desde).days + 1  # días corridos inclusive

        # 3. Días pendientes suficientes
        if dias > periodo.dias_pendientes:
            return (
                False,
                f"Días solicitados ({dias}) superan los pendientes ({periodo.dias_pendientes})",
                dias,
            )

        # 4. No overlap con solicitudes activas
        estados_activos = ["pendiente", "aprobada", "gozada"]
        overlap = (
            self.db.query(RRHHVacacionesSolicitud)
            .filter(
                RRHHVacacionesSolicitud.empleado_id == empleado_id,
                RRHHVacacionesSolicitud.estado.in_(estados_activos),
                # Overlap: existing.desde <= new.hasta AND existing.hasta >= new.desde
                and_(
                    RRHHVacacionesSolicitud.fecha_desde <= fecha_hasta,
                    RRHHVacacionesSolicitud.fecha_hasta >= fecha_desde,
                ),
            )
            .first()
        )
        if overlap:
            return (
                False,
                f"Se superpone con solicitud #{overlap.id} ({overlap.fecha_desde} - {overlap.fecha_hasta})",
                dias,
            )

        return True, None, dias
