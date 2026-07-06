"""
Router del módulo RRHH - Horarios, Fichadas e integración Hikvision.

Endpoints:
- Fichadas: listar, registro manual, sincronización Hikvision
- Hikvision: usuarios del dispositivo, mapeo empleado ↔ Hikvision employeeNo
- Horarios: CRUD de configuraciones de turno
- Excepciones: CRUD de feriados y días especiales

Fichadas Hikvision:
  - Sync vía ISAPI (POST /ISAPI/AccessControl/AcsEvent?format=json)
  - Dedup por event_id (serialNo del dispositivo)
  - Mapeo empleado: employeeNoString → rrhh_empleados.hikvision_employee_no
"""

from datetime import date, datetime, time
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session, joinedload

from app.core.database import get_db
from app.api.deps import get_current_user
from app.models.rrhh_empleado import RRHHEmpleado
from app.models.rrhh_empleado_horario import RRHHEmpleadoHorario
from app.models.rrhh_fichada import OrigenFichada, RRHHFichada, TipoFichada
from app.models.rrhh_hikvision_user import RRHHHikvisionUser
from app.models.rrhh_horario import RRHHHorarioConfig, RRHHHorarioExcepcion
from app.models.usuario import Usuario
from app.services.permisos_service import PermisosService
from app.services.rrhh_hikvision_client import HikvisionClient

router = APIRouter(prefix="/rrhh", tags=["rrhh-horarios"])


# ──────────────────────────────────────────────
# SCHEMAS — Fichadas
# ──────────────────────────────────────────────


class FichadaResponse(BaseModel):
    """Registro de fichada (clock-in/out)."""

    id: int
    empleado_id: Optional[int] = None
    empleado_nombre: str = ""
    empleado_legajo: str = ""
    hikvision_employee_no: Optional[str] = None
    timestamp: datetime
    tipo: str
    origen: str
    device_serial: Optional[str] = None
    event_id: Optional[str] = None
    registrado_por_nombre: str = ""
    motivo_manual: Optional[str] = None
    horas_dia: Optional[float] = None
    minutos_tarde: Optional[int] = None
    puntualidad: Optional[str] = None  # "a_tiempo" | "tolerancia" | "tarde" | None
    # Mobile geo fields (informative, NULL for non-mobile fichadas)
    latitud: Optional[float] = None
    longitud: Optional[float] = None
    accuracy_metros: Optional[float] = None
    distancia_oficina_metros: Optional[float] = None
    created_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class FichadaManualCreate(BaseModel):
    """Datos para registrar una fichada manual."""

    empleado_id: int
    timestamp: datetime
    tipo: str = Field(description="entrada o salida")
    motivo_manual: str = Field(min_length=1, max_length=500)


class FichadaMotivoUpdate(BaseModel):
    """Datos para actualizar el motivo de una fichada."""

    motivo_manual: str = Field(min_length=1, max_length=500)


class FichadaListResponse(BaseModel):
    """Lista paginada de fichadas."""

    items: list[FichadaResponse] = []
    total: int = 0


class SyncHikvisionRequest(BaseModel):
    """Parámetros para sincronización Hikvision."""

    desde: Optional[datetime] = None


class SyncHikvisionResponse(BaseModel):
    """Resultado de sincronización con Hikvision."""

    nuevas: int = 0
    duplicadas: int = 0
    sin_empleado: int = 0
    errores: int = 0


# ──────────────────────────────────────────────
# SCHEMAS — Hikvision Users
# ──────────────────────────────────────────────


class HikvisionUserResponse(BaseModel):
    """Usuario registrado en el dispositivo Hikvision."""

    employee_no: str
    name: str
    user_type: str = ""
    valid_begin: Optional[str] = None
    valid_end: Optional[str] = None
    # Mapeo con nuestro sistema
    empleado_id: Optional[int] = None
    empleado_nombre: Optional[str] = None


class HikvisionMappingRequest(BaseModel):
    """Asignar un employeeNo de Hikvision a un empleado."""

    empleado_id: int
    hikvision_employee_no: str = Field(min_length=1, max_length=20)


# ──────────────────────────────────────────────
# SCHEMAS — Horarios
# ──────────────────────────────────────────────


class HorarioConfigResponse(BaseModel):
    """Configuración de turno/horario."""

    id: int
    nombre: str
    hora_entrada: time
    hora_salida: time
    tolerancia_minutos: int
    dias_semana: str
    activo: bool
    created_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class HorarioConfigCreate(BaseModel):
    """Datos para crear un horario."""

    nombre: str = Field(min_length=1, max_length=100)
    hora_entrada: time
    hora_salida: time
    tolerancia_minutos: int = Field(default=15, ge=0, le=120)
    dias_semana: str = Field(
        default="1,2,3,4,5",
        max_length=20,
        description="Días laborables: 1=Lun ... 7=Dom, separados por coma",
    )
    activo: bool = True


class HorarioConfigUpdate(BaseModel):
    """Datos para actualizar un horario."""

    nombre: Optional[str] = Field(default=None, min_length=1, max_length=100)
    hora_entrada: Optional[time] = None
    hora_salida: Optional[time] = None
    tolerancia_minutos: Optional[int] = Field(default=None, ge=0, le=120)
    dias_semana: Optional[str] = Field(default=None, max_length=20)
    activo: Optional[bool] = None


# ──────────────────────────────────────────────
# SCHEMAS — Excepciones
# ──────────────────────────────────────────────


