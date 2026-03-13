"""
Router del módulo RRHH - Empleados y Legajos.

Endpoints:
- CRUD de empleados (crear, listar, obtener, actualizar, soft-delete)
- Upload/download/delete de documentos del legajo
- CRUD de tipos de documento (configuración)
- CRUD de campos custom del legajo (schema_legajo)
- Historial de cambios del legajo (auditoría)
"""

import os
import uuid
from datetime import date, datetime, UTC
from typing import Optional

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, or_
from sqlalchemy.orm import Session, selectinload

from app.core.config import settings
from app.core.database import get_db
from app.core.deps import get_current_user
from app.models.rrhh_documento import RRHHDocumento
from app.models.rrhh_empleado import EstadoEmpleado, RRHHEmpleado
from app.models.rrhh_legajo_historial import RRHHLegajoHistorial
from app.models.rrhh_schema_legajo import RRHHSchemaLegajo
from app.models.rrhh_tipo_documento import RRHHTipoDocumento
from app.models.usuario import Usuario
from app.services.permisos_service import PermisosService

router = APIRouter(prefix="/rrhh", tags=["rrhh"])


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


def _registrar_cambio(
    db: Session,
    empleado_id: int,
    campo: str,
    valor_anterior: Optional[str],
    valor_nuevo: Optional[str],
    usuario_id: int,
) -> None:
    """Registra un cambio en el historial del legajo."""
    historial = RRHHLegajoHistorial(
        empleado_id=empleado_id,
        campo=campo,
        valor_anterior=str(valor_anterior) if valor_anterior is not None else None,
        valor_nuevo=str(valor_nuevo) if valor_nuevo is not None else None,
        usuario_id=usuario_id,
    )
    db.add(historial)


# ──────────────────────────────────────────────
# SCHEMAS — Empleados
# ──────────────────────────────────────────────


class EmpleadoCreate(BaseModel):
    nombre: str = Field(min_length=1, max_length=100)
    apellido: str = Field(min_length=1, max_length=100)
    dni: str = Field(min_length=1, max_length=20)
    cuil: Optional[str] = Field(default=None, max_length=20)
    fecha_nacimiento: Optional[date] = None
    domicilio: Optional[str] = Field(default=None, max_length=500)
    telefono: Optional[str] = Field(default=None, max_length=50)
    email_personal: Optional[str] = Field(default=None, max_length=255)
    contacto_emergencia: Optional[str] = Field(default=None, max_length=255)
    contacto_emergencia_tel: Optional[str] = Field(default=None, max_length=50)
    legajo: str = Field(min_length=1, max_length=20)
    fecha_ingreso: date
    puesto: Optional[str] = Field(default=None, max_length=100)
    area: Optional[str] = Field(default=None, max_length=100)
    estado: str = Field(default="activo", max_length=20)
    usuario_id: Optional[int] = None
    datos_custom: Optional[dict] = None
    observaciones: Optional[str] = None
    hikvision_employee_no: Optional[str] = Field(default=None, max_length=20)


class EmpleadoUpdate(BaseModel):
    nombre: Optional[str] = Field(default=None, max_length=100)
    apellido: Optional[str] = Field(default=None, max_length=100)
    dni: Optional[str] = Field(default=None, max_length=20)
    cuil: Optional[str] = Field(default=None, max_length=20)
    fecha_nacimiento: Optional[date] = None
    domicilio: Optional[str] = Field(default=None, max_length=500)
    telefono: Optional[str] = Field(default=None, max_length=50)
    email_personal: Optional[str] = Field(default=None, max_length=255)
    contacto_emergencia: Optional[str] = Field(default=None, max_length=255)
    contacto_emergencia_tel: Optional[str] = Field(default=None, max_length=50)
    legajo: Optional[str] = Field(default=None, max_length=20)
    fecha_ingreso: Optional[date] = None
    fecha_egreso: Optional[date] = None
    puesto: Optional[str] = Field(default=None, max_length=100)
    area: Optional[str] = Field(default=None, max_length=100)
    estado: Optional[str] = Field(default=None, max_length=20)
    usuario_id: Optional[int] = None
    datos_custom: Optional[dict] = None
    observaciones: Optional[str] = None
    hikvision_employee_no: Optional[str] = Field(default=None, max_length=20)


