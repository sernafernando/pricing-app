"""
Router de fichaje mobile — self-service clock-in/out vía PWA.

Permite a cualquier usuario autenticado con un empleado RRHH vinculado
registrar su propia fichada de entrada/salida desde el celular.

GPS es informativo (nunca bloquea). Se calcula distancia a oficina más cercana
via haversine si hay coordenadas y oficinas configuradas.

Endpoints:
- GET  /rrhh/fichaje-mobile/estado   — estado actual del empleado (sugerencia entrada/salida)
- POST /rrhh/fichaje-mobile/fichar   — registrar fichada mobile
- CRUD /rrhh/ubicaciones-oficina     — ABM de sedes/oficinas (requiere rrhh.config)
"""

import math
from datetime import datetime, time, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import get_current_user
from app.models.rrhh_empleado import RRHHEmpleado
from app.models.rrhh_fichada import OrigenFichada, RRHHFichada, TipoFichada
from app.models.rrhh_ubicacion_oficina import RRHHUbicacionOficina
from app.models.usuario import Usuario
from app.services.permisos_service import PermisosService

router = APIRouter(prefix="/rrhh", tags=["rrhh-fichaje-mobile"])

# Argentina timezone (UTC-3)
ART_TZ = timezone(timedelta(hours=-3))

# Proximity dedup window — same as Hikvision (120 seconds)
PROXIMITY_DEDUP_SECONDS = 120


# ──────────────────────────────────────────────
# SCHEMAS — Fichaje Mobile
# ──────────────────────────────────────────────


class FichadaMobileCreate(BaseModel):
    """Datos para registrar una fichada desde el celular."""

    latitud: Optional[float] = Field(None, ge=-90, le=90, description="GPS latitude")
    longitud: Optional[float] = Field(None, ge=-180, le=180, description="GPS longitude")
    accuracy_metros: Optional[float] = Field(None, ge=0, description="GPS accuracy in meters")


class UltimaFichadaInfo(BaseModel):
    """Info resumida de la última fichada del día."""

    id: int
    tipo: str
    timestamp: datetime
    origen: str

    model_config = ConfigDict(from_attributes=True)


class FichajeMobileEstado(BaseModel):
    """Estado actual del empleado para el fichaje mobile."""

    empleado_id: int
    empleado_nombre: str
    sugerencia: str  # "entrada" or "salida"
    ultima_fichada: Optional[UltimaFichadaInfo] = None
    fichadas_hoy: int


class FichadaMobileResponse(BaseModel):
    """Respuesta tras registrar una fichada mobile."""

    id: int
    empleado_id: int
    empleado_nombre: str
    timestamp: datetime
    tipo: str
    origen: str
    latitud: Optional[float] = None
    longitud: Optional[float] = None
    accuracy_metros: Optional[float] = None
    distancia_oficina_metros: Optional[float] = None
    created_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


# ──────────────────────────────────────────────
# SCHEMAS — Ubicaciones Oficina
# ──────────────────────────────────────────────


class UbicacionOficinaResponse(BaseModel):
    """Sede/oficina de la empresa."""

    id: int
    nombre: str
    latitud: float
    longitud: float
    radio_metros: float
    activo: bool
    created_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class UbicacionOficinaCreate(BaseModel):
    """Datos para crear una sede/oficina."""

    nombre: str = Field(min_length=1, max_length=100)
    latitud: float = Field(ge=-90, le=90)
    longitud: float = Field(ge=-180, le=180)
    radio_metros: float = Field(default=100.0, gt=0)


class UbicacionOficinaUpdate(BaseModel):
    """Datos para actualizar una sede/oficina."""

    nombre: Optional[str] = Field(None, min_length=1, max_length=100)
    latitud: Optional[float] = Field(None, ge=-90, le=90)
    longitud: Optional[float] = Field(None, ge=-180, le=180)
    radio_metros: Optional[float] = Field(None, gt=0)
    activo: Optional[bool] = None


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