class ExcepcionResponse(BaseModel):
    """Excepción de horario (feriado o día especial)."""

    id: int
    fecha: date
    tipo: str
    descripcion: str
    es_laborable: bool
    created_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class ExcepcionCreate(BaseModel):
    """Datos para crear una excepción."""

    fecha: date
    tipo: str = Field(description="feriado o dia_especial")
    descripcion: str = Field(min_length=1, max_length=255)
    es_laborable: bool = False


class ExcepcionUpdate(BaseModel):
    """Datos para actualizar una excepción."""

    tipo: Optional[str] = None
    descripcion: Optional[str] = Field(default=None, min_length=1, max_length=255)
    es_laborable: Optional[bool] = None


# ──────────────────────────────────────────────
# HELPERS
# ──────────────────────────────────────────────


def _check_permiso(db: Session, user: Usuario, codigo: str) -> None:
    """Verifica permiso o lanza 403."""
    if not PermisosService(db).tiene_permiso(user, codigo):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Sin permiso: {codigo}",
        )


def _get_empleado_or_404(db: Session, empleado_id: int) -> RRHHEmpleado:
    """Obtiene empleado o lanza 404."""
    empleado = db.query(RRHHEmpleado).filter(RRHHEmpleado.id == empleado_id).first()
    if not empleado:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Empleado {empleado_id} no encontrado",
        )
    return empleado


def _validate_tipo_fichada(tipo: str) -> str:
    """Valida y normaliza tipo de fichada."""
    valores_validos = [e.value for e in TipoFichada]
    if tipo not in valores_validos:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Tipo de fichada inválido. Opciones: {', '.join(valores_validos)}",
        )
    return tipo


def _validate_tipo_excepcion(tipo: str) -> str:
    """Valida tipo de excepción."""
    tipos_validos = ["feriado", "dia_especial"]
    if tipo not in tipos_validos:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Tipo de excepción inválido. Opciones: {', '.join(tipos_validos)}",
        )
    return tipo


def _validate_dias_semana(dias: str) -> str:
    """Valida formato de días de semana (1-7 separados por coma)."""
    try:
        parts = [int(d.strip()) for d in dias.split(",")]
        if not all(1 <= d <= 7 for d in parts):
            raise ValueError
        return ",".join(str(d) for d in sorted(set(parts)))
    except (ValueError, AttributeError):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Formato de días inválido. Usar números 1-7 separados por coma (1=Lun, 7=Dom)",
        )


# ──────────────────────────────────────────────
# Tardanza helpers
# ──────────────────────────────────────────────


def _build_horario_map(
    db: Session,
    emp_ids: list[int],
) -> dict[int, tuple[time, int, set[int]]]:
    """
    Build a map of empleado_id → (hora_entrada, tolerancia_minutos, dias_laborales).

    Uses the highest-priority (lowest prioridad value) active horario per employee.
    Returns empty dict entries are omitted — callers should .get() with None fallback.
    """
    if not emp_ids:
        return {}

    asignaciones = (
        db.query(RRHHEmpleadoHorario)
        .filter(RRHHEmpleadoHorario.empleado_id.in_(emp_ids))
        .order_by(RRHHEmpleadoHorario.prioridad.asc())
        .all()
    )
    horario_ids = list({a.horario_config_id for a in asignaciones})
    if not horario_ids:
        return {}

    horarios = (
        db.query(RRHHHorarioConfig)
        .filter(RRHHHorarioConfig.id.in_(horario_ids), RRHHHorarioConfig.activo.is_(True))
        .all()
    )
    horarios_by_id = {h.id: h for h in horarios}

    result: dict[int, tuple[time, int, set[int]]] = {}
    for asig in asignaciones:
        if asig.empleado_id in result:
            continue  # ya tiene el de mayor prioridad
        h = horarios_by_id.get(asig.horario_config_id)
        if not h:
            continue
        dias = set()
        if h.dias_semana:
            for d in h.dias_semana.split(","):
                d_stripped = d.strip()
                if d_stripped.isdigit():
                    dias.add(int(d_stripped))
        result[asig.empleado_id] = (h.hora_entrada, h.tolerancia_minutos, dias)

    return result


def _calc_puntualidad(
    primera_entrada: datetime,
    hora_entrada: time,
    tolerancia_min: int,
    dias_laborales: set[int],
) -> tuple[Optional[int], Optional[str]]:
    """
    Compare first entry timestamp against scheduled time.

    Returns (minutos_tarde, puntualidad):
    - (0, "a_tiempo") — arrived on time or early
    - (N, "tolerancia") — arrived 1..tolerancia minutes late
    - (N, "tarde") — arrived >tolerancia minutes late
    - (None, None) — not a work day for this employee
    """
    from datetime import timedelta as td, timezone as tz

    ART_TZ = tz(td(hours=-3))
    entrada_local = primera_entrada.astimezone(ART_TZ)

    # Skip non-work days
    if dias_laborales and entrada_local.isoweekday() not in dias_laborales:
        return None, None

    hora_real = entrada_local.time()
    scheduled = datetime.combine(entrada_local.date(), hora_entrada)
    actual = datetime.combine(entrada_local.date(), hora_real)

    diff_minutes = int((actual - scheduled).total_seconds() / 60)

    if diff_minutes <= 0:
        return 0, "a_tiempo"
    if diff_minutes <= tolerancia_min:
        return diff_minutes, "tolerancia"
    return diff_minutes, "tarde"


# ──────────────────────────────────────────────
# ENDPOINTS — Fichadas
# ──────────────────────────────────────────────


