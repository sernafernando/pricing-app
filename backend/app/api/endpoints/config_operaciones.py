"""
Config Operaciones — endpoints para gestión de operadores, config de tabs,
registro de actividad y costos de envío por logística/cordón.

Agrupa todo lo necesario para la página /config-operaciones del frontend:
- Operadores CRUD (PIN 4 dígitos, micro-usuarios de depósito)
- Config tabs (qué páginas/tabs requieren PIN y con qué timeout)
- Actividad log (trazabilidad de acciones de operadores)
- Costos envío por logística × cordón (con historial de precios)
"""

from datetime import date, datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, and_
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.api.deps import get_current_user
from app.models.usuario import Usuario
from app.models.operador import Operador
from app.models.operador_config_tab import OperadorConfigTab
from app.models.operador_actividad import OperadorActividad
from app.models.logistica_costo_cordon import LogisticaCostoCordon
from app.models.logistica import Logistica

router = APIRouter()


# ══════════════════════════════════════════════════════════════════════
# Schemas
# ══════════════════════════════════════════════════════════════════════


# ── Operadores ────────────────────────────────────────────────────────


class OperadorResponse(BaseModel):
    """Operador de depósito."""

    id: int
    pin: str
    nombre: str
    activo: bool
    created_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class OperadorCreate(BaseModel):
    """Payload para crear operador."""

    pin: str = Field(
        min_length=4,
        max_length=4,
        pattern=r"^\d{4}$",
        description="PIN de 4 dígitos",
    )
    nombre: str = Field(min_length=1, max_length=100)


class OperadorUpdate(BaseModel):
    """Payload para actualizar operador."""

    nombre: Optional[str] = Field(None, min_length=1, max_length=100)
    pin: Optional[str] = Field(
        None,
        min_length=4,
        max_length=4,
        pattern=r"^\d{4}$",
        description="PIN de 4 dígitos",
    )
    activo: Optional[bool] = None


class ValidarPinRequest(BaseModel):
    """Payload para validar PIN de operador."""

    pin: str = Field(
        min_length=4,
        max_length=4,
        pattern=r"^\d{4}$",
    )


class ValidarPinResponse(BaseModel):
    """Resultado de validación de PIN."""

    ok: bool
    operador_id: Optional[int] = None
    nombre: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


# ── Config Tabs ───────────────────────────────────────────────────────


class ConfigTabResponse(BaseModel):
    """Config de tab que requiere PIN."""

    id: int
    tab_key: str
    page_path: str
    label: str
    timeout_minutos: int
    activo: bool
    created_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class ConfigTabCreate(BaseModel):
    """Payload para crear config de tab."""

    tab_key: str = Field(min_length=1, max_length=50)
    page_path: str = Field(min_length=1, max_length=100)
    label: str = Field(min_length=1, max_length=100)
    timeout_minutos: int = Field(default=15, ge=1, le=480)


class ConfigTabUpdate(BaseModel):
    """Payload para actualizar config de tab."""

    label: Optional[str] = Field(None, min_length=1, max_length=100)
    timeout_minutos: Optional[int] = Field(None, ge=1, le=480)
    activo: Optional[bool] = None


# ── Actividad ─────────────────────────────────────────────────────────


class ActividadCreate(BaseModel):
    """Payload para registrar actividad de operador."""

    operador_id: int
    tab_key: str = Field(min_length=1, max_length=50)
    accion: str = Field(min_length=1, max_length=100)
    detalle: Optional[dict] = None


class ActividadResponse(BaseModel):
    """Registro de actividad de operador."""

    id: int
    operador_id: int
    operador_nombre: Optional[str] = None
    usuario_id: int
    tab_key: str
    accion: str
    detalle: Optional[dict] = None
    created_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


# ── Costos Envío ──────────────────────────────────────────────────────