class EmpleadoResponse(BaseModel):
    id: int
    nombre: str
    apellido: str
    dni: str
    cuil: Optional[str] = None
    fecha_nacimiento: Optional[date] = None
    domicilio: Optional[str] = None
    telefono: Optional[str] = None
    email_personal: Optional[str] = None
    contacto_emergencia: Optional[str] = None
    contacto_emergencia_tel: Optional[str] = None
    legajo: str
    fecha_ingreso: date
    fecha_egreso: Optional[date] = None
    puesto: Optional[str] = None
    area: Optional[str] = None
    estado: str
    usuario_id: Optional[int] = None
    hikvision_employee_no: Optional[str] = None
    foto_path: Optional[str] = None
    datos_custom: Optional[dict] = None
    observaciones: Optional[str] = None
    activo: bool
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class EmpleadoListResponse(BaseModel):
    items: list[EmpleadoResponse]
    total: int
    page: int
    page_size: int


# ──────────────────────────────────────────────
# SCHEMAS — Documentos
# ──────────────────────────────────────────────


class DocumentoResponse(BaseModel):
    id: int
    empleado_id: int
    tipo_documento_id: int
    tipo_documento_nombre: Optional[str] = None
    nombre_archivo: str
    mime_type: Optional[str] = None
    tamano_bytes: Optional[int] = None
    descripcion: Optional[str] = None
    fecha_vencimiento: Optional[date] = None
    numero_documento: Optional[str] = None
    subido_por_id: int
    subido_por_nombre: Optional[str] = None
    created_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


# ──────────────────────────────────────────────
# SCHEMAS — Tipos de documento
# ──────────────────────────────────────────────


class TipoDocumentoCreate(BaseModel):
    nombre: str = Field(min_length=1, max_length=100)
    descripcion: Optional[str] = Field(default=None, max_length=500)
    requiere_vencimiento: bool = False
    orden: int = 0


class TipoDocumentoUpdate(BaseModel):
    nombre: Optional[str] = Field(default=None, max_length=100)
    descripcion: Optional[str] = Field(default=None, max_length=500)
    requiere_vencimiento: Optional[bool] = None
    activo: Optional[bool] = None
    orden: Optional[int] = None


class TipoDocumentoResponse(BaseModel):
    id: int
    nombre: str
    descripcion: Optional[str] = None
    requiere_vencimiento: bool
    activo: bool
    orden: int
    created_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


# ──────────────────────────────────────────────
# SCHEMAS — Schema Legajo (campos custom)
# ──────────────────────────────────────────────


class SchemaLegajoCreate(BaseModel):
    nombre: str = Field(min_length=1, max_length=100)
    label: str = Field(min_length=1, max_length=200)
    tipo_campo: str = Field(min_length=1, max_length=50)
    requerido: bool = False
    opciones: Optional[list] = None
    orden: int = 0


class SchemaLegajoUpdate(BaseModel):
    label: Optional[str] = Field(default=None, max_length=200)
    tipo_campo: Optional[str] = Field(default=None, max_length=50)
    requerido: Optional[bool] = None
    opciones: Optional[list] = None
    activo: Optional[bool] = None
    orden: Optional[int] = None


class SchemaLegajoResponse(BaseModel):
    id: int
    nombre: str
    label: str
    tipo_campo: str
    requerido: bool
    opciones: Optional[list] = None
    orden: int
    activo: bool
    created_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


# ──────────────────────────────────────────────
# SCHEMAS — Historial
# ──────────────────────────────────────────────


class HistorialResponse(BaseModel):
    id: int
    empleado_id: int
    campo: str
    valor_anterior: Optional[str] = None
    valor_nuevo: Optional[str] = None
    usuario_id: int
    usuario_nombre: Optional[str] = None
    created_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


# ═══════════════════════════════════════════════
# ENDPOINTS — Empleados
# ═══════════════════════════════════════════════