@router.get(
    "/fichadas",
    response_model=FichadaListResponse,
    summary="Listar fichadas con filtros y paginación",
)
def listar_fichadas(
    empleado_id: Optional[int] = None,
    fecha_desde: Optional[date] = None,
    fecha_hasta: Optional[date] = None,
    tipo: Optional[str] = None,
    origen: Optional[str] = None,
    orden: str = Query("desc", pattern="^(asc|desc)$", description="Orden por timestamp: asc o desc"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> FichadaListResponse:
    """Lista fichadas con filtros opcionales y paginación."""
    _check_permiso(db, current_user, "rrhh.ver")

    # Build base query with filters (WITHOUT joinedload for accurate count)
    base_query = db.query(RRHHFichada)

    if empleado_id:
        base_query = base_query.filter(RRHHFichada.empleado_id == empleado_id)
    if fecha_desde:
        base_query = base_query.filter(RRHHFichada.timestamp >= datetime.combine(fecha_desde, time.min))
    if fecha_hasta:
        base_query = base_query.filter(RRHHFichada.timestamp <= datetime.combine(fecha_hasta, time(23, 59, 59)))
    if tipo:
        _validate_tipo_fichada(tipo)
        base_query = base_query.filter(RRHHFichada.tipo == tipo)
    if origen:
        valores_origen = [e.value for e in OrigenFichada]
        if origen not in valores_origen:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Origen inválido. Opciones: {', '.join(valores_origen)}",
            )
        base_query = base_query.filter(RRHHFichada.origen == origen)

    total = base_query.count()
    offset = (page - 1) * page_size
    order_clause = RRHHFichada.timestamp.asc() if orden == "asc" else RRHHFichada.timestamp.desc()
    fichadas = (
        base_query.options(
            joinedload(RRHHFichada.empleado),
            joinedload(RRHHFichada.registrado_por),
        )
        .order_by(order_clause)
        .offset(offset)
        .limit(page_size)
        .all()
    )

    # ── Calculate horas_dia per employee+day ──
    emp_day_pairs: set[tuple[int, date]] = set()
    for f in fichadas:
        if f.empleado_id and hasattr(f.timestamp, "date"):
            emp_day_pairs.add((f.empleado_id, f.timestamp.date()))

    horas_dia_map: dict[tuple[int, date], float] = {}
    if emp_day_pairs:
        for emp_id, dia in emp_day_pairs:
            dia_fichadas = (
                db.query(RRHHFichada)
                .filter(
                    RRHHFichada.empleado_id == emp_id,
                    RRHHFichada.timestamp >= datetime.combine(dia, time.min),
                    RRHHFichada.timestamp <= datetime.combine(dia, time(23, 59, 59)),
                )
                .order_by(RRHHFichada.timestamp.asc())
                .all()
            )
            entradas = [ff for ff in dia_fichadas if ff.tipo == "entrada"]
            salidas = [ff for ff in dia_fichadas if ff.tipo == "salida"]
            pares = min(len(entradas), len(salidas))
            minutos = 0.0
            for i in range(pares):
                delta = salidas[i].timestamp - entradas[i].timestamp
                minutos += max(delta.total_seconds() / 60, 0)
            horas_dia_map[(emp_id, dia)] = round(minutos / 60, 2)

    # ── Tardiness: build horario map + first-entry map ──
    page_emp_ids = list({f.empleado_id for f in fichadas if f.empleado_id})
    horario_map = _build_horario_map(db, page_emp_ids)

    # First entry per (employee, day) — to mark only the first entry, not salidas
    from sqlalchemy import func as sa_func

    primera_entrada_map: dict[tuple[int, str], datetime] = {}
    if page_emp_ids and emp_day_pairs:
        first_entries = (
            db.query(
                RRHHFichada.empleado_id,
                sa_func.date(RRHHFichada.timestamp).label("fecha"),
                sa_func.min(RRHHFichada.timestamp).label("primera"),
            )
            .filter(
                RRHHFichada.empleado_id.in_(page_emp_ids),
                RRHHFichada.tipo == "entrada",
                RRHHFichada.timestamp >= datetime.combine(min(d for _, d in emp_day_pairs), time.min),
                RRHHFichada.timestamp <= datetime.combine(max(d for _, d in emp_day_pairs), time(23, 59, 59)),
            )
            .group_by(RRHHFichada.empleado_id, sa_func.date(RRHHFichada.timestamp))
            .all()
        )
        for row in first_entries:
            fecha_iso = row.fecha if isinstance(row.fecha, str) else row.fecha.isoformat()
            primera_entrada_map[(row.empleado_id, fecha_iso)] = row.primera

    items = []
    for f in fichadas:
        emp = f.empleado
        horas = None
        minutos_tarde = None
        puntualidad = None
        if f.empleado_id and hasattr(f.timestamp, "date"):
            horas = horas_dia_map.get((f.empleado_id, f.timestamp.date()))
            # Tardiness: only for "entrada" fichadas that are the first of the day
            if f.tipo == "entrada":
                horario_info = horario_map.get(f.empleado_id)
                if horario_info:
                    fecha_iso = f.timestamp.date().isoformat()
                    primera = primera_entrada_map.get((f.empleado_id, fecha_iso))
                    if primera and abs((f.timestamp - primera).total_seconds()) < 60:
                        h_entrada, h_tolerancia, h_dias = horario_info
                        minutos_tarde, puntualidad = _calc_puntualidad(
                            f.timestamp,
                            h_entrada,
                            h_tolerancia,
                            h_dias,
                        )
        items.append(
            FichadaResponse(
                id=f.id,
                empleado_id=f.empleado_id,
                empleado_nombre=f"{emp.apellido}, {emp.nombre}" if emp else "",
                empleado_legajo=emp.legajo if emp else "",
                hikvision_employee_no=f.hikvision_employee_no,
                timestamp=f.timestamp,
                tipo=f.tipo,
                origen=f.origen,
                device_serial=f.device_serial,
                event_id=f.event_id,
                registrado_por_nombre=(f.registrado_por.nombre if f.registrado_por else ""),
                motivo_manual=f.motivo_manual,
                horas_dia=horas,
                minutos_tarde=minutos_tarde,
                puntualidad=puntualidad,
                latitud=float(f.latitud) if f.latitud is not None else None,
                longitud=float(f.longitud) if f.longitud is not None else None,
                accuracy_metros=f.accuracy_metros,
                distancia_oficina_metros=f.distancia_oficina_metros,
                created_at=f.created_at,
            )
        )

    return FichadaListResponse(items=items, total=total)


@router.post(
    "/fichadas/manual",
    response_model=FichadaResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Registrar fichada manual",
)
def registrar_fichada_manual(
    data: FichadaManualCreate,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> FichadaResponse:
    """Registra una fichada manual (entrada/salida) para un empleado."""
    _check_permiso(db, current_user, "rrhh.gestionar")
    empleado = _get_empleado_or_404(db, data.empleado_id)
    _validate_tipo_fichada(data.tipo)

    fichada = RRHHFichada(
        empleado_id=data.empleado_id,
        timestamp=data.timestamp,
        tipo=data.tipo,
        origen=OrigenFichada.MANUAL.value,
        registrado_por_id=current_user.id,
        motivo_manual=data.motivo_manual,
    )
    db.add(fichada)
    db.commit()
    db.refresh(fichada)

    return FichadaResponse(
        id=fichada.id,
        empleado_id=fichada.empleado_id,
        empleado_nombre=f"{empleado.apellido}, {empleado.nombre}",
        empleado_legajo=empleado.legajo or "",
        timestamp=fichada.timestamp,
        tipo=fichada.tipo,
        origen=fichada.origen,
        device_serial=fichada.device_serial,
        event_id=fichada.event_id,
        registrado_por_nombre=current_user.nombre,
        motivo_manual=fichada.motivo_manual,
        created_at=fichada.created_at,
    )


@router.post(
    "/fichadas/sync-hikvision",
    response_model=SyncHikvisionResponse,
    summary="Sincronizar fichadas desde dispositivo Hikvision",
)
def sync_hikvision(
    data: Optional[SyncHikvisionRequest] = None,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> SyncHikvisionResponse:
    """
    Sincroniza fichadas desde el terminal Hikvision DS-K1T804.

    Si no se especifica 'desde', sincroniza las últimas 24 horas.
    Requiere permiso rrhh.gestionar.
    """
    _check_permiso(db, current_user, "rrhh.gestionar")

    client = HikvisionClient(db)
    desde = data.desde if data else None

    try:
        result = client.sync_fichadas(desde)
        db.commit()
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )
    except ConnectionError as e:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(e),
        )

    return SyncHikvisionResponse(**result)


@router.delete(
    "/fichadas/{fichada_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Eliminar una fichada manual",
)
def eliminar_fichada(
    fichada_id: int,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> None:
    """Elimina una fichada manual o mobile. Las de Hikvision no se eliminan."""
    _check_permiso(db, current_user, "rrhh.gestionar")

    fichada = db.query(RRHHFichada).filter(RRHHFichada.id == fichada_id).first()
    if not fichada:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Fichada {fichada_id} no encontrada",
        )

    origenes_eliminables = {OrigenFichada.MANUAL.value, OrigenFichada.MOBILE.value}
    if fichada.origen not in origenes_eliminables:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Solo se pueden eliminar fichadas manuales o mobile. Las de Hikvision no se eliminan.",
        )

    db.delete(fichada)
    db.commit()