def _resolve_empleado(db: Session, user: Usuario) -> RRHHEmpleado:
    """Resuelve el empleado vinculado al usuario actual.

    Raises:
        HTTPException 404: si el usuario no tiene empleado vinculado.
        HTTPException 403: si el empleado no está activo.
    """
    empleado = db.query(RRHHEmpleado).filter(RRHHEmpleado.usuario_id == user.id).first()
    if not empleado:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Tu usuario no tiene un empleado vinculado. Contactá a RRHH.",
        )
    if empleado.estado != "activo":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Tu legajo no está activo. Contactá a RRHH.",
        )
    return empleado


def _get_hoy_rango() -> tuple[datetime, datetime]:
    """Retorna (inicio_del_dia, fin_del_dia) en Argentina timezone como UTC."""
    ahora_art = datetime.now(ART_TZ)
    inicio_dia = datetime.combine(ahora_art.date(), time.min, tzinfo=ART_TZ)
    fin_dia = datetime.combine(ahora_art.date(), time(23, 59, 59), tzinfo=ART_TZ)
    return inicio_dia, fin_dia


def _get_ultima_fichada_hoy(db: Session, empleado_id: int) -> Optional[RRHHFichada]:
    """Obtiene la última fichada del día actual para el empleado."""
    inicio_dia, fin_dia = _get_hoy_rango()
    return (
        db.query(RRHHFichada)
        .filter(
            RRHHFichada.empleado_id == empleado_id,
            RRHHFichada.timestamp >= inicio_dia,
            RRHHFichada.timestamp <= fin_dia,
        )
        .order_by(RRHHFichada.timestamp.desc())
        .first()
    )


def _contar_fichadas_hoy(db: Session, empleado_id: int) -> int:
    """Cuenta las fichadas del día actual para el empleado."""
    inicio_dia, fin_dia = _get_hoy_rango()
    return (
        db.query(RRHHFichada)
        .filter(
            RRHHFichada.empleado_id == empleado_id,
            RRHHFichada.timestamp >= inicio_dia,
            RRHHFichada.timestamp <= fin_dia,
        )
        .count()
    )


def _check_proximity_dedup(db: Session, empleado_id: int, window_seconds: int = PROXIMITY_DEDUP_SECONDS) -> None:
    """Verifica que no exista una fichada reciente (proximity dedup).

    Raises:
        HTTPException 409: si hay una fichada dentro de la ventana.
    """
    ahora = datetime.now(timezone.utc)
    limite = ahora - timedelta(seconds=window_seconds)
    recent = (
        db.query(RRHHFichada)
        .filter(
            RRHHFichada.empleado_id == empleado_id,
            RRHHFichada.timestamp >= limite,
        )
        .first()
    )
    if recent:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Ya registraste una fichada hace menos de 2 minutos. Esperá un momento.",
        )