@router.get("/empleados", response_model=EmpleadoListResponse)
def listar_empleados(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    search: Optional[str] = Query(default=None, max_length=200),
    estado: Optional[str] = Query(default=None, max_length=20),
    area: Optional[str] = Query(default=None, max_length=100),
    activo: Optional[bool] = None,
    current_user: Usuario = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> EmpleadoListResponse:
    """
    Lista empleados con paginación, búsqueda y filtros.
    Requiere autenticación. Permiso rrhh.ver para acceder.
    """
    svc = PermisosService(db)
    if not svc.tiene_permiso(current_user, "rrhh.ver"):
        raise HTTPException(status_code=403, detail="Sin permiso: rrhh.ver")

    query = db.query(RRHHEmpleado)

    # Filtros
    if activo is not None:
        query = query.filter(RRHHEmpleado.activo == activo)
    else:
        # Por defecto solo activos
        query = query.filter(RRHHEmpleado.activo.is_(True))

    if estado:
        query = query.filter(RRHHEmpleado.estado == estado)

    if area:
        query = query.filter(RRHHEmpleado.area == area)

    if search:
        term = f"%{search}%"
        query = query.filter(
            or_(
                RRHHEmpleado.nombre.ilike(term),
                RRHHEmpleado.apellido.ilike(term),
                RRHHEmpleado.dni.ilike(term),
                RRHHEmpleado.legajo.ilike(term),
                RRHHEmpleado.cuil.ilike(term),
            )
        )

    total = query.count()
    offset = (page - 1) * page_size
    empleados = query.order_by(RRHHEmpleado.apellido, RRHHEmpleado.nombre).offset(offset).limit(page_size).all()

    return EmpleadoListResponse(
        items=[EmpleadoResponse.model_validate(e) for e in empleados],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/empleados/{empleado_id}", response_model=EmpleadoResponse)
def obtener_empleado(
    empleado_id: int,
    current_user: Usuario = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> EmpleadoResponse:
    """Obtiene un empleado por ID. Requiere rrhh.ver."""
    svc = PermisosService(db)
    if not svc.tiene_permiso(current_user, "rrhh.ver"):
        raise HTTPException(status_code=403, detail="Sin permiso: rrhh.ver")

    empleado = (
        db.query(RRHHEmpleado)
        .options(selectinload(RRHHEmpleado.documentos))
        .filter(RRHHEmpleado.id == empleado_id)
        .first()
    )
    if not empleado:
        raise HTTPException(status_code=404, detail="Empleado no encontrado")
    return EmpleadoResponse.model_validate(empleado)


@router.post(
    "/empleados",
    response_model=EmpleadoResponse,
    status_code=status.HTTP_201_CREATED,
)
def crear_empleado(
    data: EmpleadoCreate,
    current_user: Usuario = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> EmpleadoResponse:
    """Crea un empleado nuevo. Requiere rrhh.gestionar."""
    svc = PermisosService(db)
    if not svc.tiene_permiso(current_user, "rrhh.gestionar"):
        raise HTTPException(status_code=403, detail="Sin permiso: rrhh.gestionar")

    # Validar unicidad de DNI
    if db.query(RRHHEmpleado).filter(RRHHEmpleado.dni == data.dni).first():
        raise HTTPException(status_code=400, detail="Ya existe un empleado con ese DNI")

    # Validar unicidad de legajo
    if db.query(RRHHEmpleado).filter(RRHHEmpleado.legajo == data.legajo).first():
        raise HTTPException(status_code=400, detail="Ya existe un empleado con ese legajo")

    # Validar estado
    valid_estados = [e.value for e in EstadoEmpleado]
    if data.estado not in valid_estados:
        raise HTTPException(
            status_code=400,
            detail=f"Estado inválido. Opciones: {valid_estados}",
        )

    # Validar usuario_id si se provee
    if data.usuario_id is not None:
        existing = db.query(RRHHEmpleado).filter(RRHHEmpleado.usuario_id == data.usuario_id).first()
        if existing:
            raise HTTPException(
                status_code=400,
                detail="Ese usuario ya está asignado a otro empleado",
            )

    empleado = RRHHEmpleado(
        **data.model_dump(),
        creado_por_id=current_user.id,
    )
    db.add(empleado)
    db.flush()

    # Registrar en historial
    _registrar_cambio(db, empleado.id, "alta", None, "Empleado creado", current_user.id)

    db.commit()
    db.refresh(empleado)
    return EmpleadoResponse.model_validate(empleado)


@router.put("/empleados/{empleado_id}", response_model=EmpleadoResponse)
def actualizar_empleado(
    empleado_id: int,
    data: EmpleadoUpdate,
    current_user: Usuario = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> EmpleadoResponse:
    """Actualiza un empleado. Requiere rrhh.gestionar. Registra cambios en historial."""
    svc = PermisosService(db)
    if not svc.tiene_permiso(current_user, "rrhh.gestionar"):
        raise HTTPException(status_code=403, detail="Sin permiso: rrhh.gestionar")

    empleado = db.query(RRHHEmpleado).filter(RRHHEmpleado.id == empleado_id).first()
    if not empleado:
        raise HTTPException(status_code=404, detail="Empleado no encontrado")

    update_data = data.model_dump(exclude_unset=True)

    # Validar unicidad si se cambia DNI
    if "dni" in update_data and update_data["dni"] != empleado.dni:
        if (
            db.query(RRHHEmpleado)
            .filter(RRHHEmpleado.dni == update_data["dni"], RRHHEmpleado.id != empleado_id)
            .first()
        ):
            raise HTTPException(status_code=400, detail="Ya existe un empleado con ese DNI")

    # Validar unicidad si se cambia legajo
    if "legajo" in update_data and update_data["legajo"] != empleado.legajo:
        if (
            db.query(RRHHEmpleado)
            .filter(
                RRHHEmpleado.legajo == update_data["legajo"],
                RRHHEmpleado.id != empleado_id,
            )
            .first()
        ):
            raise HTTPException(status_code=400, detail="Ya existe un empleado con ese legajo")

    # Validar unicidad si se cambia hikvision_employee_no
    if "hikvision_employee_no" in update_data and update_data["hikvision_employee_no"]:
        if update_data["hikvision_employee_no"] != empleado.hikvision_employee_no:
            if (
                db.query(RRHHEmpleado)
                .filter(
                    RRHHEmpleado.hikvision_employee_no == update_data["hikvision_employee_no"],
                    RRHHEmpleado.id != empleado_id,
                )
                .first()
            ):
                raise HTTPException(
                    status_code=400,
                    detail="Ese ID de Hikvision ya está asignado a otro empleado",
                )

    # Validar estado si se cambia
    if "estado" in update_data:
        valid_estados = [e.value for e in EstadoEmpleado]
        if update_data["estado"] not in valid_estados:
            raise HTTPException(
                status_code=400,
                detail=f"Estado inválido. Opciones: {valid_estados}",
            )

    # Validar usuario_id si se cambia
    if "usuario_id" in update_data and update_data["usuario_id"] is not None:
        existing = (
            db.query(RRHHEmpleado)
            .filter(
                RRHHEmpleado.usuario_id == update_data["usuario_id"],
                RRHHEmpleado.id != empleado_id,
            )
            .first()
        )
        if existing:
            raise HTTPException(
                status_code=400,
                detail="Ese usuario ya está asignado a otro empleado",
            )

    # Registrar cambios en historial
    for campo, nuevo_valor in update_data.items():
        anterior = getattr(empleado, campo, None)
        if str(anterior) != str(nuevo_valor):
            _registrar_cambio(db, empleado.id, campo, anterior, nuevo_valor, current_user.id)

    # Aplicar cambios
    for campo, valor in update_data.items():
        setattr(empleado, campo, valor)

    empleado.updated_at = datetime.now(UTC)
    db.commit()
    db.refresh(empleado)
    return EmpleadoResponse.model_validate(empleado)


@router.delete("/empleados/{empleado_id}", status_code=status.HTTP_204_NO_CONTENT)
def eliminar_empleado(
    empleado_id: int,
    current_user: Usuario = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> None:
    """Soft-delete de un empleado (activo=False). Requiere rrhh.gestionar."""
    svc = PermisosService(db)
    if not svc.tiene_permiso(current_user, "rrhh.gestionar"):
        raise HTTPException(status_code=403, detail="Sin permiso: rrhh.gestionar")

    empleado = db.query(RRHHEmpleado).filter(RRHHEmpleado.id == empleado_id).first()
    if not empleado:
        raise HTTPException(status_code=404, detail="Empleado no encontrado")

    empleado.activo = False
    empleado.updated_at = datetime.now(UTC)
    _registrar_cambio(db, empleado.id, "activo", "True", "False", current_user.id)
    db.commit()


# ═══════════════════════════════════════════════
# ENDPOINTS — Documentos del legajo
# ═══════════════════════════════════════════════

ALLOWED_MIME_TYPES = {
    "application/pdf",
    "image/jpeg",
    "image/png",
    "image/webp",
    "application/msword",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}


@router.get(
    "/empleados/{empleado_id}/documentos",
    response_model=list[DocumentoResponse],
)
def listar_documentos(
    empleado_id: int,
    current_user: Usuario = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[DocumentoResponse]:
    """Lista documentos del legajo de un empleado. Requiere rrhh.ver."""
    svc = PermisosService(db)
    if not svc.tiene_permiso(current_user, "rrhh.ver"):
        raise HTTPException(status_code=403, detail="Sin permiso: rrhh.ver")

    # Verificar que el empleado existe
    empleado = db.query(RRHHEmpleado).filter(RRHHEmpleado.id == empleado_id).first()
    if not empleado:
        raise HTTPException(status_code=404, detail="Empleado no encontrado")

    docs = (
        db.query(RRHHDocumento)
        .options(
            selectinload(RRHHDocumento.tipo_documento),
            selectinload(RRHHDocumento.subido_por),
        )
        .filter(RRHHDocumento.empleado_id == empleado_id)
        .order_by(RRHHDocumento.created_at.desc())
        .all()
    )

    result = []
    for doc in docs:
        resp = DocumentoResponse.model_validate(doc)
        resp.tipo_documento_nombre = doc.tipo_documento.nombre if doc.tipo_documento else None
        resp.subido_por_nombre = doc.subido_por.nombre if doc.subido_por else None
        result.append(resp)
    return result


@router.post(
    "/empleados/{empleado_id}/documentos",
    response_model=DocumentoResponse,
    status_code=status.HTTP_201_CREATED,
)
async def subir_documento(
    empleado_id: int,
    tipo_documento_id: int = Query(..., description="ID del tipo de documento"),
    descripcion: Optional[str] = Query(default=None, max_length=500),
    fecha_vencimiento: Optional[date] = Query(default=None),
    numero_documento: Optional[str] = Query(default=None, max_length=100),
    file: UploadFile = File(...),
    current_user: Usuario = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> DocumentoResponse:
    """
    Sube un documento al legajo de un empleado.
    Requiere rrhh.gestionar. Archivos permitidos: PDF, imágenes, Word.
    Tamaño máximo: RRHH_MAX_FILE_SIZE_MB (default 10MB).
    """
    svc = PermisosService(db)
    if not svc.tiene_permiso(current_user, "rrhh.gestionar"):
        raise HTTPException(status_code=403, detail="Sin permiso: rrhh.gestionar")

    # Verificar empleado
    empleado = db.query(RRHHEmpleado).filter(RRHHEmpleado.id == empleado_id).first()
    if not empleado:
        raise HTTPException(status_code=404, detail="Empleado no encontrado")

    # Verificar tipo de documento
    tipo_doc = (
        db.query(RRHHTipoDocumento)
        .filter(RRHHTipoDocumento.id == tipo_documento_id, RRHHTipoDocumento.activo.is_(True))
        .first()
    )
    if not tipo_doc:
        raise HTTPException(status_code=400, detail="Tipo de documento no encontrado o inactivo")

    # Validar MIME type
    if file.content_type and file.content_type not in ALLOWED_MIME_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"Tipo de archivo no permitido: {file.content_type}",
        )

    # Leer archivo
    content = await file.read()
    max_bytes = settings.RRHH_MAX_FILE_SIZE_MB * 1024 * 1024
    if len(content) > max_bytes:
        raise HTTPException(
            status_code=400,
            detail=f"Archivo demasiado grande. Máximo: {settings.RRHH_MAX_FILE_SIZE_MB}MB",
        )

    # Guardar en disco: uploads/rrhh/{empleado_id}/{uuid}_{filename}
    upload_dir = os.path.join(settings.RRHH_UPLOADS_DIR, str(empleado_id))
    os.makedirs(upload_dir, exist_ok=True)

    safe_filename = file.filename or "archivo"
    stored_name = f"{uuid.uuid4().hex}_{safe_filename}"
    full_path = os.path.join(upload_dir, stored_name)

    with open(full_path, "wb") as f:
        f.write(content)

    # Guardar en DB (path relativo)
    rel_path = os.path.join(str(empleado_id), stored_name)
    documento = RRHHDocumento(
        empleado_id=empleado_id,
        tipo_documento_id=tipo_documento_id,
        nombre_archivo=safe_filename,
        path_archivo=rel_path,
        mime_type=file.content_type,
        tamano_bytes=len(content),
        descripcion=descripcion,
        fecha_vencimiento=fecha_vencimiento,
        numero_documento=numero_documento,
        subido_por_id=current_user.id,
    )
    db.add(documento)
    db.flush()

    _registrar_cambio(
        db,
        empleado_id,
        "documento_subido",
        None,
        f"{tipo_doc.nombre}: {safe_filename}",
        current_user.id,
    )

    db.commit()
    db.refresh(documento)

    resp = DocumentoResponse.model_validate(documento)
    resp.tipo_documento_nombre = tipo_doc.nombre
    resp.subido_por_nombre = current_user.nombre if hasattr(current_user, "nombre") else None
    return resp


@router.get("/documentos/{documento_id}/descargar")
def descargar_documento(
    documento_id: int,
    current_user: Usuario = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> FileResponse:
    """Descarga un documento del legajo. Auth-gated (no StaticFiles). Requiere rrhh.ver."""
    svc = PermisosService(db)
    if not svc.tiene_permiso(current_user, "rrhh.ver"):
        raise HTTPException(status_code=403, detail="Sin permiso: rrhh.ver")

    documento = db.query(RRHHDocumento).filter(RRHHDocumento.id == documento_id).first()
    if not documento:
        raise HTTPException(status_code=404, detail="Documento no encontrado")

    full_path = os.path.join(settings.RRHH_UPLOADS_DIR, documento.path_archivo)
    if not os.path.exists(full_path):
        raise HTTPException(status_code=404, detail="Archivo no encontrado en disco")

    return FileResponse(
        path=full_path,
        filename=documento.nombre_archivo,
        media_type=documento.mime_type or "application/octet-stream",
    )


@router.delete("/documentos/{documento_id}", status_code=status.HTTP_204_NO_CONTENT)
def eliminar_documento(
    documento_id: int,
    current_user: Usuario = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> None:
    """Elimina un documento del legajo (archivo + registro). Requiere rrhh.gestionar."""
    svc = PermisosService(db)
    if not svc.tiene_permiso(current_user, "rrhh.gestionar"):
        raise HTTPException(status_code=403, detail="Sin permiso: rrhh.gestionar")

    documento = (
        db.query(RRHHDocumento)
        .options(selectinload(RRHHDocumento.tipo_documento))
        .filter(RRHHDocumento.id == documento_id)
        .first()
    )
    if not documento:
        raise HTTPException(status_code=404, detail="Documento no encontrado")

    # Registrar en historial antes de borrar
    tipo_nombre = documento.tipo_documento.nombre if documento.tipo_documento else "desconocido"
    _registrar_cambio(
        db,
        documento.empleado_id,
        "documento_eliminado",
        f"{tipo_nombre}: {documento.nombre_archivo}",
        None,
        current_user.id,
    )

    # Borrar archivo de disco
    full_path = os.path.join(settings.RRHH_UPLOADS_DIR, documento.path_archivo)
    if os.path.exists(full_path):
        os.remove(full_path)

    db.delete(documento)
    db.commit()


# ═══════════════════════════════════════════════
# ENDPOINTS — Tipos de documento (configuración)
# ═══════════════════════════════════════════════


@router.get("/tipos-documento", response_model=list[TipoDocumentoResponse])
def listar_tipos_documento(
    activo: Optional[bool] = None,
    current_user: Usuario = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[TipoDocumentoResponse]:
    """Lista tipos de documento configurados. Requiere rrhh.ver."""
    svc = PermisosService(db)
    if not svc.tiene_permiso(current_user, "rrhh.ver"):
        raise HTTPException(status_code=403, detail="Sin permiso: rrhh.ver")

    query = db.query(RRHHTipoDocumento)
    if activo is not None:
        query = query.filter(RRHHTipoDocumento.activo == activo)
    tipos = query.order_by(RRHHTipoDocumento.orden, RRHHTipoDocumento.nombre).all()
    return [TipoDocumentoResponse.model_validate(t) for t in tipos]


@router.post(
    "/tipos-documento",
    response_model=TipoDocumentoResponse,
    status_code=status.HTTP_201_CREATED,
)
def crear_tipo_documento(
    data: TipoDocumentoCreate,
    current_user: Usuario = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> TipoDocumentoResponse:
    """Crea un tipo de documento nuevo. Requiere rrhh.config."""
    svc = PermisosService(db)
    if not svc.tiene_permiso(current_user, "rrhh.config"):
        raise HTTPException(status_code=403, detail="Sin permiso: rrhh.config")

    if db.query(RRHHTipoDocumento).filter(RRHHTipoDocumento.nombre == data.nombre).first():
        raise HTTPException(status_code=400, detail="Ya existe un tipo de documento con ese nombre")

    tipo = RRHHTipoDocumento(**data.model_dump())
    db.add(tipo)
    db.commit()
    db.refresh(tipo)
    return TipoDocumentoResponse.model_validate(tipo)


@router.put("/tipos-documento/{tipo_id}", response_model=TipoDocumentoResponse)
def actualizar_tipo_documento(
    tipo_id: int,
    data: TipoDocumentoUpdate,
    current_user: Usuario = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> TipoDocumentoResponse:
    """Actualiza un tipo de documento. Requiere rrhh.config."""
    svc = PermisosService(db)
    if not svc.tiene_permiso(current_user, "rrhh.config"):
        raise HTTPException(status_code=403, detail="Sin permiso: rrhh.config")

    tipo = db.query(RRHHTipoDocumento).filter(RRHHTipoDocumento.id == tipo_id).first()
    if not tipo:
        raise HTTPException(status_code=404, detail="Tipo de documento no encontrado")

    update_data = data.model_dump(exclude_unset=True)

    # Validar unicidad del nombre si se cambia
    if "nombre" in update_data and update_data["nombre"] != tipo.nombre:
        if (
            db.query(RRHHTipoDocumento)
            .filter(RRHHTipoDocumento.nombre == update_data["nombre"], RRHHTipoDocumento.id != tipo_id)
            .first()
        ):
            raise HTTPException(
                status_code=400,
                detail="Ya existe un tipo de documento con ese nombre",
            )

    for campo, valor in update_data.items():
        setattr(tipo, campo, valor)

    db.commit()
    db.refresh(tipo)
    return TipoDocumentoResponse.model_validate(tipo)


# ═══════════════════════════════════════════════
# ENDPOINTS — Schema Legajo (campos custom)
# ═══════════════════════════════════════════════


@router.get("/schema-legajo", response_model=list[SchemaLegajoResponse])
def listar_schema_legajo(
    activo: Optional[bool] = None,
    current_user: Usuario = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[SchemaLegajoResponse]:
    """Lista campos custom del legajo. Requiere rrhh.ver."""
    svc = PermisosService(db)
    if not svc.tiene_permiso(current_user, "rrhh.ver"):
        raise HTTPException(status_code=403, detail="Sin permiso: rrhh.ver")

    query = db.query(RRHHSchemaLegajo)
    if activo is not None:
        query = query.filter(RRHHSchemaLegajo.activo == activo)
    campos = query.order_by(RRHHSchemaLegajo.orden, RRHHSchemaLegajo.nombre).all()
    return [SchemaLegajoResponse.model_validate(c) for c in campos]


@router.post(
    "/schema-legajo",
    response_model=SchemaLegajoResponse,
    status_code=status.HTTP_201_CREATED,
)
def crear_campo_legajo(
    data: SchemaLegajoCreate,
    current_user: Usuario = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> SchemaLegajoResponse:
    """Crea un campo custom para el legajo. Requiere rrhh.config."""
    svc = PermisosService(db)
    if not svc.tiene_permiso(current_user, "rrhh.config"):
        raise HTTPException(status_code=403, detail="Sin permiso: rrhh.config")

    valid_tipos = {"text", "number", "date", "select", "boolean"}
    if data.tipo_campo not in valid_tipos:
        raise HTTPException(
            status_code=400,
            detail=f"tipo_campo inválido. Opciones: {sorted(valid_tipos)}",
        )

    if data.tipo_campo == "select" and not data.opciones:
        raise HTTPException(
            status_code=400,
            detail="tipo_campo 'select' requiere opciones",
        )

    if db.query(RRHHSchemaLegajo).filter(RRHHSchemaLegajo.nombre == data.nombre).first():
        raise HTTPException(status_code=400, detail="Ya existe un campo con ese nombre")

    campo = RRHHSchemaLegajo(**data.model_dump())
    db.add(campo)
    db.commit()
    db.refresh(campo)
    return SchemaLegajoResponse.model_validate(campo)


@router.put("/schema-legajo/{campo_id}", response_model=SchemaLegajoResponse)
def actualizar_campo_legajo(
    campo_id: int,
    data: SchemaLegajoUpdate,
    current_user: Usuario = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> SchemaLegajoResponse:
    """Actualiza un campo custom del legajo. Requiere rrhh.config."""
    svc = PermisosService(db)
    if not svc.tiene_permiso(current_user, "rrhh.config"):
        raise HTTPException(status_code=403, detail="Sin permiso: rrhh.config")

    campo = db.query(RRHHSchemaLegajo).filter(RRHHSchemaLegajo.id == campo_id).first()
    if not campo:
        raise HTTPException(status_code=404, detail="Campo no encontrado")

    update_data = data.model_dump(exclude_unset=True)

    # Validar tipo_campo si se cambia
    if "tipo_campo" in update_data:
        valid_tipos = {"text", "number", "date", "select", "boolean"}
        if update_data["tipo_campo"] not in valid_tipos:
            raise HTTPException(
                status_code=400,
                detail=f"tipo_campo inválido. Opciones: {sorted(valid_tipos)}",
            )

    for campo_key, valor in update_data.items():
        setattr(campo, campo_key, valor)

    db.commit()
    db.refresh(campo)
    return SchemaLegajoResponse.model_validate(campo)


# ═══════════════════════════════════════════════
# ENDPOINTS — Historial del legajo
# ═══════════════════════════════════════════════


@router.get(
    "/empleados/{empleado_id}/historial",
    response_model=list[HistorialResponse],
)
def listar_historial(
    empleado_id: int,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    current_user: Usuario = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[HistorialResponse]:
    """Lista historial de cambios del legajo de un empleado. Requiere rrhh.ver."""
    svc = PermisosService(db)
    if not svc.tiene_permiso(current_user, "rrhh.ver"):
        raise HTTPException(status_code=403, detail="Sin permiso: rrhh.ver")

    # Verificar que el empleado existe
    empleado = db.query(RRHHEmpleado).filter(RRHHEmpleado.id == empleado_id).first()
    if not empleado:
        raise HTTPException(status_code=404, detail="Empleado no encontrado")

    offset = (page - 1) * page_size
    historial = (
        db.query(RRHHLegajoHistorial)
        .options(selectinload(RRHHLegajoHistorial.usuario))
        .filter(RRHHLegajoHistorial.empleado_id == empleado_id)
        .order_by(RRHHLegajoHistorial.created_at.desc())
        .offset(offset)
        .limit(page_size)
        .all()
    )

    result = []
    for h in historial:
        resp = HistorialResponse.model_validate(h)
        resp.usuario_nombre = h.usuario.nombre if h.usuario else None
        result.append(resp)
    return result
