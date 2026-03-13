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
from datetime import date, datetime, time
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


class EmpleadoPresentismoRow(BaseModel):
    """Una fila de empleado en la grilla de presentismo."""

    empleado_id: int
    legajo: str
    nombre_completo: str
    area: Optional[str] = None
    dias: dict[str, Optional[str]]  # { "2026-03-01": "presente", ... }


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
    Grilla de presentismo: todos los empleados activos para un rango de fechas.

    Devuelve una estructura de grilla donde cada empleado tiene un dict
    de fechas → estado. Las fechas sin marcación aparecen como null.
    """
    svc = PermisosService(db)
    if not svc.tiene_permiso(current_user, "rrhh.ver"):
        raise HTTPException(status_code=403, detail="Sin permiso: rrhh.ver")

    if fecha_desde > fecha_hasta:
        raise HTTPException(
            status_code=400,
            detail="fecha_desde no puede ser posterior a fecha_hasta",
        )

    # Limitar rango a 62 días (2 meses) para evitar queries enormes
    delta = (fecha_hasta - fecha_desde).days
    if delta > 62:
        raise HTTPException(
            status_code=400,
            detail="El rango máximo es de 62 días",
        )

    # Empleados activos
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

    # Marcaciones del rango
    marcaciones = (
        db.query(RRHHPresentismoDiario)
        .filter(
            RRHHPresentismoDiario.empleado_id.in_(emp_ids),
            RRHHPresentismoDiario.fecha >= fecha_desde,
            RRHHPresentismoDiario.fecha <= fecha_hasta,
        )
        .all()
    )

    # Indexar por (empleado_id, fecha_str)
    marc_map: dict[tuple[int, str], str] = {}
    for m in marcaciones:
        marc_map[(m.empleado_id, m.fecha.isoformat())] = m.estado

    # Generar lista de fechas
    from datetime import timedelta

    fechas: list[str] = []
    current = fecha_desde
    while current <= fecha_hasta:
        fechas.append(current.isoformat())
        current += timedelta(days=1)

    # Armar grilla
    rows: list[EmpleadoPresentismoRow] = []
    for emp in empleados:
        dias: dict[str, Optional[str]] = {}
        for f in fechas:
            dias[f] = marc_map.get((emp.id, f))
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
