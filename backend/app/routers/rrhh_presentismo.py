"""
Router del módulo RRHH - Presentismo diario + Casos ART.

Endpoints:
- Grilla de presentismo: listado de todos los empleados para un rango de fechas
- Marcación individual y masiva (bulk)
- CRUD de casos ART (accidentes de trabajo)
- Upload/download de documentación médica ART
"""

import os
import uuid
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session, selectinload

from app.core.config import settings
from app.core.database import get_db
from app.core.deps import get_current_user
from app.models.rrhh_art_caso import EstadoArt, RRHHArtCaso
from app.models.rrhh_art_documento import RRHHArtDocumento
from app.models.rrhh_empleado import RRHHEmpleado
from app.models.rrhh_empleado_horario import RRHHEmpleadoHorario
from app.models.rrhh_fichada import RRHHFichada
from app.models.rrhh_horario import RRHHHorarioConfig, RRHHHorarioExcepcion
from app.models.rrhh_presentismo import EstadoPresentismo, RRHHPresentismoDiario
from app.models.usuario import Usuario
from app.services.permisos_service import PermisosService

router = APIRouter(prefix="/rrhh", tags=["rrhh-presentismo"])


# ──────────────────────────────────────────────
# HELPERS
# ──────────────────────────────────────────────


def _require_rrhh_permiso(
    permiso: str,
    current_user: Usuario = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Usuario:
    """Dependency: verifica que el usuario tenga un permiso RRHH específico."""
    svc = PermisosService(db)
    if not svc.tiene_permiso(current_user, permiso):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Sin permiso: {permiso}",
        )
    return current_user


# ──────────────────────────────────────────────
# SCHEMAS — Presentismo
# ──────────────────────────────────────────────


class PresentismoMarcacion(BaseModel):
    """Body para marcar un día de presentismo."""

    estado: str = Field(max_length=30)
    hora_ingreso: Optional[time] = None
    hora_egreso: Optional[time] = None
    observaciones: Optional[str] = None
    art_caso_id: Optional[int] = None


class PresentismoBulkItem(BaseModel):
    empleado_id: int
    estado: str = Field(max_length=30)
    hora_ingreso: Optional[time] = None
    hora_egreso: Optional[time] = None
    observaciones: Optional[str] = None


class PresentismoBulkRequest(BaseModel):
    fecha: date
    marcaciones: list[PresentismoBulkItem]


class PresentismoResponse(BaseModel):
    id: int
    empleado_id: int
    fecha: date
    estado: str
    hora_ingreso: Optional[time] = None
    hora_egreso: Optional[time] = None
    observaciones: Optional[str] = None
    art_caso_id: Optional[int] = None
    registrado_por_id: Optional[int] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class DiaPresentismo(BaseModel):
    """Dato de presentismo de un día: estado + origen (manual o auto) + fichada."""

    estado: Optional[str] = None
    origen: Optional[str] = None  # "manual" | "auto" | None
    fichada: Optional[str] = None  # "HH:MM - HH:MM" (primera entrada - última salida)
    minutos_tarde: Optional[int] = None
    puntualidad: Optional[str] = None  # "a_tiempo" | "tolerancia" | "tarde" | None


class EmpleadoPresentismoRow(BaseModel):
    """Una fila de empleado en la grilla de presentismo."""

    empleado_id: int
    legajo: str
    nombre_completo: str
    area: Optional[str] = None
    dias: dict[str, Optional[DiaPresentismo]]  # { "2026-03-01": {...}, ... }


class PresentismoGrillaResponse(BaseModel):
    """Respuesta de la grilla de presentismo."""

    fechas: list[str]
    empleados: list[EmpleadoPresentismoRow]
    total_empleados: int


# ──────────────────────────────────────────────
# SCHEMAS — ART
# ──────────────────────────────────────────────


class ArtCasoCreate(BaseModel):
    empleado_id: int
    numero_siniestro: Optional[str] = Field(default=None, max_length=50)
    fecha_accidente: date
    descripcion_accidente: Optional[str] = None
    lugar_accidente: Optional[str] = Field(default=None, max_length=255)
    tipo_lesion: Optional[str] = Field(default=None, max_length=100)
    parte_cuerpo: Optional[str] = Field(default=None, max_length=100)
    art_nombre: Optional[str] = Field(default=None, max_length=200)
    numero_expediente_art: Optional[str] = Field(default=None, max_length=50)
    estado: str = Field(default="abierto", max_length=30)
    observaciones: Optional[str] = None


