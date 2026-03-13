"""
Servicio de reportes RRHH — Phase 8.

Consultas de agregación sobre todas las tablas del módulo RRHH.
No crea tablas propias — solo lectura y exportación.

Reportes disponibles:
- Presentismo mensual (grilla de asistencia por empleado)
- Sanciones en un período (agrupadas por tipo y empleado)
- Vacaciones resumen anual (días correspondientes / gozados / pendientes)
- Cuenta corriente resumen (todas las cuentas con saldo)
- Horas trabajadas (calculadas a partir de fichadas entrada/salida)
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import cast, func, Date
from sqlalchemy.orm import Session

from app.models.rrhh_cuenta_corriente import RRHHCuentaCorriente
from app.models.rrhh_empleado import RRHHEmpleado
from app.models.rrhh_fichada import RRHHFichada
from app.models.rrhh_presentismo import RRHHPresentismoDiario
from app.models.rrhh_sancion import RRHHSancion, RRHHTipoSancion
from app.models.rrhh_vacaciones import RRHHVacacionesPeriodo


class ReportesService:
    """Servicio de agregación para reportes RRHH."""

    def __init__(self, db: Session):
        self.db = db

    # ──────────────────────────────────────────
    # 1. Presentismo mensual
    # ──────────────────────────────────────────

    def presentismo_mensual(
        self,
        mes: int,
        anio: int,
        area: str | None = None,
    ) -> dict[str, Any]:
        """
        Reporte de presentismo mensual.

        Retorna por cada empleado activo:
        - Nombre, legajo, área, puesto
        - Cantidad de días por cada estado (presente, ausente, etc.)
        - Total de días registrados

        Opcional: filtrar por área.
        """
        # Base: empleados activos
        emp_query = self.db.query(RRHHEmpleado).filter(
            RRHHEmpleado.activo.is_(True),
            RRHHEmpleado.estado == "activo",
        )
        if area:
            emp_query = emp_query.filter(RRHHEmpleado.area == area)

        empleados = emp_query.order_by(RRHHEmpleado.apellido, RRHHEmpleado.nombre).all()

        # Rango del mes
        fecha_desde = date(anio, mes, 1)
        if mes == 12:
            fecha_hasta = date(anio + 1, 1, 1) - timedelta(days=1)
        else:
            fecha_hasta = date(anio, mes + 1, 1) - timedelta(days=1)

        # Aggregate presentismo
        conteos = (
            self.db.query(
                RRHHPresentismoDiario.empleado_id,
                RRHHPresentismoDiario.estado,
                func.count().label("cantidad"),
            )
            .filter(
                RRHHPresentismoDiario.fecha >= fecha_desde,
                RRHHPresentismoDiario.fecha <= fecha_hasta,
            )
            .group_by(
                RRHHPresentismoDiario.empleado_id,
                RRHHPresentismoDiario.estado,
            )
            .all()
        )

        # Build lookup: {empleado_id: {estado: count}}
        conteo_map: dict[int, dict[str, int]] = {}
        for row in conteos:
            if row.empleado_id not in conteo_map:
                conteo_map[row.empleado_id] = {}
            conteo_map[row.empleado_id][row.estado] = row.cantidad

        estados_posibles = [
            "presente",
            "ausente",
            "home_office",
            "vacaciones",
            "art",
            "licencia",
            "franco",
            "feriado",
        ]

        items = []
        for emp in empleados:
            emp_conteo = conteo_map.get(emp.id, {})
            registro: dict[str, Any] = {
                "empleado_id": emp.id,
                "nombre": emp.nombre_completo,
                "legajo": emp.legajo,
                "area": emp.area or "",
                "puesto": emp.puesto or "",
            }
            total = 0
            for estado in estados_posibles:
                cant = emp_conteo.get(estado, 0)
                registro[estado] = cant
                total += cant
            registro["total_registrado"] = total
            items.append(registro)

        return {
            "mes": mes,
            "anio": anio,
            "area": area,
            "fecha_desde": fecha_desde.isoformat(),
            "fecha_hasta": fecha_hasta.isoformat(),
            "total_empleados": len(items),
            "items": items,
        }

    # ──────────────────────────────────────────
    # 2. Sanciones por período
    # ──────────────────────────────────────────

    def sanciones_periodo(
        self,
        fecha_desde: date,
        fecha_hasta: date,
    ) -> dict[str, Any]:
        """
        Reporte de sanciones en un rango de fechas.

        Retorna:
        - Lista detallada de sanciones (incluyendo anuladas marcadas).
        - Resumen por tipo de sanción.
        - Resumen por empleado.
        """
        sanciones = (
            self.db.query(RRHHSancion)
            .filter(
                RRHHSancion.fecha >= fecha_desde,
                RRHHSancion.fecha <= fecha_hasta,
            )
            .order_by(RRHHSancion.fecha.desc())
            .all()
        )

        # Lookup empleados and tipos
        emp_ids = {s.empleado_id for s in sanciones}
        tipo_ids = {s.tipo_sancion_id for s in sanciones}

        empleados_map: dict[int, str] = {}
        if emp_ids:
            emps = (
                self.db.query(RRHHEmpleado.id, RRHHEmpleado.apellido, RRHHEmpleado.nombre)
                .filter(RRHHEmpleado.id.in_(emp_ids))
                .all()
            )
            empleados_map = {e.id: f"{e.apellido}, {e.nombre}" for e in emps}

        tipos_map: dict[int, str] = {}
        if tipo_ids:
            tipos = (
                self.db.query(RRHHTipoSancion.id, RRHHTipoSancion.nombre).filter(RRHHTipoSancion.id.in_(tipo_ids)).all()
            )
            tipos_map = {t.id: t.nombre for t in tipos}

        # Build items
        items = []
        por_tipo: dict[str, int] = {}
        por_empleado: dict[str, int] = {}

        for s in sanciones:
            emp_nombre = empleados_map.get(s.empleado_id, f"ID {s.empleado_id}")
            tipo_nombre = tipos_map.get(s.tipo_sancion_id, f"ID {s.tipo_sancion_id}")

            items.append(
                {
                    "id": s.id,
                    "empleado_id": s.empleado_id,
                    "empleado_nombre": emp_nombre,
                    "tipo": tipo_nombre,
                    "fecha": s.fecha.isoformat(),
                    "motivo": s.motivo,
                    "anulada": s.anulada,
                    "fecha_desde": s.fecha_desde.isoformat() if s.fecha_desde else None,
                    "fecha_hasta": s.fecha_hasta.isoformat() if s.fecha_hasta else None,
                }
            )

            if not s.anulada:
                por_tipo[tipo_nombre] = por_tipo.get(tipo_nombre, 0) + 1
                por_empleado[emp_nombre] = por_empleado.get(emp_nombre, 0) + 1

        return {
            "fecha_desde": fecha_desde.isoformat(),
            "fecha_hasta": fecha_hasta.isoformat(),
            "total": len(items),
            "total_vigentes": sum(1 for s in sanciones if not s.anulada),
            "total_anuladas": sum(1 for s in sanciones if s.anulada),
            "items": items,
            "por_tipo": [{"tipo": k, "cantidad": v} for k, v in sorted(por_tipo.items(), key=lambda x: -x[1])],
            "por_empleado": [
                {"empleado": k, "cantidad": v} for k, v in sorted(por_empleado.items(), key=lambda x: -x[1])
            ],
        }

    # ──────────────────────────────────────────
    # 3. Vacaciones resumen anual
    # ──────────────────────────────────────────

    def vacaciones_resumen(self, anio: int) -> dict[str, Any]:
        """
        Resumen de vacaciones para un año.

        Retorna períodos con empleado, días correspondientes/gozados/pendientes.
        """
        periodos = (
            self.db.query(RRHHVacacionesPeriodo)
            .filter(RRHHVacacionesPeriodo.anio == anio)
            .order_by(RRHHVacacionesPeriodo.empleado_id)
            .all()
        )

        # Lookup empleados
        emp_ids = {p.empleado_id for p in periodos}
        empleados_map: dict[int, dict[str, str]] = {}
        if emp_ids:
            emps = (
                self.db.query(
                    RRHHEmpleado.id,
                    RRHHEmpleado.apellido,
                    RRHHEmpleado.nombre,
                    RRHHEmpleado.legajo,
                    RRHHEmpleado.area,
                )
                .filter(RRHHEmpleado.id.in_(emp_ids))
                .all()
            )
            empleados_map = {
                e.id: {
                    "nombre": f"{e.apellido}, {e.nombre}",
                    "legajo": e.legajo,
                    "area": e.area or "",
                }
                for e in emps
            }

        total_correspondientes = 0
        total_gozados = 0
        total_pendientes = 0
        items = []

        for p in periodos:
            emp = empleados_map.get(p.empleado_id, {})
            items.append(
                {
                    "empleado_id": p.empleado_id,
                    "nombre": emp.get("nombre", f"ID {p.empleado_id}"),
                    "legajo": emp.get("legajo", ""),
                    "area": emp.get("area", ""),
                    "antiguedad_anios": p.antiguedad_anios,
                    "dias_correspondientes": p.dias_correspondientes,
                    "dias_gozados": p.dias_gozados,
                    "dias_pendientes": p.dias_pendientes,
                }
            )
            total_correspondientes += p.dias_correspondientes
            total_gozados += p.dias_gozados
            total_pendientes += p.dias_pendientes

        return {
            "anio": anio,
            "total_empleados": len(items),
            "total_dias_correspondientes": total_correspondientes,
            "total_dias_gozados": total_gozados,
            "total_dias_pendientes": total_pendientes,
            "items": items,
        }

    # ──────────────────────────────────────────
    # 4. Cuenta corriente resumen
    # ──────────────────────────────────────────

    def cuenta_corriente_resumen(self) -> dict[str, Any]:
        """
        Resumen de todas las cuentas corrientes con saldo.

        Retorna cuentas ordenadas por saldo descendente (mayor deuda primero).
        """
        cuentas = self.db.query(RRHHCuentaCorriente).order_by(RRHHCuentaCorriente.saldo.desc()).all()

        # Lookup empleados
        emp_ids = {c.empleado_id for c in cuentas}
        empleados_map: dict[int, dict[str, str]] = {}
        if emp_ids:
            emps = (
                self.db.query(
                    RRHHEmpleado.id,
                    RRHHEmpleado.apellido,
                    RRHHEmpleado.nombre,
                    RRHHEmpleado.legajo,
                    RRHHEmpleado.area,
                )
                .filter(RRHHEmpleado.id.in_(emp_ids))
                .all()
            )
            empleados_map = {
                e.id: {
                    "nombre": f"{e.apellido}, {e.nombre}",
                    "legajo": e.legajo,
                    "area": e.area or "",
                }
                for e in emps
            }

        total_saldo = Decimal("0")
        items = []

        for c in cuentas:
            emp = empleados_map.get(c.empleado_id, {})
            saldo = c.saldo or Decimal("0")
            items.append(
                {
                    "empleado_id": c.empleado_id,
                    "nombre": emp.get("nombre", f"ID {c.empleado_id}"),
                    "legajo": emp.get("legajo", ""),
                    "area": emp.get("area", ""),
                    "saldo": float(saldo),
                }
            )
            total_saldo += saldo

        con_deuda = sum(1 for i in items if i["saldo"] > 0)
        con_credito = sum(1 for i in items if i["saldo"] < 0)
        sin_saldo = sum(1 for i in items if i["saldo"] == 0)

        return {
            "total_cuentas": len(items),
            "total_saldo": float(total_saldo),
            "con_deuda": con_deuda,
            "con_credito": con_credito,
            "sin_saldo": sin_saldo,
            "items": items,
        }

    # ──────────────────────────────────────────
    # 5. Horas trabajadas
    # ──────────────────────────────────────────

    def horas_trabajadas(
        self,
        mes: int,
        anio: int,
        empleado_id: int | None = None,
    ) -> dict[str, Any]:
        """
        Calcula horas trabajadas a partir de fichadas (entrada/salida).

        Algoritmo:
        - Agrupa fichadas por empleado y día.
        - Ordena por timestamp dentro de cada grupo.
        - Empareja entradas con salidas secuencialmente.
        - Suma las diferencias de tiempo de cada par.

        Fichadas sin pareja (entrada sin salida o viceversa) se marcan como
        incompletas.
        """
        # Rango del mes
        fecha_desde = date(anio, mes, 1)
        if mes == 12:
            fecha_hasta = date(anio + 1, 1, 1) - timedelta(days=1)
        else:
            fecha_hasta = date(anio, mes + 1, 1) - timedelta(days=1)

        # Query fichadas with employee mapping
        query = self.db.query(RRHHFichada).filter(
            RRHHFichada.empleado_id.isnot(None),
            cast(RRHHFichada.timestamp, Date) >= fecha_desde,
            cast(RRHHFichada.timestamp, Date) <= fecha_hasta,
        )
        if empleado_id:
            query = query.filter(RRHHFichada.empleado_id == empleado_id)

        fichadas = query.order_by(RRHHFichada.empleado_id, RRHHFichada.timestamp).all()

        # Lookup empleados
        emp_ids = {f.empleado_id for f in fichadas}
        empleados_map: dict[int, dict[str, str]] = {}
        if emp_ids:
            emps = (
                self.db.query(
                    RRHHEmpleado.id,
                    RRHHEmpleado.apellido,
                    RRHHEmpleado.nombre,
                    RRHHEmpleado.legajo,
                )
                .filter(RRHHEmpleado.id.in_(emp_ids))
                .all()
            )
            empleados_map = {e.id: {"nombre": f"{e.apellido}, {e.nombre}", "legajo": e.legajo} for e in emps}

        # Group by employee + day
        from collections import defaultdict

        by_emp_day: dict[int, dict[date, list]] = defaultdict(lambda: defaultdict(list))
        for f in fichadas:
            dia = f.timestamp.date() if hasattr(f.timestamp, "date") else f.timestamp
            by_emp_day[f.empleado_id][dia].append(f)

        items = []
        for eid, days in by_emp_day.items():
            emp = empleados_map.get(eid, {})
            total_minutos = 0
            dias_completos = 0
            dias_incompletos = 0
            detalle_dias: list[dict[str, Any]] = []

            for dia, fichadas_dia in sorted(days.items()):
                # Separate entries and exits
                entradas = [f for f in fichadas_dia if f.tipo == "entrada"]
                salidas = [f for f in fichadas_dia if f.tipo == "salida"]

                # Pair them sequentially
                pares = min(len(entradas), len(salidas))
                minutos_dia = 0
                for i in range(pares):
                    delta = salidas[i].timestamp - entradas[i].timestamp
                    minutos_dia += max(delta.total_seconds() / 60, 0)

                completo = pares > 0 and len(entradas) == len(salidas)
                if completo:
                    dias_completos += 1
                else:
                    dias_incompletos += 1

                total_minutos += minutos_dia
                detalle_dias.append(
                    {
                        "fecha": dia.isoformat(),
                        "fichadas": len(fichadas_dia),
                        "horas": round(minutos_dia / 60, 2),
                        "completo": completo,
                    }
                )

            items.append(
                {
                    "empleado_id": eid,
                    "nombre": emp.get("nombre", f"ID {eid}"),
                    "legajo": emp.get("legajo", ""),
                    "total_horas": round(total_minutos / 60, 2),
                    "dias_trabajados": dias_completos + dias_incompletos,
                    "dias_completos": dias_completos,
                    "dias_incompletos": dias_incompletos,
                    "detalle": detalle_dias,
                }
            )

        # Sort by total hours descending
        items.sort(key=lambda x: -x["total_horas"])

        return {
            "mes": mes,
            "anio": anio,
            "empleado_id": empleado_id,
            "fecha_desde": fecha_desde.isoformat(),
            "fecha_hasta": fecha_hasta.isoformat(),
            "total_empleados": len(items),
            "items": items,
        }