@router.patch(
    "/fichadas/{fichada_id}/motivo",
    response_model=FichadaResponse,
    summary="Actualizar motivo/detalle de una fichada",
)
def actualizar_motivo_fichada(
    fichada_id: int,
    data: FichadaMotivoUpdate,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> FichadaResponse:
    """Actualiza el motivo/detalle de cualquier fichada (manual o hikvision)."""
    _check_permiso(db, current_user, "rrhh.gestionar")

    fichada = (
        db.query(RRHHFichada)
        .options(joinedload(RRHHFichada.empleado), joinedload(RRHHFichada.registrado_por))
        .filter(RRHHFichada.id == fichada_id)
        .first()
    )
    if not fichada:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Fichada {fichada_id} no encontrada",
        )

    fichada.motivo_manual = data.motivo_manual
    db.commit()
    db.refresh(fichada)

    emp = fichada.empleado
    return FichadaResponse(
        id=fichada.id,
        empleado_id=fichada.empleado_id,
        empleado_nombre=f"{emp.apellido}, {emp.nombre}" if emp else "",
        empleado_legajo=emp.legajo if emp else "",
        timestamp=fichada.timestamp,
        tipo=fichada.tipo,
        origen=fichada.origen,
        device_serial=fichada.device_serial,
        event_id=fichada.event_id,
        registrado_por_nombre=(fichada.registrado_por.nombre if fichada.registrado_por else ""),
        motivo_manual=fichada.motivo_manual,
        created_at=fichada.created_at,
    )