class ArtCasoUpdate(BaseModel):
    numero_siniestro: Optional[str] = Field(default=None, max_length=50)
    descripcion_accidente: Optional[str] = None
    lugar_accidente: Optional[str] = Field(default=None, max_length=255)
    tipo_lesion: Optional[str] = Field(default=None, max_length=100)
    parte_cuerpo: Optional[str] = Field(default=None, max_length=100)
    art_nombre: Optional[str] = Field(default=None, max_length=200)
    numero_expediente_art: Optional[str] = Field(default=None, max_length=50)
    estado: Optional[str] = Field(default=None, max_length=30)
    fecha_alta_medica: Optional[date] = None
    dias_baja: Optional[int] = None
    porcentaje_incapacidad: Optional[Decimal] = None
    monto_indemnizacion: Optional[Decimal] = None
    observaciones: Optional[str] = None


class ArtDocumentoResponse(BaseModel):
    id: int
    art_caso_id: int
    nombre_archivo: str
    mime_type: Optional[str] = None
    tamano_bytes: Optional[int] = None
    descripcion: Optional[str] = None
    subido_por_id: int
    created_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class ArtCasoResponse(BaseModel):
    id: int
    empleado_id: int
    numero_siniestro: Optional[str] = None
    fecha_accidente: date
    descripcion_accidente: Optional[str] = None
    lugar_accidente: Optional[str] = None
    tipo_lesion: Optional[str] = None
    parte_cuerpo: Optional[str] = None
    art_nombre: Optional[str] = None
    numero_expediente_art: Optional[str] = None
    estado: str
    fecha_alta_medica: Optional[date] = None
    dias_baja: Optional[int] = None
    porcentaje_incapacidad: Optional[Decimal] = None
    monto_indemnizacion: Optional[Decimal] = None
    observaciones: Optional[str] = None
    creado_por_id: Optional[int] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    documentos: list[ArtDocumentoResponse] = []

    model_config = ConfigDict(from_attributes=True)


class ArtCasoListResponse(BaseModel):
    items: list[ArtCasoResponse]
    total: int
    page: int
    page_size: int


# ──────────────────────────────────────────────
# ENDPOINTS — Presentismo
# ──────────────────────────────────────────────