class CostoCordonResponse(BaseModel):
    """Costo de envío por logística × cordón."""

    id: int
    logistica_id: int
    logistica_nombre: Optional[str] = None
    cordon: str
    costo: float
    vigente_desde: date
    created_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class CostoCordonCreate(BaseModel):
    """Payload para crear/actualizar costo de envío."""

    logistica_id: int
    cordon: str = Field(min_length=1, max_length=20)
    costo: float = Field(ge=0)
    vigente_desde: date


# ══════════════════════════════════════════════════════════════════════
# Endpoints — Operadores
# ══════════════════════════════════════════════════════════════════════


@router.get(
    "/config-operaciones/operadores",
    response_model=List[OperadorResponse],
    summary="Listar operadores",
)
def listar_operadores(
    incluir_inactivos: bool = Query(False, description="Incluir operadores inactivos"),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> List[OperadorResponse]:
    """Lista todos los operadores del depósito. Por defecto solo los activos."""
    query = db.query(Operador)

    if not incluir_inactivos:
        query = query.filter(Operador.activo.is_(True))

    query = query.order_by(Operador.nombre)
    return query.all()


@router.post(
    "/config-operaciones/operadores",
    response_model=OperadorResponse,
    status_code=201,
    summary="Crear operador",
)
def crear_operador(
    payload: OperadorCreate,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> OperadorResponse:
    """
    Crea un nuevo operador de depósito.
    El PIN debe ser único y de exactamente 4 dígitos.
    """
    # Verificar PIN único
    existente = db.query(Operador).filter(Operador.pin == payload.pin).first()
    if existente:
        raise HTTPException(
            status_code=400,
            detail=f"Ya existe un operador con el PIN {payload.pin}",
        )

    # Verificar nombre único
    existente_nombre = (
        db.query(Operador).filter(Operador.nombre == payload.nombre).first()
    )
    if existente_nombre:
        raise HTTPException(
            status_code=400,
            detail=f"Ya existe un operador con el nombre '{payload.nombre}'",
        )

    operador = Operador(
        pin=payload.pin,
        nombre=payload.nombre,
    )
    db.add(operador)
    db.commit()
    db.refresh(operador)

    return operador


@router.put(
    "/config-operaciones/operadores/{operador_id}",
    response_model=OperadorResponse,
    summary="Actualizar operador",
)
def actualizar_operador(
    operador_id: int,
    payload: OperadorUpdate,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> OperadorResponse:
    """Actualiza nombre, PIN o estado activo de un operador."""
    operador = db.query(Operador).filter(Operador.id == operador_id).first()
    if not operador:
        raise HTTPException(404, "Operador no encontrado")

    if payload.pin is not None:
        existente = (
            db.query(Operador)
            .filter(Operador.pin == payload.pin, Operador.id != operador_id)
            .first()
        )
        if existente:
            raise HTTPException(400, f"Ya existe un operador con el PIN {payload.pin}")
        operador.pin = payload.pin

    if payload.nombre is not None:
        existente_nombre = (
            db.query(Operador)
            .filter(Operador.nombre == payload.nombre, Operador.id != operador_id)
            .first()
        )
        if existente_nombre:
            raise HTTPException(
                400,
                f"Ya existe un operador con el nombre '{payload.nombre}'",
            )
        operador.nombre = payload.nombre

    if payload.activo is not None:
        operador.activo = payload.activo

    db.commit()
    db.refresh(operador)

    return operador


@router.delete(
    "/config-operaciones/operadores/{operador_id}",
    response_model=OperadorResponse,
    summary="Desactivar operador (soft delete)",
)
def desactivar_operador(
    operador_id: int,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> OperadorResponse:
    """Soft delete: marca el operador como inactivo."""
    operador = db.query(Operador).filter(Operador.id == operador_id).first()
    if not operador:
        raise HTTPException(404, "Operador no encontrado")

    operador.activo = False
    db.commit()
    db.refresh(operador)

    return operador


@router.post(
    "/config-operaciones/operadores/validar-pin",
    response_model=ValidarPinResponse,
    summary="Validar PIN de operador",
)
def validar_pin(
    payload: ValidarPinRequest,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> ValidarPinResponse:
    """
    Valida un PIN de operador. Usado por el componente PinLock del frontend.
    Solo busca entre operadores activos.
    """
    operador = (
        db.query(Operador)
        .filter(Operador.pin == payload.pin, Operador.activo.is_(True))
        .first()
    )

    if not operador:
        return ValidarPinResponse(ok=False)

    return ValidarPinResponse(
        ok=True,
        operador_id=operador.id,
        nombre=operador.nombre,
    )


# ══════════════════════════════════════════════════════════════════════
# Endpoints — Config Tabs
# ══════════════════════════════════════════════════════════════════════


@router.get(
    "/config-operaciones/tabs",
    response_model=List[ConfigTabResponse],
    summary="Listar config de tabs",
)
def listar_config_tabs(
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> List[ConfigTabResponse]:
    """Lista todas las configuraciones de tabs que requieren PIN."""
    return (
        db.query(OperadorConfigTab)
        .order_by(OperadorConfigTab.page_path, OperadorConfigTab.tab_key)
        .all()
    )


@router.post(
    "/config-operaciones/tabs",
    response_model=ConfigTabResponse,
    status_code=201,
    summary="Crear config de tab",
)
def crear_config_tab(
    payload: ConfigTabCreate,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> ConfigTabResponse:
    """
    Crea una nueva configuración de tab que requerirá PIN de operador.
    La combinación tab_key + page_path debe ser única.
    """
    existente = (
        db.query(OperadorConfigTab)
        .filter(
            OperadorConfigTab.tab_key == payload.tab_key,
            OperadorConfigTab.page_path == payload.page_path,
        )
        .first()
    )
    if existente:
        raise HTTPException(
            400,
            f"Ya existe config para tab '{payload.tab_key}' en '{payload.page_path}'",
        )

    config = OperadorConfigTab(
        tab_key=payload.tab_key,
        page_path=payload.page_path,
        label=payload.label,
        timeout_minutos=payload.timeout_minutos,
    )
    db.add(config)
    db.commit()
    db.refresh(config)

    return config


@router.put(
    "/config-operaciones/tabs/{tab_id}",
    response_model=ConfigTabResponse,
    summary="Actualizar config de tab",
)
def actualizar_config_tab(
    tab_id: int,
    payload: ConfigTabUpdate,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> ConfigTabResponse:
    """Actualiza label, timeout o estado activo de una config de tab."""
    config = db.query(OperadorConfigTab).filter(OperadorConfigTab.id == tab_id).first()
    if not config:
        raise HTTPException(404, "Config de tab no encontrada")

    if payload.label is not None:
        config.label = payload.label

    if payload.timeout_minutos is not None:
        config.timeout_minutos = payload.timeout_minutos

    if payload.activo is not None:
        config.activo = payload.activo

    db.commit()
    db.refresh(config)

    return config


@router.delete(
    "/config-operaciones/tabs/{tab_id}",
    response_model=dict,
    summary="Eliminar config de tab",
)
def eliminar_config_tab(
    tab_id: int,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> dict:
    """Elimina una config de tab (hard delete — ya no pedirá PIN en ese tab)."""
    config = db.query(OperadorConfigTab).filter(OperadorConfigTab.id == tab_id).first()
    if not config:
        raise HTTPException(404, "Config de tab no encontrada")

    db.delete(config)
    db.commit()

    return {"ok": True, "deleted_id": tab_id}


# ══════════════════════════════════════════════════════════════════════
# Endpoints — Actividad
# ══════════════════════════════════════════════════════════════════════


@router.post(
    "/config-operaciones/actividad",
    response_model=ActividadResponse,
    status_code=201,
    summary="Registrar actividad de operador",
)
def registrar_actividad(
    payload: ActividadCreate,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> ActividadResponse:
    """
    Registra una acción realizada por un operador identificado con PIN.
    El usuario_id se toma del usuario del sistema logueado (sesión JWT).
    """
    # Verificar que el operador existe y está activo
    operador = (
        db.query(Operador)
        .filter(Operador.id == payload.operador_id, Operador.activo.is_(True))
        .first()
    )
    if not operador:
        raise HTTPException(404, "Operador no encontrado o inactivo")

    actividad = OperadorActividad(
        operador_id=payload.operador_id,
        usuario_id=current_user.id,
        tab_key=payload.tab_key,
        accion=payload.accion,
        detalle=payload.detalle,
    )
    db.add(actividad)
    db.commit()
    db.refresh(actividad)

    return ActividadResponse(
        id=actividad.id,
        operador_id=actividad.operador_id,
        operador_nombre=operador.nombre,
        usuario_id=actividad.usuario_id,
        tab_key=actividad.tab_key,
        accion=actividad.accion,
        detalle=actividad.detalle,
        created_at=actividad.created_at,
    )


@router.get(
    "/config-operaciones/actividad",
    response_model=List[ActividadResponse],
    summary="Listar actividad de operadores",
)
def listar_actividad(
    operador_id: Optional[int] = Query(None, description="Filtrar por operador"),
    tab_key: Optional[str] = Query(None, description="Filtrar por tab"),
    accion: Optional[str] = Query(None, description="Filtrar por acción"),
    fecha: Optional[date] = Query(None, description="Filtrar por fecha (día)"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> List[ActividadResponse]:
    """
    Lista actividad reciente de operadores con filtros opcionales.
    Paginada, ordenada por más reciente primero.
    """
    query = db.query(OperadorActividad)

    if operador_id is not None:
        query = query.filter(OperadorActividad.operador_id == operador_id)

    if tab_key:
        query = query.filter(OperadorActividad.tab_key == tab_key)

    if accion:
        query = query.filter(OperadorActividad.accion == accion)

    if fecha:
        query = query.filter(func.date(OperadorActividad.created_at) == fecha)

    query = query.order_by(OperadorActividad.created_at.desc())

    offset = (page - 1) * page_size
    rows = query.offset(offset).limit(page_size).all()

    return [
        ActividadResponse(
            id=row.id,
            operador_id=row.operador_id,
            operador_nombre=row.operador.nombre if row.operador else None,
            usuario_id=row.usuario_id,
            tab_key=row.tab_key,
            accion=row.accion,
            detalle=row.detalle,
            created_at=row.created_at,
        )
        for row in rows
    ]


# ══════════════════════════════════════════════════════════════════════
# Endpoints — Costos Envío
# ══════════════════════════════════════════════════════════════════════


@router.get(
    "/config-operaciones/costos",
    response_model=List[CostoCordonResponse],
    summary="Listar costos vigentes por logística × cordón",
)
def listar_costos_vigentes(
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> List[CostoCordonResponse]:
    """
    Devuelve el costo vigente más reciente por cada combinación
    (logistica_id, cordon) donde vigente_desde <= hoy.

    El frontend construye una matriz logística × cordón con estos datos.
    """
    hoy = date.today()

    # Subquery: max vigente_desde por (logistica_id, cordon) donde <= hoy
    max_fecha_sub = (
        db.query(
            LogisticaCostoCordon.logistica_id,
            LogisticaCostoCordon.cordon,
            func.max(LogisticaCostoCordon.vigente_desde).label("max_fecha"),
        )
        .filter(LogisticaCostoCordon.vigente_desde <= hoy)
        .group_by(
            LogisticaCostoCordon.logistica_id,
            LogisticaCostoCordon.cordon,
        )
        .subquery()
    )

    # Join para obtener el registro completo
    rows = (
        db.query(
            LogisticaCostoCordon.id,
            LogisticaCostoCordon.logistica_id,
            Logistica.nombre.label("logistica_nombre"),
            LogisticaCostoCordon.cordon,
            LogisticaCostoCordon.costo,
            LogisticaCostoCordon.vigente_desde,
            LogisticaCostoCordon.created_at,
        )
        .join(
            max_fecha_sub,
            and_(
                LogisticaCostoCordon.logistica_id == max_fecha_sub.c.logistica_id,
                LogisticaCostoCordon.cordon == max_fecha_sub.c.cordon,
                LogisticaCostoCordon.vigente_desde == max_fecha_sub.c.max_fecha,
            ),
        )
        .outerjoin(Logistica, LogisticaCostoCordon.logistica_id == Logistica.id)
        .order_by(Logistica.nombre, LogisticaCostoCordon.cordon)
        .all()
    )

    return [
        CostoCordonResponse(
            id=row.id,
            logistica_id=row.logistica_id,
            logistica_nombre=row.logistica_nombre,
            cordon=row.cordon,
            costo=float(row.costo),
            vigente_desde=row.vigente_desde,
            created_at=row.created_at,
        )
        for row in rows
    ]


@router.post(
    "/config-operaciones/costos",
    response_model=CostoCordonResponse,
    status_code=201,
    summary="Crear/actualizar costo de envío",
)
def crear_costo(
    payload: CostoCordonCreate,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> CostoCordonResponse:
    """
    Crea un nuevo registro de costo para logística × cordón con fecha de vigencia.
    Los registros anteriores se mantienen como historial — el query vigente
    siempre toma el más reciente con vigente_desde <= hoy.
    """
    # Verificar que la logística existe
    logistica = db.query(Logistica).filter(Logistica.id == payload.logistica_id).first()
    if not logistica:
        raise HTTPException(404, "Logística no encontrada")

    # Validar cordon
    cordones_validos = {"CABA", "Cordon 1", "Cordon 2", "Cordon 3"}
    if payload.cordon not in cordones_validos:
        raise HTTPException(
            400,
            f"Cordón inválido. Valores permitidos: {', '.join(sorted(cordones_validos))}",
        )

    costo = LogisticaCostoCordon(
        logistica_id=payload.logistica_id,
        cordon=payload.cordon,
        costo=payload.costo,
        vigente_desde=payload.vigente_desde,
    )
    db.add(costo)
    db.commit()
    db.refresh(costo)

    return CostoCordonResponse(
        id=costo.id,
        logistica_id=costo.logistica_id,
        logistica_nombre=logistica.nombre,
        cordon=costo.cordon,
        costo=float(costo.costo),
        vigente_desde=costo.vigente_desde,
        created_at=costo.created_at,
    )


@router.get(
    "/config-operaciones/costos/historial",
    response_model=List[CostoCordonResponse],
    summary="Historial de costos de envío",
)
def historial_costos(
    logistica_id: Optional[int] = Query(None, description="Filtrar por logística"),
    cordon: Optional[str] = Query(None, description="Filtrar por cordón"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> List[CostoCordonResponse]:
    """
    Historial completo de costos de envío con filtros opcionales.
    Incluye precios pasados y futuros (programados).
    """
    query = db.query(
        LogisticaCostoCordon.id,
        LogisticaCostoCordon.logistica_id,
        Logistica.nombre.label("logistica_nombre"),
        LogisticaCostoCordon.cordon,
        LogisticaCostoCordon.costo,
        LogisticaCostoCordon.vigente_desde,
        LogisticaCostoCordon.created_at,
    ).outerjoin(Logistica, LogisticaCostoCordon.logistica_id == Logistica.id)

    if logistica_id is not None:
        query = query.filter(LogisticaCostoCordon.logistica_id == logistica_id)

    if cordon:
        query = query.filter(LogisticaCostoCordon.cordon == cordon)

    query = query.order_by(
        LogisticaCostoCordon.vigente_desde.desc(),
        Logistica.nombre,
        LogisticaCostoCordon.cordon,
    )

    offset = (page - 1) * page_size
    rows = query.offset(offset).limit(page_size).all()

    return [
        CostoCordonResponse(
            id=row.id,
            logistica_id=row.logistica_id,
            logistica_nombre=row.logistica_nombre,
            cordon=row.cordon,
            costo=float(row.costo),
            vigente_desde=row.vigente_desde,
            created_at=row.created_at,
        )
        for row in rows
    ]