# ──────────────────────────────────────────────
# ENDPOINTS — Hikvision Users & Mapping
# ──────────────────────────────────────────────


@router.get(
    "/hikvision/usuarios",
    response_model=list[HikvisionUserResponse],
    summary="Listar usuarios del dispositivo Hikvision",
)
def listar_usuarios_hikvision(
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> list[HikvisionUserResponse]:
    """
    Consulta la ISAPI del Hikvision y devuelve los usuarios registrados.

    Enriquece con el mapeo a empleados de la app (via hikvision_employee_no).
    """
    _check_permiso(db, current_user, "rrhh.gestionar")

    client = HikvisionClient(db)

    try:
        hik_users = client.fetch_users()
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )
    except ConnectionError as e:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(e),
        )

    # Pre-cargar mapeo hikvision_employee_no → empleado
    empleados = db.query(RRHHEmpleado).filter(RRHHEmpleado.hikvision_employee_no.isnot(None)).all()
    hik_to_emp = {emp.hikvision_employee_no: emp for emp in empleados}

    result = []
    for u in hik_users:
        employee_no = str(u.get("employeeNo", ""))
        valid_info = u.get("Valid", {})
        emp = hik_to_emp.get(employee_no)

        result.append(
            HikvisionUserResponse(
                employee_no=employee_no,
                name=u.get("name", ""),
                user_type=u.get("userType", ""),
                valid_begin=valid_info.get("beginTime"),
                valid_end=valid_info.get("endTime"),
                empleado_id=emp.id if emp else None,
                empleado_nombre=emp.nombre_completo if emp else None,
            )
        )

    return result


# ──────────────────────────────────────────────
# Hikvision Users Cache (local DB)
# ──────────────────────────────────────────────


@router.get(
    "/hikvision/users-cache",
    response_model=list[HikvisionUserResponse],
    summary="Leer usuarios Hikvision desde cache local",
)
def get_hikvision_users_cache(
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> list[HikvisionUserResponse]:
    """Lee usuarios Hikvision desde la tabla cache (no consulta el dispositivo)."""
    _check_permiso(db, current_user, "rrhh.ver")

    cached = db.query(RRHHHikvisionUser).order_by(RRHHHikvisionUser.employee_no).all()

    # Enrich with empleado mapping
    empleados = db.query(RRHHEmpleado).filter(RRHHEmpleado.hikvision_employee_no.isnot(None)).all()
    hik_to_emp = {emp.hikvision_employee_no: emp for emp in empleados}

    return [
        HikvisionUserResponse(
            employee_no=u.employee_no,
            name=u.name,
            user_type=u.user_type,
            valid_begin=u.valid_begin,
            valid_end=u.valid_end,
            empleado_id=hik_to_emp[u.employee_no].id if u.employee_no in hik_to_emp else None,
            empleado_nombre=(hik_to_emp[u.employee_no].nombre_completo if u.employee_no in hik_to_emp else None),
        )
        for u in cached
    ]


@router.post(
    "/hikvision/sync-users",
    summary="Sincronizar usuarios Hikvision al cache local",
)
def sync_hikvision_users_cache(
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> dict:
    """
    Consulta la ISAPI del Hikvision, obtiene todos los usuarios registrados
    y los guarda/actualiza en la tabla cache local.

    Se ejecuta manualmente cuando se registra un empleado nuevo en el dispositivo.
    """
    _check_permiso(db, current_user, "rrhh.gestionar")

    client = HikvisionClient(db)
    try:
        hik_users = client.fetch_users()
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except ConnectionError as e:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(e))

    # Upsert: por cada usuario, crear o actualizar en cache
    nuevos = 0
    actualizados = 0
    for u in hik_users:
        employee_no = str(u.get("employeeNo", ""))
        if not employee_no:
            continue

        valid_info = u.get("Valid", {})
        existing = db.query(RRHHHikvisionUser).filter(RRHHHikvisionUser.employee_no == employee_no).first()
        if existing:
            existing.name = u.get("name", "")
            existing.user_type = u.get("userType", "")
            existing.valid_begin = valid_info.get("beginTime")
            existing.valid_end = valid_info.get("endTime")
            actualizados += 1
        else:
            db.add(
                RRHHHikvisionUser(
                    employee_no=employee_no,
                    name=u.get("name", ""),
                    user_type=u.get("userType", ""),
                    valid_begin=valid_info.get("beginTime"),
                    valid_end=valid_info.get("endTime"),
                )
            )
            nuevos += 1

    db.commit()

    return {
        "total_dispositivo": len(hik_users),
        "nuevos": nuevos,
        "actualizados": actualizados,
    }


@router.post(
    "/hikvision/mapear",
    status_code=status.HTTP_200_OK,
    summary="Asignar un empleado a un usuario Hikvision",
)
def mapear_empleado_hikvision(
    data: HikvisionMappingRequest,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> dict:
    """
    Asigna el hikvision_employee_no a un empleado.

    Esto vincula el employeeNo del dispositivo Hikvision con el empleado
    en la app, permitiendo la sincronización automática de fichadas.
    """
    _check_permiso(db, current_user, "rrhh.gestionar")

    empleado = _get_empleado_or_404(db, data.empleado_id)

    # Check que el hikvision_employee_no no esté asignado a otro empleado
    existing = (
        db.query(RRHHEmpleado)
        .filter(
            RRHHEmpleado.hikvision_employee_no == data.hikvision_employee_no,
            RRHHEmpleado.id != data.empleado_id,
        )
        .first()
    )
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"El ID Hikvision '{data.hikvision_employee_no}' ya está "
                f"asignado a {existing.nombre_completo} (ID {existing.id})"
            ),
        )

    empleado.hikvision_employee_no = data.hikvision_employee_no

    # Vincular retroactivamente fichadas huérfanas con este hikvision_employee_no
    fichadas_vinculadas = HikvisionClient.vincular_fichadas_retroactivas(db, data.hikvision_employee_no, empleado.id)

    db.commit()

    return {
        "message": (
            f"Empleado {empleado.nombre_completo} vinculado al usuario Hikvision #{data.hikvision_employee_no}"
        ),
        "empleado_id": empleado.id,
        "hikvision_employee_no": data.hikvision_employee_no,
        "fichadas_vinculadas": fichadas_vinculadas,
    }