def haversine_meters(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Calcula la distancia en metros entre dos puntos geográficos (fórmula de haversine)."""
    r = 6_371_000  # Radio de la Tierra en metros
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    return r * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _compute_distance_to_nearest_office(db: Session, lat: float, lon: float) -> Optional[float]:
    """Calcula la distancia en metros a la oficina activa más cercana.

    Returns None si no hay oficinas activas configuradas.
    """
    oficinas = db.query(RRHHUbicacionOficina).filter(RRHHUbicacionOficina.activo.is_(True)).all()
    if not oficinas:
        return None

    distancias = [haversine_meters(lat, lon, float(o.latitud), float(o.longitud)) for o in oficinas]
    return round(min(distancias), 1)


def _sugerencia_tipo(ultima: Optional[RRHHFichada]) -> str:
    """Sugiere el próximo tipo de fichada basado en la última del día."""
    if ultima is None:
        return TipoFichada.ENTRADA.value
    if ultima.tipo == TipoFichada.ENTRADA.value:
        return TipoFichada.SALIDA.value
    return TipoFichada.ENTRADA.value


# ──────────────────────────────────────────────
# ENDPOINTS — Fichaje Mobile
# ──────────────────────────────────────────────


@router.get(
    "/fichaje-mobile/estado",
    response_model=FichajeMobileEstado,
    summary="Estado actual del fichaje para el empleado autenticado",
)
def get_estado_fichaje(
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> FichajeMobileEstado:
    """Retorna el estado actual del fichaje del empleado autenticado.

    Incluye: nombre del empleado, sugerencia de tipo (entrada/salida),
    última fichada del día, y cantidad de fichadas hoy.
    No requiere permiso especial — solo JWT + empleado vinculado.
    """
    empleado = _resolve_empleado(db, current_user)
    ultima = _get_ultima_fichada_hoy(db, empleado.id)
    fichadas_hoy = _contar_fichadas_hoy(db, empleado.id)

    ultima_info = None
    if ultima:
        ultima_info = UltimaFichadaInfo(
            id=ultima.id,
            tipo=ultima.tipo,
            timestamp=ultima.timestamp,
            origen=ultima.origen,
        )

    return FichajeMobileEstado(
        empleado_id=empleado.id,
        empleado_nombre=f"{empleado.apellido}, {empleado.nombre}",
        sugerencia=_sugerencia_tipo(ultima),
        ultima_fichada=ultima_info,
        fichadas_hoy=fichadas_hoy,
    )


@router.post(
    "/fichaje-mobile/fichar",
    response_model=FichadaMobileResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Registrar fichada mobile (entrada/salida)",
)
def registrar_fichada_mobile(
    data: FichadaMobileCreate,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> FichadaMobileResponse:
    """Registra una fichada de entrada o salida desde el celular.

    El tipo (entrada/salida) se determina automáticamente según la última
    fichada del día: si la última fue entrada → salida, y viceversa.
    Si no hay fichadas hoy → entrada.

    GPS es informativo: latitud/longitud/accuracy son opcionales y nunca
    bloquean el fichaje. Si se proporcionan coordenadas y hay oficinas
    configuradas, se calcula la distancia a la más cercana.

    Proximity dedup: rechaza si hay una fichada del mismo empleado en los
    últimos 120 segundos (mismo mecanismo que Hikvision).

    No requiere permiso especial — solo JWT + empleado vinculado activo.
    """
    empleado = _resolve_empleado(db, current_user)
    _check_proximity_dedup(db, empleado.id)

    # Auto-detect tipo
    ultima = _get_ultima_fichada_hoy(db, empleado.id)
    tipo = _sugerencia_tipo(ultima)

    # Distance to nearest office
    distancia: Optional[float] = None
    if data.latitud is not None and data.longitud is not None:
        distancia = _compute_distance_to_nearest_office(db, data.latitud, data.longitud)

    ahora = datetime.now(timezone.utc)

    fichada = RRHHFichada(
        empleado_id=empleado.id,
        timestamp=ahora,
        tipo=tipo,
        origen=OrigenFichada.MOBILE.value,
        latitud=data.latitud,
        longitud=data.longitud,
        accuracy_metros=data.accuracy_metros,
        distancia_oficina_metros=distancia,
    )
    db.add(fichada)
    db.commit()
    db.refresh(fichada)

    return FichadaMobileResponse(
        id=fichada.id,
        empleado_id=fichada.empleado_id,
        empleado_nombre=f"{empleado.apellido}, {empleado.nombre}",
        timestamp=fichada.timestamp,
        tipo=fichada.tipo,
        origen=fichada.origen,
        latitud=float(fichada.latitud) if fichada.latitud is not None else None,
        longitud=float(fichada.longitud) if fichada.longitud is not None else None,
        accuracy_metros=fichada.accuracy_metros,
        distancia_oficina_metros=fichada.distancia_oficina_metros,
        created_at=fichada.created_at,
    )


# ──────────────────────────────────────────────
# ENDPOINTS — Ubicaciones Oficina (CRUD)
# ──────────────────────────────────────────────


@router.get(
    "/ubicaciones-oficina",
    response_model=list[UbicacionOficinaResponse],
    summary="Listar sedes/oficinas",
)
def listar_ubicaciones_oficina(
    solo_activas: bool = True,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> list[UbicacionOficinaResponse]:
    """Lista las sedes/oficinas configuradas. Por defecto solo las activas.

    Requiere permiso rrhh.ver.
    """
    _check_permiso(db, current_user, "rrhh.ver")

    query = db.query(RRHHUbicacionOficina)
    if solo_activas:
        query = query.filter(RRHHUbicacionOficina.activo.is_(True))

    oficinas = query.order_by(RRHHUbicacionOficina.nombre).all()

    return [
        UbicacionOficinaResponse(
            id=o.id,
            nombre=o.nombre,
            latitud=float(o.latitud),
            longitud=float(o.longitud),
            radio_metros=o.radio_metros,
            activo=o.activo,
            created_at=o.created_at,
        )
        for o in oficinas
    ]


@router.post(
    "/ubicaciones-oficina",
    response_model=UbicacionOficinaResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Crear sede/oficina",
)
def crear_ubicacion_oficina(
    data: UbicacionOficinaCreate,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> UbicacionOficinaResponse:
    """Crea una nueva sede/oficina como referencia para cálculo de distancia.

    Requiere permiso rrhh.config.
    """
    _check_permiso(db, current_user, "rrhh.config")

    oficina = RRHHUbicacionOficina(
        nombre=data.nombre,
        latitud=data.latitud,
        longitud=data.longitud,
        radio_metros=data.radio_metros,
    )
    db.add(oficina)
    db.commit()
    db.refresh(oficina)

    return UbicacionOficinaResponse(
        id=oficina.id,
        nombre=oficina.nombre,
        latitud=float(oficina.latitud),
        longitud=float(oficina.longitud),
        radio_metros=oficina.radio_metros,
        activo=oficina.activo,
        created_at=oficina.created_at,
    )


@router.patch(
    "/ubicaciones-oficina/{oficina_id}",
    response_model=UbicacionOficinaResponse,
    summary="Actualizar sede/oficina",
)
def actualizar_ubicacion_oficina(
    oficina_id: int,
    data: UbicacionOficinaUpdate,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> UbicacionOficinaResponse:
    """Actualiza una sede/oficina existente.

    Requiere permiso rrhh.config.
    """
    _check_permiso(db, current_user, "rrhh.config")

    oficina = db.query(RRHHUbicacionOficina).filter(RRHHUbicacionOficina.id == oficina_id).first()
    if not oficina:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Oficina {oficina_id} no encontrada",
        )

    if data.nombre is not None:
        oficina.nombre = data.nombre
    if data.latitud is not None:
        oficina.latitud = data.latitud
    if data.longitud is not None:
        oficina.longitud = data.longitud
    if data.radio_metros is not None:
        oficina.radio_metros = data.radio_metros
    if data.activo is not None:
        oficina.activo = data.activo

    db.commit()
    db.refresh(oficina)

    return UbicacionOficinaResponse(
        id=oficina.id,
        nombre=oficina.nombre,
        latitud=float(oficina.latitud),
        longitud=float(oficina.longitud),
        radio_metros=oficina.radio_metros,
        activo=oficina.activo,
        created_at=oficina.created_at,
    )


@router.delete(
    "/ubicaciones-oficina/{oficina_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Desactivar sede/oficina",
)
def eliminar_ubicacion_oficina(
    oficina_id: int,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> None:
    """Desactiva una sede/oficina (soft-delete).

    Requiere permiso rrhh.config.
    """
    _check_permiso(db, current_user, "rrhh.config")

    oficina = db.query(RRHHUbicacionOficina).filter(RRHHUbicacionOficina.id == oficina_id).first()
    if not oficina:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Oficina {oficina_id} no encontrada",
        )

    oficina.activo = False
    db.commit()
