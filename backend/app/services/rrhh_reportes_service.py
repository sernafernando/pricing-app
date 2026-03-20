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

from datetime import date, timedelta, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import cast, func, Date
from sqlalchemy.orm import Session

from app.models.rrhh_cuenta_corriente import RRHHCuentaCorriente
from app.models.rrhh_empleado import RRHHEmpleado
from app.models.rrhh_empleado_horario import RRHHEmpleadoHorario
from app.models.rrhh_fichada import RRHHFichada
from app.models.rrhh_horario import RRHHHorarioConfig, RRHHHorarioExcepcion
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

    # ──────────────────────────────────────────
    # 6. Presentismo diario (grilla apaisada)
    # ──────────────────────────────────────────

    def presentismo_diario(
        self,
        fecha_desde: date,
        fecha_hasta: date,
        empleado_id: int | None = None,
        area: str | None = None,
    ) -> dict[str, Any]:
        """
        Reporte apaisado de presentismo diario.

        Una fila por empleado, una columna por fecha.
        Incluye estado + fichada (hora ingreso/egreso) por día.

        Prioridad de estado (misma lógica que la grilla):
        1. Manual: registro en rrhh_presentismo_diario → origen="manual"
        2. Feriado: excepción no laborable → "feriado", origen="auto"
        3. Franco: día de semana fuera de turnos → "franco", origen="auto"
        4. Presente: fichada de entrada ese día → "presente", origen="auto"
        5. Nulo: sin dato
        """
        from collections import defaultdict
        from datetime import datetime, time

        # ── 1. Empleados activos ──
        emp_query = self.db.query(RRHHEmpleado).filter(
            RRHHEmpleado.activo.is_(True),
            RRHHEmpleado.estado == "activo",
        )
        if area:
            emp_query = emp_query.filter(RRHHEmpleado.area == area)
        if empleado_id:
            emp_query = emp_query.filter(RRHHEmpleado.id == empleado_id)

        empleados = emp_query.order_by(RRHHEmpleado.apellido, RRHHEmpleado.nombre).all()

        if not empleados:
            fechas_list: list[str] = []
            current = fecha_desde
            while current <= fecha_hasta:
                fechas_list.append(current.isoformat())
                current += timedelta(days=1)
            return {
                "fecha_desde": fecha_desde.isoformat(),
                "fecha_hasta": fecha_hasta.isoformat(),
                "fechas": fechas_list,
                "total_empleados": 0,
                "items": [],
            }

        emp_ids = [e.id for e in empleados]

        # ── 2. Marcaciones manuales del rango ──
        marcaciones = (
            self.db.query(RRHHPresentismoDiario)
            .filter(
                RRHHPresentismoDiario.empleado_id.in_(emp_ids),
                RRHHPresentismoDiario.fecha >= fecha_desde,
                RRHHPresentismoDiario.fecha <= fecha_hasta,
            )
            .all()
        )
        marc_map: dict[tuple[int, str], str] = {}
        for m in marcaciones:
            marc_map[(m.empleado_id, m.fecha.isoformat())] = m.estado

        # ── 3. Excepciones (feriados) del rango ──
        excepciones = (
            self.db.query(RRHHHorarioExcepcion)
            .filter(
                RRHHHorarioExcepcion.fecha >= fecha_desde,
                RRHHHorarioExcepcion.fecha <= fecha_hasta,
            )
            .all()
        )
        feriados_set: set[str] = set()
        for exc in excepciones:
            if exc.tipo == "feriado" and not exc.es_laborable:
                feriados_set.add(exc.fecha.isoformat())

        # ── 4. Turnos asignados por empleado (para detectar francos) ──
        asignaciones = self.db.query(RRHHEmpleadoHorario).filter(RRHHEmpleadoHorario.empleado_id.in_(emp_ids)).all()
        horario_ids = list({a.horario_config_id for a in asignaciones})
        horarios_map: dict[int, RRHHHorarioConfig] = {}
        if horario_ids:
            horarios = (
                self.db.query(RRHHHorarioConfig)
                .filter(
                    RRHHHorarioConfig.id.in_(horario_ids),
                    RRHHHorarioConfig.activo.is_(True),
                )
                .all()
            )
            horarios_map = {h.id: h for h in horarios}

        emp_dias_laborales: dict[int, set[int]] = {}
        for eid in emp_ids:
            dias_set: set[int] = set()
            emp_asigs = [a for a in asignaciones if a.empleado_id == eid]
            for asig in emp_asigs:
                horario = horarios_map.get(asig.horario_config_id)
                if horario and horario.dias_semana:
                    for d in horario.dias_semana.split(","):
                        d_stripped = d.strip()
                        if d_stripped.isdigit():
                            dias_set.add(int(d_stripped))
            emp_dias_laborales[eid] = dias_set

        # ── 5. Fichadas del rango (entrada y salida) ──
        fichadas_raw = (
            self.db.query(RRHHFichada)
            .filter(
                RRHHFichada.empleado_id.in_(emp_ids),
                RRHHFichada.timestamp >= datetime.combine(fecha_desde, time.min),
                RRHHFichada.timestamp <= datetime.combine(fecha_hasta, time.max),
                RRHHFichada.tipo.in_(["entrada", "salida"]),
            )
            .order_by(RRHHFichada.timestamp)
            .all()
        )

        # Group fichadas by (empleado_id, fecha_iso)
        fichadas_by_emp_day: dict[tuple[int, str], list] = defaultdict(list)
        for f in fichadas_raw:
            dia = f.timestamp.date() if hasattr(f.timestamp, "date") else f.timestamp
            fichadas_by_emp_day[(f.empleado_id, dia.isoformat())].append(f)

        # Set of (emp_id, fecha_iso) with at least one entrada
        fichadas_entrada_set: set[tuple[int, str]] = set()
        for f in fichadas_raw:
            if f.tipo == "entrada":
                dia = f.timestamp.date() if hasattr(f.timestamp, "date") else f.timestamp
                fichadas_entrada_set.add((f.empleado_id, dia.isoformat()))

        # ── 6. Generar lista de fechas ──
        fechas: list[str] = []
        fecha_weekday: dict[str, int] = {}
        current_date = fecha_desde
        while current_date <= fecha_hasta:
            iso = current_date.isoformat()
            fechas.append(iso)
            fecha_weekday[iso] = current_date.isoweekday()
            current_date += timedelta(days=1)

        # ── 7. Armar grilla con auto-cálculo + fichadas ──
        items: list[dict[str, Any]] = []
        for emp in empleados:
            dias: dict[str, dict[str, Any]] = {}
            dias_lab = emp_dias_laborales.get(emp.id, set())
            tiene_turnos = len(dias_lab) > 0

            for f_iso in fechas:
                estado: str | None = None
                origen: str | None = None

                # Prioridad 1: Manual
                manual_estado = marc_map.get((emp.id, f_iso))
                if manual_estado is not None:
                    estado = manual_estado
                    origen = "manual"
                # Prioridad 2: Feriado no laborable
                elif f_iso in feriados_set:
                    estado = "feriado"
                    origen = "auto"
                # Prioridad 3: Franco
                elif tiene_turnos and fecha_weekday[f_iso] not in dias_lab:
                    estado = "franco"
                    origen = "auto"
                # Prioridad 4: Fichada de entrada → presente
                elif (emp.id, f_iso) in fichadas_entrada_set:
                    estado = "presente"
                    origen = "auto"

                # Format fichada string: "HH:MM - HH:MM" (first entry - last exit, in ART timezone)
                ART_TZ = timezone(timedelta(hours=-3))
                fichada_str = ""
                day_fichadas = fichadas_by_emp_day.get((emp.id, f_iso), [])
                if day_fichadas:
                    entradas = [fich for fich in day_fichadas if fich.tipo == "entrada"]
                    salidas = [fich for fich in day_fichadas if fich.tipo == "salida"]
                    first_entry = entradas[0].timestamp.astimezone(ART_TZ).strftime("%H:%M") if entradas else ""
                    last_exit = salidas[-1].timestamp.astimezone(ART_TZ).strftime("%H:%M") if salidas else ""
                    if first_entry and last_exit:
                        fichada_str = f"{first_entry} - {last_exit}"
                    elif first_entry:
                        fichada_str = first_entry
                    elif last_exit:
                        fichada_str = f"- {last_exit}"

                if estado is not None:
                    dias[f_iso] = {
                        "estado": estado,
                        "origen": origen,
                        "fichada": fichada_str,
                    }
                else:
                    # Sin dato pero con fichada posible (edge case)
                    if fichada_str:
                        dias[f_iso] = {
                            "estado": "",
                            "origen": None,
                            "fichada": fichada_str,
                        }

            items.append(
                {
                    "empleado_id": emp.id,
                    "nombre": emp.nombre_completo,
                    "legajo": emp.legajo,
                    "area": emp.area or "",
                    "dias": dias,
                }
            )

        return {
            "fecha_desde": fecha_desde.isoformat(),
            "fecha_hasta": fecha_hasta.isoformat(),
            "fechas": fechas,
            "total_empleados": len(items),
            "items": items,
        }
