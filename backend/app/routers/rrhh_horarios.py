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
from app.core.deps import get_current_user
from app.models.rrhh_empleado import RRHHEmpleado
from app.models.rrhh_fichada import OrigenFichada, RRHHFichada, TipoFichada
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
    timestamp: datetime
    tipo: str
    origen: str
    device_serial: Optional[str] = None
    event_id: Optional[str] = None
    registrado_por_nombre: str = ""
    motivo_manual: Optional[str] = None
    created_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class FichadaManualCreate(BaseModel):
    """Datos para registrar una fichada manual."""

    empleado_id: int
    timestamp: datetime
    tipo: str = Field(description="entrada o salida")
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
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> FichadaListResponse:
    """Lista fichadas con filtros opcionales y paginación."""
    _check_permiso(db, current_user, "rrhh.ver")

    query = db.query(RRHHFichada).options(
        joinedload(RRHHFichada.empleado),
        joinedload(RRHHFichada.registrado_por),
    )

    if empleado_id:
        query = query.filter(RRHHFichada.empleado_id == empleado_id)
    if fecha_desde:
        query = query.filter(RRHHFichada.timestamp >= datetime.combine(fecha_desde, time.min))
    if fecha_hasta:
        query = query.filter(RRHHFichada.timestamp <= datetime.combine(fecha_hasta, time(23, 59, 59)))
    if tipo:
        _validate_tipo_fichada(tipo)
        query = query.filter(RRHHFichada.tipo == tipo)
    if origen:
        valores_origen = [e.value for e in OrigenFichada]
        if origen not in valores_origen:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Origen inválido. Opciones: {', '.join(valores_origen)}",
            )
        query = query.filter(RRHHFichada.origen == origen)

    total = query.count()
    offset = (page - 1) * page_size
    fichadas = query.order_by(RRHHFichada.timestamp.desc()).offset(offset).limit(page_size).all()

    items = []
    for f in fichadas:
        emp = f.empleado
        items.append(
            FichadaResponse(
                id=f.id,
                empleado_id=f.empleado_id,
                empleado_nombre=f"{emp.apellido}, {emp.nombre}" if emp else "",
                empleado_legajo=emp.legajo if emp else "",
                timestamp=f.timestamp,
                tipo=f.tipo,
                origen=f.origen,
                device_serial=f.device_serial,
                event_id=f.event_id,
                registrado_por_nombre=(f.registrado_por.nombre if f.registrado_por else ""),
                motivo_manual=f.motivo_manual,
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
    """Elimina una fichada. Solo se pueden eliminar fichadas manuales."""
    _check_permiso(db, current_user, "rrhh.gestionar")

    fichada = db.query(RRHHFichada).filter(RRHHFichada.id == fichada_id).first()
    if not fichada:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Fichada {fichada_id} no encontrada",
        )

    if fichada.origen != OrigenFichada.MANUAL.value:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Solo se pueden eliminar fichadas manuales. Las fichadas de Hikvision no se eliminan.",
        )

    db.delete(fichada)
    db.commit()


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