@router.get("/presentismo", response_model=PresentismoGrillaResponse)
def get_presentismo_grilla(
    fecha_desde: date = Query(..., description="Fecha inicio del rango"),
    fecha_hasta: date = Query(..., description="Fecha fin del rango"),
    area: Optional[str] = Query(default=None, description="Filtrar por área"),
    current_user: Usuario = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> PresentismoGrillaResponse:
    """
    Grilla de presentismo con auto-cálculo.

    Prioridad de cálculo por celda (empleado × fecha):
    1. Manual: si existe registro en rrhh_presentismo_diario → origen="manual"
    2. Feriado: si la fecha es excepción no laborable → "feriado", origen="auto"
    3. Franco: si el día de semana NO está en los turnos del empleado → "franco", origen="auto"
    4. Presente: si existe al menos una fichada de entrada ese día → "presente", origen="auto"
    5. Nulo: sin dato → None

    Los auto-calculados son "pisables": cualquier marca manual los sobreescribe.
    """
    svc = PermisosService(db)
    if not svc.tiene_permiso(current_user, "rrhh.ver"):
        raise HTTPException(status_code=403, detail="Sin permiso: rrhh.ver")

    if fecha_desde > fecha_hasta:
        raise HTTPException(
            status_code=400,
            detail="fecha_desde no puede ser posterior a fecha_hasta",
        )

    delta = (fecha_hasta - fecha_desde).days
    if delta > 62:
        raise HTTPException(
            status_code=400,
            detail="El rango máximo es de 62 días",
        )

    # ── 1. Empleados activos ──
    emp_query = db.query(RRHHEmpleado).filter(
        RRHHEmpleado.activo.is_(True),
        RRHHEmpleado.estado != "baja",
    )
    if area:
        emp_query = emp_query.filter(RRHHEmpleado.area == area)
    emp_query = emp_query.order_by(RRHHEmpleado.apellido, RRHHEmpleado.nombre)
    empleados = emp_query.all()

    if not empleados:
        return PresentismoGrillaResponse(fechas=[], empleados=[], total_empleados=0)

    emp_ids = [e.id for e in empleados]

    # ── 2. Marcaciones manuales del rango ──
    marcaciones = (
        db.query(RRHHPresentismoDiario)
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
        db.query(RRHHHorarioExcepcion)
        .filter(
            RRHHHorarioExcepcion.fecha >= fecha_desde,
            RRHHHorarioExcepcion.fecha <= fecha_hasta,
        )
        .all()
    )
    # Feriados no laborables → set de fechas ISO
    feriados_set: set[str] = set()
    for exc in excepciones:
        if exc.tipo == "feriado" and not exc.es_laborable:
            feriados_set.add(exc.fecha.isoformat())

    # ── 4. Turnos asignados por empleado ──
    asignaciones = db.query(RRHHEmpleadoHorario).filter(RRHHEmpleadoHorario.empleado_id.in_(emp_ids)).all()
    horario_ids = list({a.horario_config_id for a in asignaciones})
    horarios_map: dict[int, RRHHHorarioConfig] = {}
    if horario_ids:
        horarios = (
            db.query(RRHHHorarioConfig)
            .filter(
                RRHHHorarioConfig.id.in_(horario_ids),
                RRHHHorarioConfig.activo.is_(True),
            )
            .all()
        )
        horarios_map = {h.id: h for h in horarios}

    # Para cada empleado: set de días laborales (1=Lun ... 7=Dom, isoweekday)
    emp_dias_laborales: dict[int, set[int]] = {}
    for emp_id in emp_ids:
        dias_set: set[int] = set()
        emp_asigs = [a for a in asignaciones if a.empleado_id == emp_id]
        for asig in emp_asigs:
            horario = horarios_map.get(asig.horario_config_id)
            if horario and horario.dias_semana:
                for d in horario.dias_semana.split(","):
                    d_stripped = d.strip()
                    if d_stripped.isdigit():
                        dias_set.add(int(d_stripped))
        emp_dias_laborales[emp_id] = dias_set

    # Build per-employee horario info for tardiness (highest priority = lowest prioridad)
    emp_horario_info: dict[int, tuple[time, int]] = {}  # emp_id → (hora_entrada, tolerancia)
    sorted_asigs = sorted(asignaciones, key=lambda a: a.prioridad)
    for asig in sorted_asigs:
        if asig.empleado_id in emp_horario_info:
            continue
        h = horarios_map.get(asig.horario_config_id)
        if h:
            emp_horario_info[asig.empleado_id] = (h.hora_entrada, h.tolerancia_minutos)

    # ── 5. Fichadas del rango (entrada + salida para detectar "presente" y mostrar horarios) ──
    from sqlalchemy import func as sa_func

    # Primera entrada por (empleado, fecha)
    fichadas_entradas = (
        db.query(
            RRHHFichada.empleado_id,
            sa_func.date(RRHHFichada.timestamp).label("fecha"),
            sa_func.min(RRHHFichada.timestamp).label("primera_entrada"),
        )
        .filter(
            RRHHFichada.empleado_id.in_(emp_ids),
            RRHHFichada.timestamp >= datetime.combine(fecha_desde, time.min),
            RRHHFichada.timestamp <= datetime.combine(fecha_hasta, time.max),
            RRHHFichada.tipo == "entrada",
        )
        .group_by(RRHHFichada.empleado_id, sa_func.date(RRHHFichada.timestamp))
        .all()
    )

    # Última salida por (empleado, fecha)
    fichadas_salidas = (
        db.query(
            RRHHFichada.empleado_id,
            sa_func.date(RRHHFichada.timestamp).label("fecha"),
            sa_func.max(RRHHFichada.timestamp).label("ultima_salida"),
        )
        .filter(
            RRHHFichada.empleado_id.in_(emp_ids),
            RRHHFichada.timestamp >= datetime.combine(fecha_desde, time.min),
            RRHHFichada.timestamp <= datetime.combine(fecha_hasta, time.max),
            RRHHFichada.tipo == "salida",
        )
        .group_by(RRHHFichada.empleado_id, sa_func.date(RRHHFichada.timestamp))
        .all()
    )

    # Mapas: (empleado_id, fecha_iso) → timestamp
    def _to_key(row_emp_id, row_fecha):
        return (row_emp_id, row_fecha if isinstance(row_fecha, str) else row_fecha.isoformat())

    fichadas_entrada_map: dict[tuple[int, str], datetime] = {}
    fichadas_set: set[tuple[int, str]] = set()
    for row in fichadas_entradas:
        key = _to_key(row.empleado_id, row.fecha)
        fichadas_set.add(key)
        fichadas_entrada_map[key] = row.primera_entrada

    fichadas_salida_map: dict[tuple[int, str], datetime] = {}
    for row in fichadas_salidas:
        key = _to_key(row.empleado_id, row.fecha)
        fichadas_salida_map[key] = row.ultima_salida

    # ── 6. Generar lista de fechas ──
    fechas: list[str] = []
    current = fecha_desde
    while current <= fecha_hasta:
        fechas.append(current.isoformat())
        current += timedelta(days=1)

    # ── 7. Armar grilla con auto-cálculo ──
    # Mapa fecha_iso → isoweekday para evitar parsear repetidamente
    fecha_weekday: dict[str, int] = {}
    current = fecha_desde
    while current <= fecha_hasta:
        fecha_weekday[current.isoformat()] = current.isoweekday()
        current += timedelta(days=1)

    # Helper: formatear fichada como "HH:MM - HH:MM" (en hora Argentina)
    ART_TZ = timezone(timedelta(hours=-3))

    def _format_fichada(emp_id: int, fecha_iso: str) -> Optional[str]:
        key = (emp_id, fecha_iso)
        entrada = fichadas_entrada_map.get(key)
        salida = fichadas_salida_map.get(key)
        if not entrada and not salida:
            return None
        parts = []
        if entrada:
            parts.append(entrada.astimezone(ART_TZ).strftime("%H:%M"))
        else:
            parts.append("--:--")
        if salida:
            parts.append(salida.astimezone(ART_TZ).strftime("%H:%M"))
        else:
            parts.append("--:--")
        return " - ".join(parts)

    def _calc_tardanza(emp_id: int, fecha_iso: str) -> tuple[Optional[int], Optional[str]]:
        """Compute tardiness for the first entry on a work day."""
        info = emp_horario_info.get(emp_id)
        if not info:
            return None, None
        primera = fichadas_entrada_map.get((emp_id, fecha_iso))
        if not primera:
            return None, None
        hora_entrada, tolerancia = info
        entrada_local = primera.astimezone(ART_TZ)
        hora_real = entrada_local.time()
        scheduled = datetime.combine(entrada_local.date(), hora_entrada)
        actual = datetime.combine(entrada_local.date(), hora_real)
        diff = int((actual - scheduled).total_seconds() / 60)
        if diff <= 0:
            return 0, "a_tiempo"
        if diff <= tolerancia:
            return diff, "tolerancia"
        return diff, "tarde"

    rows: list[EmpleadoPresentismoRow] = []
    for emp in empleados:
        dias: dict[str, Optional[DiaPresentismo]] = {}
        dias_lab = emp_dias_laborales.get(emp.id, set())
        tiene_turnos = len(dias_lab) > 0

        for f in fechas:
            fichada_str = _format_fichada(emp.id, f)

            # Prioridad 1: Manual
            manual_estado = marc_map.get((emp.id, f))
            if manual_estado is not None:
                mt, pt = (None, None)
                if manual_estado == "presente":
                    mt, pt = _calc_tardanza(emp.id, f)
                dias[f] = DiaPresentismo(
                    estado=manual_estado,
                    origen="manual",
                    fichada=fichada_str,
                    minutos_tarde=mt,
                    puntualidad=pt,
                )
                continue

            # Prioridad 2: Feriado no laborable
            if f in feriados_set:
                dias[f] = DiaPresentismo(estado="feriado", origen="auto", fichada=fichada_str)
                continue

            # Prioridad 3: Franco (si tiene turnos y el día no es laboral)
            if tiene_turnos:
                weekday = fecha_weekday[f]
                if weekday not in dias_lab:
                    dias[f] = DiaPresentismo(estado="franco", origen="auto", fichada=fichada_str)
                    continue

            # Prioridad 4: Fichada de entrada → presente
            if (emp.id, f) in fichadas_set:
                mt, pt = _calc_tardanza(emp.id, f)
                dias[f] = DiaPresentismo(
                    estado="presente",
                    origen="auto",
                    fichada=fichada_str,
                    minutos_tarde=mt,
                    puntualidad=pt,
                )
                continue

            # Sin dato
            dias[f] = None

        rows.append(
            EmpleadoPresentismoRow(
                empleado_id=emp.id,
                legajo=emp.legajo,
                nombre_completo=emp.nombre_completo,
                area=emp.area,
                dias=dias,
            )
        )

    return PresentismoGrillaResponse(
        fechas=fechas,
        empleados=rows,
        total_empleados=len(rows),
    )


class PresentismoRangoRequest(BaseModel):
    """Marcar un rango de fechas para un empleado (vacaciones, suspensión, ART, licencia)."""

    empleado_id: int
    estado: str = Field(max_length=30)
    fecha_desde: date
    fecha_hasta: date
    observaciones: Optional[str] = None
    art_caso_id: Optional[int] = None


@router.put("/presentismo/rango", response_model=dict)
def mark_presentismo_rango(
    body: PresentismoRangoRequest,
    current_user: Usuario = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """
    Marcar un rango de fechas para un empleado.

    Útil para cargar vacaciones, suspensiones, ART o licencia
    de fecha X a fecha Y sin hacerlo día por día manualmente.
    """
    svc = PermisosService(db)
    if not svc.tiene_permiso(current_user, "rrhh.gestionar"):
        raise HTTPException(status_code=403, detail="Sin permiso: rrhh.gestionar")

    # Validaciones
    empleado = db.query(RRHHEmpleado).filter(RRHHEmpleado.id == body.empleado_id).first()
    if not empleado:
        raise HTTPException(status_code=404, detail="Empleado no encontrado")

    estados_validos = [e.value for e in EstadoPresentismo]
    if body.estado not in estados_validos:
        raise HTTPException(
            status_code=400,
            detail=f"Estado inválido. Opciones: {', '.join(estados_validos)}",
        )

    if body.fecha_desde > body.fecha_hasta:
        raise HTTPException(status_code=400, detail="fecha_desde no puede ser posterior a fecha_hasta")

    delta = (body.fecha_hasta - body.fecha_desde).days
    if delta > 365:
        raise HTTPException(status_code=400, detail="Rango máximo: 365 días")

    # Validate ART case if estado is 'art'
    if body.estado == EstadoPresentismo.ART.value and body.art_caso_id:
        art_caso = db.query(RRHHArtCaso).filter(RRHHArtCaso.id == body.art_caso_id).first()
        if not art_caso:
            raise HTTPException(status_code=404, detail="Caso ART no encontrado")
        if art_caso.empleado_id != body.empleado_id:
            raise HTTPException(status_code=400, detail="El caso ART no pertenece a este empleado")

    # Create/update records for each day in the range
    current = body.fecha_desde
    updated = 0
    while current <= body.fecha_hasta:
        registro = (
            db.query(RRHHPresentismoDiario)
            .filter(
                RRHHPresentismoDiario.empleado_id == body.empleado_id,
                RRHHPresentismoDiario.fecha == current,
            )
            .first()
        )

        if registro:
            registro.estado = body.estado
            registro.observaciones = body.observaciones
            registro.art_caso_id = body.art_caso_id if body.estado == EstadoPresentismo.ART.value else None
            registro.registrado_por_id = current_user.id
        else:
            registro = RRHHPresentismoDiario(
                empleado_id=body.empleado_id,
                fecha=current,
                estado=body.estado,
                observaciones=body.observaciones,
                art_caso_id=body.art_caso_id if body.estado == EstadoPresentismo.ART.value else None,
                registrado_por_id=current_user.id,
            )
            db.add(registro)

        updated += 1
        current += timedelta(days=1)

    db.commit()
    return {
        "updated": updated,
        "empleado_id": body.empleado_id,
        "estado": body.estado,
        "fecha_desde": body.fecha_desde.isoformat(),
        "fecha_hasta": body.fecha_hasta.isoformat(),
    }


@router.put(
    "/presentismo/{empleado_id}/{fecha}",
    response_model=PresentismoResponse,
)
def mark_presentismo(
    empleado_id: int,
    fecha: date,
    body: PresentismoMarcacion,
    current_user: Usuario = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> PresentismoResponse:
    """
    Marcar o actualizar el estado de presentismo de un empleado en una fecha.

    Si ya existe una marcación para esa fecha, la actualiza (upsert).
    """
    svc = PermisosService(db)
    if not svc.tiene_permiso(current_user, "rrhh.gestionar"):
        raise HTTPException(status_code=403, detail="Sin permiso: rrhh.gestionar")

    # Validar empleado
    empleado = db.query(RRHHEmpleado).filter(RRHHEmpleado.id == empleado_id).first()
    if not empleado:
        raise HTTPException(status_code=404, detail="Empleado no encontrado")

    # Validar estado
    estados_validos = [e.value for e in EstadoPresentismo]
    if body.estado not in estados_validos:
        raise HTTPException(
            status_code=400,
            detail=f"Estado inválido. Opciones: {', '.join(estados_validos)}",
        )

    # Validar art_caso_id si estado es 'art'
    if body.estado == EstadoPresentismo.ART.value and body.art_caso_id:
        art_caso = db.query(RRHHArtCaso).filter(RRHHArtCaso.id == body.art_caso_id).first()
        if not art_caso:
            raise HTTPException(status_code=404, detail="Caso ART no encontrado")
        if art_caso.empleado_id != empleado_id:
            raise HTTPException(
                status_code=400,
                detail="El caso ART no pertenece a este empleado",
            )

    # Upsert: buscar existente o crear
    registro = (
        db.query(RRHHPresentismoDiario)
        .filter(
            RRHHPresentismoDiario.empleado_id == empleado_id,
            RRHHPresentismoDiario.fecha == fecha,
        )
        .first()
    )

    if registro:
        registro.estado = body.estado
        registro.hora_ingreso = body.hora_ingreso
        registro.hora_egreso = body.hora_egreso
        registro.observaciones = body.observaciones
        registro.art_caso_id = body.art_caso_id if body.estado == EstadoPresentismo.ART.value else None
        registro.registrado_por_id = current_user.id
    else:
        registro = RRHHPresentismoDiario(
            empleado_id=empleado_id,
            fecha=fecha,
            estado=body.estado,
            hora_ingreso=body.hora_ingreso,
            hora_egreso=body.hora_egreso,
            observaciones=body.observaciones,
            art_caso_id=body.art_caso_id if body.estado == EstadoPresentismo.ART.value else None,
            registrado_por_id=current_user.id,
        )
        db.add(registro)

    db.commit()
    db.refresh(registro)
    return PresentismoResponse.model_validate(registro)


@router.put("/presentismo/bulk", response_model=dict)
def bulk_mark_presentismo(
    body: PresentismoBulkRequest,
    current_user: Usuario = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """
    Marcación masiva: marcar múltiples empleados para una misma fecha.

    Útil para el día a día: el responsable marca presente/ausente
    a todo el plantel de una vez.
    """
    svc = PermisosService(db)
    if not svc.tiene_permiso(current_user, "rrhh.gestionar"):
        raise HTTPException(status_code=403, detail="Sin permiso: rrhh.gestionar")

    estados_validos = [e.value for e in EstadoPresentismo]
    updated = 0

    for item in body.marcaciones:
        if item.estado not in estados_validos:
            continue  # skip invalid states silently in bulk

        # Verificar que el empleado existe
        empleado = db.query(RRHHEmpleado).filter(RRHHEmpleado.id == item.empleado_id).first()
        if not empleado:
            continue

        # Upsert
        registro = (
            db.query(RRHHPresentismoDiario)
            .filter(
                RRHHPresentismoDiario.empleado_id == item.empleado_id,
                RRHHPresentismoDiario.fecha == body.fecha,
            )
            .first()
        )

        if registro:
            registro.estado = item.estado
            registro.hora_ingreso = item.hora_ingreso
            registro.hora_egreso = item.hora_egreso
            registro.observaciones = item.observaciones
            registro.registrado_por_id = current_user.id
        else:
            registro = RRHHPresentismoDiario(
                empleado_id=item.empleado_id,
                fecha=body.fecha,
                estado=item.estado,
                hora_ingreso=item.hora_ingreso,
                hora_egreso=item.hora_egreso,
                observaciones=item.observaciones,
                registrado_por_id=current_user.id,
            )
            db.add(registro)

        updated += 1

    db.commit()
    return {"updated": updated, "fecha": body.fecha.isoformat()}


# ──────────────────────────────────────────────
# ENDPOINTS — ART Casos
# ──────────────────────────────────────────────


@router.get("/art", response_model=ArtCasoListResponse)
def list_art_casos(
    empleado_id: Optional[int] = Query(default=None),
    estado: Optional[str] = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    current_user: Usuario = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ArtCasoListResponse:
    """Listar casos ART con filtros opcionales."""
    svc = PermisosService(db)
    if not svc.tiene_permiso(current_user, "rrhh.ver"):
        raise HTTPException(status_code=403, detail="Sin permiso: rrhh.ver")

    query = db.query(RRHHArtCaso).options(selectinload(RRHHArtCaso.documentos))

    if empleado_id:
        query = query.filter(RRHHArtCaso.empleado_id == empleado_id)
    if estado:
        query = query.filter(RRHHArtCaso.estado == estado)

    total = query.count()
    items = query.order_by(RRHHArtCaso.created_at.desc()).offset((page - 1) * page_size).limit(page_size).all()

    return ArtCasoListResponse(
        items=[ArtCasoResponse.model_validate(c) for c in items],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.post("/art", response_model=ArtCasoResponse, status_code=status.HTTP_201_CREATED)
def create_art_caso(
    body: ArtCasoCreate,
    current_user: Usuario = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ArtCasoResponse:
    """Crear un nuevo caso ART."""
    svc = PermisosService(db)
    if not svc.tiene_permiso(current_user, "rrhh.gestionar"):
        raise HTTPException(status_code=403, detail="Sin permiso: rrhh.gestionar")

    # Validar empleado
    empleado = db.query(RRHHEmpleado).filter(RRHHEmpleado.id == body.empleado_id).first()
    if not empleado:
        raise HTTPException(status_code=404, detail="Empleado no encontrado")

    # Validar estado
    estados_validos = [e.value for e in EstadoArt]
    if body.estado not in estados_validos:
        raise HTTPException(
            status_code=400,
            detail=f"Estado inválido. Opciones: {', '.join(estados_validos)}",
        )

    caso = RRHHArtCaso(
        empleado_id=body.empleado_id,
        numero_siniestro=body.numero_siniestro,
        fecha_accidente=body.fecha_accidente,
        descripcion_accidente=body.descripcion_accidente,
        lugar_accidente=body.lugar_accidente,
        tipo_lesion=body.tipo_lesion,
        parte_cuerpo=body.parte_cuerpo,
        art_nombre=body.art_nombre,
        numero_expediente_art=body.numero_expediente_art,
        estado=body.estado,
        observaciones=body.observaciones,
        creado_por_id=current_user.id,
    )
    db.add(caso)
    db.commit()
    db.refresh(caso)
    return ArtCasoResponse.model_validate(caso)


@router.get("/art/{caso_id}", response_model=ArtCasoResponse)
def get_art_caso(
    caso_id: int,
    current_user: Usuario = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ArtCasoResponse:
    """Obtener detalle de un caso ART."""
    svc = PermisosService(db)
    if not svc.tiene_permiso(current_user, "rrhh.ver"):
        raise HTTPException(status_code=403, detail="Sin permiso: rrhh.ver")

    caso = db.query(RRHHArtCaso).options(selectinload(RRHHArtCaso.documentos)).filter(RRHHArtCaso.id == caso_id).first()
    if not caso:
        raise HTTPException(status_code=404, detail="Caso ART no encontrado")

    return ArtCasoResponse.model_validate(caso)


@router.put("/art/{caso_id}", response_model=ArtCasoResponse)
def update_art_caso(
    caso_id: int,
    body: ArtCasoUpdate,
    current_user: Usuario = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ArtCasoResponse:
    """Actualizar un caso ART."""
    svc = PermisosService(db)
    if not svc.tiene_permiso(current_user, "rrhh.gestionar"):
        raise HTTPException(status_code=403, detail="Sin permiso: rrhh.gestionar")

    caso = db.query(RRHHArtCaso).options(selectinload(RRHHArtCaso.documentos)).filter(RRHHArtCaso.id == caso_id).first()
    if not caso:
        raise HTTPException(status_code=404, detail="Caso ART no encontrado")

    # Validar estado si se envía
    if body.estado is not None:
        estados_validos = [e.value for e in EstadoArt]
        if body.estado not in estados_validos:
            raise HTTPException(
                status_code=400,
                detail=f"Estado inválido. Opciones: {', '.join(estados_validos)}",
            )

    update_data = body.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(caso, field, value)

    db.commit()
    db.refresh(caso)
    return ArtCasoResponse.model_validate(caso)


# ──────────────────────────────────────────────
# ENDPOINTS — ART Documentos
# ──────────────────────────────────────────────


@router.post(
    "/art/{caso_id}/documentos",
    response_model=ArtDocumentoResponse,
    status_code=status.HTTP_201_CREATED,
)
def upload_art_documento(
    caso_id: int,
    file: UploadFile = File(...),
    descripcion: Optional[str] = None,
    current_user: Usuario = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ArtDocumentoResponse:
    """
    Subir documentación médica a un caso ART.

    Archivos se almacenan en {RRHH_UPLOADS_DIR}/art/{caso_id}/.
    """
    svc = PermisosService(db)
    if not svc.tiene_permiso(current_user, "rrhh.gestionar"):
        raise HTTPException(status_code=403, detail="Sin permiso: rrhh.gestionar")

    caso = db.query(RRHHArtCaso).filter(RRHHArtCaso.id == caso_id).first()
    if not caso:
        raise HTTPException(status_code=404, detail="Caso ART no encontrado")

    # Leer archivo y validar tamaño
    contenido = file.file.read()
    max_bytes = settings.RRHH_MAX_FILE_SIZE_MB * 1024 * 1024
    if len(contenido) > max_bytes:
        raise HTTPException(
            status_code=400,
            detail=f"Archivo excede el máximo de {settings.RRHH_MAX_FILE_SIZE_MB} MB",
        )

    # Generar nombre único
    unique_prefix = uuid.uuid4().hex[:12]
    safe_filename = file.filename or "documento"
    safe_filename = safe_filename.replace("/", "_").replace("\\", "_")
    nombre_unico = f"{unique_prefix}_{safe_filename}"

    # Crear directorio
    upload_dir = os.path.join(settings.RRHH_UPLOADS_DIR, "art", str(caso_id))
    os.makedirs(upload_dir, exist_ok=True)

    # Guardar archivo
    full_path = os.path.join(upload_dir, nombre_unico)
    with open(full_path, "wb") as f:
        f.write(contenido)

    # Path relativo para la DB
    path_relativo = os.path.join("art", str(caso_id), nombre_unico)

    documento = RRHHArtDocumento(
        art_caso_id=caso_id,
        nombre_archivo=file.filename or "documento",
        path_archivo=path_relativo,
        mime_type=file.content_type,
        tamano_bytes=len(contenido),
        descripcion=descripcion,
        subido_por_id=current_user.id,
    )
    db.add(documento)
    db.commit()
    db.refresh(documento)
    return ArtDocumentoResponse.model_validate(documento)


@router.get("/art/{caso_id}/documentos/{doc_id}/download")
def download_art_documento(
    caso_id: int,
    doc_id: int,
    current_user: Usuario = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Descargar documento médico de un caso ART.

    Auth-gated: requiere permiso rrhh.ver.
    """
    svc = PermisosService(db)
    if not svc.tiene_permiso(current_user, "rrhh.ver"):
        raise HTTPException(status_code=403, detail="Sin permiso: rrhh.ver")

    documento = (
        db.query(RRHHArtDocumento)
        .filter(
            RRHHArtDocumento.id == doc_id,
            RRHHArtDocumento.art_caso_id == caso_id,
        )
        .first()
    )
    if not documento:
        raise HTTPException(status_code=404, detail="Documento no encontrado")

    full_path = os.path.join(settings.RRHH_UPLOADS_DIR, documento.path_archivo)
    if not os.path.exists(full_path):
        raise HTTPException(
            status_code=404,
            detail="Archivo no encontrado en el servidor",
        )

    return FileResponse(
        path=full_path,
        filename=documento.nombre_archivo,
        media_type=documento.mime_type or "application/octet-stream",
    )


@router.delete(
    "/art/{caso_id}/documentos/{doc_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_art_documento(
    caso_id: int,
    doc_id: int,
    current_user: Usuario = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> None:
    """Eliminar documento médico de un caso ART (archivo + registro)."""
    svc = PermisosService(db)
    if not svc.tiene_permiso(current_user, "rrhh.gestionar"):
        raise HTTPException(status_code=403, detail="Sin permiso: rrhh.gestionar")

    documento = (
        db.query(RRHHArtDocumento)
        .filter(
            RRHHArtDocumento.id == doc_id,
            RRHHArtDocumento.art_caso_id == caso_id,
        )
        .first()
    )
    if not documento:
        raise HTTPException(status_code=404, detail="Documento no encontrado")

    # Borrar archivo físico
    full_path = os.path.join(settings.RRHH_UPLOADS_DIR, documento.path_archivo)
    if os.path.exists(full_path):
        os.remove(full_path)

    db.delete(documento)
    db.commit()