@router.delete(
    "/hikvision/mapear/{empleado_id}",
    status_code=status.HTTP_200_OK,
    summary="Desvincular empleado de Hikvision",
)
def desmapear_empleado_hikvision(
    empleado_id: int,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> dict:
    """Quita la vinculación Hikvision de un empleado."""
    _check_permiso(db, current_user, "rrhh.gestionar")

    empleado = _get_empleado_or_404(db, empleado_id)
    old_no = empleado.hikvision_employee_no
    empleado.hikvision_employee_no = None
    db.commit()

    return {
        "message": f"Empleado {empleado.nombre_completo} desvinculado de Hikvision (era #{old_no})",
    }


# ──────────────────────────────────────────────
# ENDPOINTS — Horarios Config
# ──────────────────────────────────────────────


@router.get(
    "/horarios",
    response_model=list[HorarioConfigResponse],
    summary="Listar configuraciones de horario",
)
def listar_horarios(
    solo_activos: bool = Query(True, description="Solo horarios activos"),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> list[HorarioConfigResponse]:
    """Lista todas las configuraciones de horario/turno."""
    _check_permiso(db, current_user, "rrhh.ver")

    query = db.query(RRHHHorarioConfig)
    if solo_activos:
        query = query.filter(RRHHHorarioConfig.activo.is_(True))

    horarios = query.order_by(RRHHHorarioConfig.nombre).all()

    return [
        HorarioConfigResponse(
            id=h.id,
            nombre=h.nombre,
            hora_entrada=h.hora_entrada,
            hora_salida=h.hora_salida,
            tolerancia_minutos=h.tolerancia_minutos,
            dias_semana=h.dias_semana,
            activo=h.activo,
            created_at=h.created_at,
        )
        for h in horarios
    ]


@router.post(
    "/horarios",
    response_model=HorarioConfigResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Crear configuración de horario",
)
def crear_horario(
    data: HorarioConfigCreate,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> HorarioConfigResponse:
    """Crea un nuevo horario/turno de trabajo."""
    _check_permiso(db, current_user, "rrhh.config")

    dias_validados = _validate_dias_semana(data.dias_semana)

    # Check nombre único
    existing = db.query(RRHHHorarioConfig).filter(RRHHHorarioConfig.nombre == data.nombre).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Ya existe un horario con nombre '{data.nombre}'",
        )

    horario = RRHHHorarioConfig(
        nombre=data.nombre,
        hora_entrada=data.hora_entrada,
        hora_salida=data.hora_salida,
        tolerancia_minutos=data.tolerancia_minutos,
        dias_semana=dias_validados,
        activo=data.activo,
    )
    db.add(horario)
    db.commit()
    db.refresh(horario)

    return HorarioConfigResponse(
        id=horario.id,
        nombre=horario.nombre,
        hora_entrada=horario.hora_entrada,
        hora_salida=horario.hora_salida,
        tolerancia_minutos=horario.tolerancia_minutos,
        dias_semana=horario.dias_semana,
        activo=horario.activo,
        created_at=horario.created_at,
    )


@router.put(
    "/horarios/{horario_id}",
    response_model=HorarioConfigResponse,
    summary="Actualizar configuración de horario",
)
def actualizar_horario(
    horario_id: int,
    data: HorarioConfigUpdate,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> HorarioConfigResponse:
    """Actualiza un horario/turno existente."""
    _check_permiso(db, current_user, "rrhh.config")

    horario = db.query(RRHHHorarioConfig).filter(RRHHHorarioConfig.id == horario_id).first()
    if not horario:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Horario {horario_id} no encontrado",
        )

    if data.nombre is not None and data.nombre != horario.nombre:
        existing = (
            db.query(RRHHHorarioConfig)
            .filter(RRHHHorarioConfig.nombre == data.nombre, RRHHHorarioConfig.id != horario_id)
            .first()
        )
        if existing:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Ya existe un horario con nombre '{data.nombre}'",
            )
        horario.nombre = data.nombre

    if data.hora_entrada is not None:
        horario.hora_entrada = data.hora_entrada
    if data.hora_salida is not None:
        horario.hora_salida = data.hora_salida
    if data.tolerancia_minutos is not None:
        horario.tolerancia_minutos = data.tolerancia_minutos
    if data.dias_semana is not None:
        horario.dias_semana = _validate_dias_semana(data.dias_semana)
    if data.activo is not None:
        horario.activo = data.activo

    db.commit()
    db.refresh(horario)

    return HorarioConfigResponse(
        id=horario.id,
        nombre=horario.nombre,
        hora_entrada=horario.hora_entrada,
        hora_salida=horario.hora_salida,
        tolerancia_minutos=horario.tolerancia_minutos,
        dias_semana=horario.dias_semana,
        activo=horario.activo,
        created_at=horario.created_at,
    )


@router.delete(
    "/horarios/{horario_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Eliminar configuración de horario",
)
def eliminar_horario(
    horario_id: int,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> None:
    """Elimina un horario. Desactiva en lugar de borrar si tiene empleados asignados."""
    _check_permiso(db, current_user, "rrhh.config")

    horario = db.query(RRHHHorarioConfig).filter(RRHHHorarioConfig.id == horario_id).first()
    if not horario:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Horario {horario_id} no encontrado",
        )

    # Soft-delete: desactivar
    horario.activo = False
    db.commit()


# ──────────────────────────────────────────────
# ENDPOINTS — Excepciones (Feriados / Días Especiales)
# ──────────────────────────────────────────────


@router.get(
    "/horarios/excepciones",
    response_model=list[ExcepcionResponse],
    summary="Listar excepciones de horario",
)
def listar_excepciones(
    anio: Optional[int] = Query(None, description="Filtrar por año"),
    tipo: Optional[str] = Query(None, description="feriado o dia_especial"),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> list[ExcepcionResponse]:
    """Lista excepciones (feriados, días especiales)."""
    _check_permiso(db, current_user, "rrhh.ver")

    query = db.query(RRHHHorarioExcepcion)

    if anio:
        query = query.filter(
            RRHHHorarioExcepcion.fecha >= date(anio, 1, 1),
            RRHHHorarioExcepcion.fecha <= date(anio, 12, 31),
        )
    if tipo:
        _validate_tipo_excepcion(tipo)
        query = query.filter(RRHHHorarioExcepcion.tipo == tipo)

    excepciones = query.order_by(RRHHHorarioExcepcion.fecha.desc()).all()

    return [
        ExcepcionResponse(
            id=e.id,
            fecha=e.fecha,
            tipo=e.tipo,
            descripcion=e.descripcion,
            es_laborable=e.es_laborable,
            created_at=e.created_at,
        )
        for e in excepciones
    ]


@router.post(
    "/horarios/excepciones",
    response_model=ExcepcionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Crear excepción de horario",
)
def crear_excepcion(
    data: ExcepcionCreate,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> ExcepcionResponse:
    """Crea un feriado o día especial."""
    _check_permiso(db, current_user, "rrhh.config")
    _validate_tipo_excepcion(data.tipo)

    # Check fecha única
    existing = db.query(RRHHHorarioExcepcion).filter(RRHHHorarioExcepcion.fecha == data.fecha).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Ya existe una excepción para la fecha {data.fecha}",
        )

    excepcion = RRHHHorarioExcepcion(
        fecha=data.fecha,
        tipo=data.tipo,
        descripcion=data.descripcion,
        es_laborable=data.es_laborable,
    )
    db.add(excepcion)
    db.commit()
    db.refresh(excepcion)

    return ExcepcionResponse(
        id=excepcion.id,
        fecha=excepcion.fecha,
        tipo=excepcion.tipo,
        descripcion=excepcion.descripcion,
        es_laborable=excepcion.es_laborable,
        created_at=excepcion.created_at,
    )


@router.put(
    "/horarios/excepciones/{excepcion_id}",
    response_model=ExcepcionResponse,
    summary="Actualizar excepción de horario",
)
def actualizar_excepcion(
    excepcion_id: int,
    data: ExcepcionUpdate,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> ExcepcionResponse:
    """Actualiza un feriado o día especial."""
    _check_permiso(db, current_user, "rrhh.config")

    excepcion = db.query(RRHHHorarioExcepcion).filter(RRHHHorarioExcepcion.id == excepcion_id).first()
    if not excepcion:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Excepción {excepcion_id} no encontrada",
        )

    if data.tipo is not None:
        _validate_tipo_excepcion(data.tipo)
        excepcion.tipo = data.tipo
    if data.descripcion is not None:
        excepcion.descripcion = data.descripcion
    if data.es_laborable is not None:
        excepcion.es_laborable = data.es_laborable

    db.commit()
    db.refresh(excepcion)

    return ExcepcionResponse(
        id=excepcion.id,
        fecha=excepcion.fecha,
        tipo=excepcion.tipo,
        descripcion=excepcion.descripcion,
        es_laborable=excepcion.es_laborable,
        created_at=excepcion.created_at,
    )


@router.delete(
    "/horarios/excepciones/{excepcion_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Eliminar excepción de horario",
)
def eliminar_excepcion(
    excepcion_id: int,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> None:
    """Elimina un feriado o día especial."""
    _check_permiso(db, current_user, "rrhh.config")

    excepcion = db.query(RRHHHorarioExcepcion).filter(RRHHHorarioExcepcion.id == excepcion_id).first()
    if not excepcion:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Excepción {excepcion_id} no encontrada",
        )

    db.delete(excepcion)
    db.commit()


# ──────────────────────────────────────────────
# SCHEMAS — Empleado ↔ Horario (Turnos)
# ──────────────────────────────────────────────


class EmpleadoHorarioResponse(BaseModel):
    """Asignación de turno a empleado."""

    id: int
    empleado_id: int
    horario_config_id: int
    horario_nombre: str = ""
    hora_entrada: Optional[time] = None
    hora_salida: Optional[time] = None
    dias_semana: str = ""
    prioridad: int = 1
    created_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class EmpleadoHorarioCreate(BaseModel):
    """Datos para asignar un turno a un empleado."""

    horario_config_id: int
    prioridad: int = Field(default=1, ge=1, le=10)


class HorarioEmpleadoResponse(BaseModel):
    """Empleado asignado a un turno (vista desde el horario)."""

    asignacion_id: int
    empleado_id: int
    legajo: str = ""
    nombre_completo: str = ""
    prioridad: int = 1


# ──────────────────────────────────────────────
# ENDPOINTS — Empleado ↔ Horario (Turnos)
# ──────────────────────────────────────────────


@router.get(
    "/empleados/{empleado_id}/horarios",
    response_model=list[EmpleadoHorarioResponse],
    summary="Listar turnos asignados a un empleado",
)
def listar_horarios_empleado(
    empleado_id: int,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> list[EmpleadoHorarioResponse]:
    """Lista todos los turnos/horarios asignados a un empleado, ordenados por prioridad."""
    _check_permiso(db, current_user, "rrhh.ver")
    _get_empleado_or_404(db, empleado_id)

    asignaciones = (
        db.query(RRHHEmpleadoHorario)
        .options(joinedload(RRHHEmpleadoHorario.horario_config))
        .filter(RRHHEmpleadoHorario.empleado_id == empleado_id)
        .order_by(RRHHEmpleadoHorario.prioridad)
        .all()
    )

    return [
        EmpleadoHorarioResponse(
            id=a.id,
            empleado_id=a.empleado_id,
            horario_config_id=a.horario_config_id,
            horario_nombre=a.horario_config.nombre if a.horario_config else "",
            hora_entrada=a.horario_config.hora_entrada if a.horario_config else None,
            hora_salida=a.horario_config.hora_salida if a.horario_config else None,
            dias_semana=a.horario_config.dias_semana if a.horario_config else "",
            prioridad=a.prioridad,
            created_at=a.created_at,
        )
        for a in asignaciones
    ]


@router.post(
    "/empleados/{empleado_id}/horarios",
    response_model=EmpleadoHorarioResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Asignar un turno a un empleado",
)
def asignar_horario_empleado(
    empleado_id: int,
    data: EmpleadoHorarioCreate,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> EmpleadoHorarioResponse:
    """Asigna un turno/horario a un empleado."""
    _check_permiso(db, current_user, "rrhh.gestionar")
    _get_empleado_or_404(db, empleado_id)

    # Verificar que el horario existe y está activo
    horario = db.query(RRHHHorarioConfig).filter(RRHHHorarioConfig.id == data.horario_config_id).first()
    if not horario:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Horario {data.horario_config_id} no encontrado",
        )
    if not horario.activo:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No se puede asignar un horario inactivo",
        )

    # Verificar duplicado
    existing = (
        db.query(RRHHEmpleadoHorario)
        .filter(
            RRHHEmpleadoHorario.empleado_id == empleado_id,
            RRHHEmpleadoHorario.horario_config_id == data.horario_config_id,
        )
        .first()
    )
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Este turno ya está asignado a este empleado",
        )

    asignacion = RRHHEmpleadoHorario(
        empleado_id=empleado_id,
        horario_config_id=data.horario_config_id,
        prioridad=data.prioridad,
    )
    db.add(asignacion)
    db.commit()
    db.refresh(asignacion)

    return EmpleadoHorarioResponse(
        id=asignacion.id,
        empleado_id=asignacion.empleado_id,
        horario_config_id=asignacion.horario_config_id,
        horario_nombre=horario.nombre,
        hora_entrada=horario.hora_entrada,
        hora_salida=horario.hora_salida,
        dias_semana=horario.dias_semana,
        prioridad=asignacion.prioridad,
        created_at=asignacion.created_at,
    )


@router.delete(
    "/empleado-horarios/{asignacion_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Desasignar un turno de un empleado",
)
def desasignar_horario_empleado(
    asignacion_id: int,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> None:
    """Elimina la asignación de un turno a un empleado."""
    _check_permiso(db, current_user, "rrhh.gestionar")

    asignacion = db.query(RRHHEmpleadoHorario).filter(RRHHEmpleadoHorario.id == asignacion_id).first()
    if not asignacion:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Asignación {asignacion_id} no encontrada",
        )

    db.delete(asignacion)
    db.commit()


@router.get(
    "/horarios/{horario_id}/empleados",
    response_model=list[HorarioEmpleadoResponse],
    summary="Listar empleados asignados a un turno",
)
def listar_empleados_horario(
    horario_id: int,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> list[HorarioEmpleadoResponse]:
    """Lista todos los empleados asignados a un turno/horario específico."""
    _check_permiso(db, current_user, "rrhh.ver")

    horario = db.query(RRHHHorarioConfig).filter(RRHHHorarioConfig.id == horario_id).first()
    if not horario:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Horario {horario_id} no encontrado",
        )

    asignaciones = (
        db.query(RRHHEmpleadoHorario)
        .options(joinedload(RRHHEmpleadoHorario.empleado))
        .filter(RRHHEmpleadoHorario.horario_config_id == horario_id)
        .order_by(RRHHEmpleadoHorario.prioridad)
        .all()
    )

    return [
        HorarioEmpleadoResponse(
            asignacion_id=a.id,
            empleado_id=a.empleado_id,
            legajo=a.empleado.legajo if a.empleado else "",
            nombre_completo=a.empleado.nombre_completo if a.empleado else "",
            prioridad=a.prioridad,
        )
        for a in asignaciones
    ]
