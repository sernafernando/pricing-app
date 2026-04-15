"""
Router del módulo Administración - Caja (Cash Register).

Endpoints para:
- Cajas: CRUD
- Movimientos: registro con balance atómico, listado paginado con filtros
- Categorías: CRUD
- Sync: importación desde Google Sheets
- Tipos de documento: CRUD
- Documentos: CRUD + vinculación N:M con movimientos
- Archivos: upload, download, delete
"""

from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from sqlalchemy import func as sa_func

from app.core.database import get_db
from app.api.deps import get_current_user
from app.models.caja import CajaDocumentoMovimiento
from app.models.usuario import Usuario
from app.services.caja_service import CajaService
from app.services.permisos_service import PermisosService

router = APIRouter(prefix="/administracion-caja", tags=["Administración - Caja"])


# ──────────────────────────────────────────────
# Pydantic Schemas
# ──────────────────────────────────────────────


# --- Caja ---


class CajaResponse(BaseModel):
    id: int
    nombre: str
    empresa_id: int
    empresa_nombre: str = ""
    moneda: str
    saldo_inicial: float
    saldo_actual: float
    activo: bool
    created_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class CajaCreate(BaseModel):
    nombre: str = Field(min_length=1, max_length=255)
    empresa_id: int
    moneda: str = Field(pattern="^(ARS|USD)$")
    saldo_inicial: float = 0


class CajaUpdate(BaseModel):
    nombre: Optional[str] = Field(None, min_length=1, max_length=255)
    activo: Optional[bool] = None


# --- Movimiento ---


class TagResponse(BaseModel):
    id: int
    nombre: str
    color: Optional[str] = None
    activo: bool = True

    model_config = ConfigDict(from_attributes=True)


class TagCreate(BaseModel):
    nombre: str = Field(min_length=1, max_length=100)
    color: Optional[str] = Field(None, pattern=r"^#[0-9a-fA-F]{6}$")


class TagUpdate(BaseModel):
    nombre: Optional[str] = Field(None, min_length=1, max_length=100)
    color: Optional[str] = Field(None, pattern=r"^#[0-9a-fA-F]{6}$")
    activo: Optional[bool] = None


class ClasificacionUpdate(BaseModel):
    categoria_id: Optional[int] = None
    clear_categoria: bool = False
    tag_ids: Optional[list[int]] = None


class MovimientoResponse(BaseModel):
    id: int
    caja_id: int
    fecha: date
    detalle: str
    tipo: str
    monto: float
    saldo_posterior: float
    categoria_id: Optional[int] = None
    categoria_nombre: Optional[str] = None
    origen: str
    registrado_por_nombre: Optional[str] = None
    observaciones: Optional[str] = None
    documentos_count: int = 0
    tags: list[TagResponse] = []
    created_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class MovimientoCreate(BaseModel):
    fecha: date
    detalle: str = Field(min_length=1)
    tipo: str = Field(pattern="^(ingreso|egreso)$")
    monto: float = Field(gt=0)
    categoria_id: Optional[int] = None
    observaciones: Optional[str] = None


class MovimientosListResponse(BaseModel):
    items: list[MovimientoResponse]
    total: int
    page: int
    page_size: int
    total_ingresos: float
    total_egresos: float
    saldo_periodo: float


# --- Categoría ---


class CategoriaResponse(BaseModel):
    id: int
    nombre: str
    tipo_aplicable: str
    activo: bool

    model_config = ConfigDict(from_attributes=True)


class CategoriaCreate(BaseModel):
    nombre: str = Field(min_length=1, max_length=100)
    tipo_aplicable: str = Field(default="ambos", pattern="^(ingreso|egreso|ambos)$")


class CategoriaUpdate(BaseModel):
    nombre: Optional[str] = Field(None, min_length=1, max_length=100)
    tipo_aplicable: Optional[str] = Field(None, pattern="^(ingreso|egreso|ambos)$")
    activo: Optional[bool] = None


# --- Sync ---


class SyncResponse(BaseModel):
    total_procesadas: int
    nuevas: int
    duplicadas_saltadas: int
    errores: list[dict]


# --- Tipo Documento ---


class TipoDocumentoResponse(BaseModel):
    id: int
    nombre: str
    descripcion: Optional[str] = None
    activo: bool

    model_config = ConfigDict(from_attributes=True)


class TipoDocumentoCreate(BaseModel):
    nombre: str = Field(min_length=1, max_length=100)
    descripcion: Optional[str] = None


class TipoDocumentoUpdate(BaseModel):
    nombre: Optional[str] = Field(None, min_length=1, max_length=100)
    descripcion: Optional[str] = None
    activo: Optional[bool] = None


# --- Documento ---


class ArchivoResponse(BaseModel):
    id: int
    documento_id: int
    nombre_archivo: str
    tipo_mime: str
    tamanio_bytes: Optional[int] = None
    created_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class DocumentoResponse(BaseModel):
    id: int
    tipo_documento_id: int
    tipo_documento_nombre: str = ""
    numero: Optional[str] = None
    descripcion: Optional[str] = None
    fecha_documento: Optional[date] = None
    monto_documento: Optional[float] = None
    entidad_tipo: Optional[str] = None
    entidad_id: Optional[int] = None
    archivos: list[ArchivoResponse] = []
    movimientos_count: int = 0
    created_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class DocumentoCreate(BaseModel):
    tipo_documento_id: int
    numero: Optional[str] = Field(None, max_length=255)
    descripcion: Optional[str] = None
    fecha_documento: Optional[date] = None
    monto_documento: Optional[float] = None
    movimiento_ids: Optional[list[int]] = None
    entidad_tipo: Optional[str] = None
    entidad_id: Optional[int] = None


class DocumentoUpdate(BaseModel):
    tipo_documento_id: Optional[int] = None
    numero: Optional[str] = Field(None, max_length=255)
    descripcion: Optional[str] = None
    fecha_documento: Optional[date] = None
    monto_documento: Optional[float] = None


# ──────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────


def _check_permiso(db: Session, user: Usuario, codigo: str) -> None:
    """Verifica permiso o lanza 403."""
    if not PermisosService(db).tiene_permiso(user, codigo):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Sin permiso: {codigo}",
        )


def _build_caja_response(caja) -> CajaResponse:
    """Builds CajaResponse from ORM object."""
    return CajaResponse(
        id=caja.id,
        nombre=caja.nombre,
        empresa_id=caja.empresa_id,
        empresa_nombre=caja.empresa.nombre if caja.empresa else "",
        moneda=caja.moneda,
        saldo_inicial=float(caja.saldo_inicial),
        saldo_actual=float(caja.saldo_actual),
        activo=caja.activo,
        created_at=caja.created_at,
    )


def _build_movimiento_response(mov, doc_count: int = 0, tags: Optional[list[dict]] = None) -> MovimientoResponse:
    """Builds MovimientoResponse from ORM object."""
    tag_responses = [TagResponse(**t) for t in (tags or [])]
    return MovimientoResponse(
        id=mov.id,
        caja_id=mov.caja_id,
        fecha=mov.fecha,
        detalle=mov.detalle,
        tipo=mov.tipo,
        monto=float(mov.monto),
        saldo_posterior=float(mov.saldo_posterior),
        categoria_id=mov.categoria_id,
        categoria_nombre=mov.categoria.nombre if mov.categoria else None,
        origen=mov.origen,
        registrado_por_nombre=mov.registrado_por.nombre if mov.registrado_por else None,
        observaciones=mov.observaciones,
        documentos_count=doc_count,
        tags=tag_responses,
        created_at=mov.created_at,
    )


def _build_documento_response(doc, mov_count: int = 0) -> DocumentoResponse:
    """Builds DocumentoResponse from ORM object."""
    return DocumentoResponse(
        id=doc.id,
        tipo_documento_id=doc.tipo_documento_id,
        tipo_documento_nombre=doc.tipo_documento.nombre if doc.tipo_documento else "",
        numero=doc.numero,
        descripcion=doc.descripcion,
        fecha_documento=doc.fecha_documento,
        monto_documento=float(doc.monto_documento) if doc.monto_documento else None,
        entidad_tipo=doc.entidad_tipo,
        entidad_id=doc.entidad_id,
        archivos=[
            ArchivoResponse(
                id=a.id,
                documento_id=a.documento_id,
                nombre_archivo=a.nombre_archivo,
                tipo_mime=a.tipo_mime,
                tamanio_bytes=a.tamanio_bytes,
                created_at=a.created_at,
            )
            for a in (doc.archivos or [])
        ],
        movimientos_count=mov_count,
        created_at=doc.created_at,
    )


# ──────────────────────────────────────────────
# ENDPOINTS — Cajas CRUD
# ──────────────────────────────────────────────


@router.get("/cajas", response_model=list[CajaResponse], summary="Listar cajas")
def listar_cajas(
    activo: Optional[bool] = Query(None),
    empresa_id: Optional[int] = Query(None),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> list[CajaResponse]:
    """Lista todas las cajas con datos de empresa."""
    _check_permiso(db, current_user, "administracion.ver_caja")
    svc = CajaService(db)
    cajas = svc.listar_cajas(activo=activo, empresa_id=empresa_id)
    return [_build_caja_response(c) for c in cajas]


@router.get("/cajas/{caja_id}", response_model=CajaResponse, summary="Detalle de caja")
def obtener_caja(
    caja_id: int,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> CajaResponse:
    """Obtiene detalle de una caja."""
    _check_permiso(db, current_user, "administracion.ver_caja")
    svc = CajaService(db)
    caja = svc.obtener_caja(caja_id)
    return _build_caja_response(caja)


@router.post(
    "/cajas",
    response_model=CajaResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Crear caja",
)
def crear_caja(
    data: CajaCreate,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> CajaResponse:
    """Crea una nueva caja."""
    _check_permiso(db, current_user, "administracion.gestionar_caja")
    svc = CajaService(db)
    try:
        caja = svc.crear_caja(
            nombre=data.nombre,
            empresa_id=data.empresa_id,
            moneda=data.moneda,
            saldo_inicial=Decimal(str(data.saldo_inicial)),
        )
        db.commit()
        db.refresh(caja)
    except Exception as e:
        db.rollback()
        # Handle unique constraint violation
        if "uq_caja_nombre_empresa" in str(e).lower() or "unique" in str(e).lower():
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Ya existe una caja '{data.nombre}' para esta empresa",
            )
        raise
    return _build_caja_response(svc.obtener_caja(caja.id))


@router.put("/cajas/{caja_id}", response_model=CajaResponse, summary="Actualizar caja")
def actualizar_caja(
    caja_id: int,
    data: CajaUpdate,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> CajaResponse:
    """Actualiza nombre y/o estado activo de una caja."""
    _check_permiso(db, current_user, "administracion.gestionar_caja")
    svc = CajaService(db)
    caja = svc.actualizar_caja(caja_id, nombre=data.nombre, activo=data.activo)
    db.commit()
    return _build_caja_response(svc.obtener_caja(caja.id))


@router.delete(
    "/cajas/{caja_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Eliminar caja",
)
def eliminar_caja(
    caja_id: int,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> None:
    """Elimina caja si no tiene movimientos."""
    _check_permiso(db, current_user, "administracion.gestionar_caja")
    svc = CajaService(db)
    svc.eliminar_caja(caja_id)
    db.commit()


# ──────────────────────────────────────────────
# ENDPOINTS — Movimientos
# ──────────────────────────────────────────────


@router.get(
    "/cajas/{caja_id}/movimientos",
    response_model=MovimientosListResponse,
    summary="Listar movimientos",
)
def listar_movimientos(
    caja_id: int,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    fecha_desde: Optional[date] = None,
    fecha_hasta: Optional[date] = None,
    tipo: Optional[str] = Query(None, pattern="^(ingreso|egreso)$"),
    categoria_id: Optional[int] = None,
    tag_id: Optional[int] = None,
    busqueda: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> MovimientosListResponse:
    """Lista movimientos paginados con filtros y resumen."""
    _check_permiso(db, current_user, "administracion.ver_caja")
    svc = CajaService(db)
    items, total, summary = svc.obtener_movimientos(
        caja_id=caja_id,
        page=page,
        page_size=page_size,
        fecha_desde=fecha_desde,
        fecha_hasta=fecha_hasta,
        tipo=tipo,
        categoria_id=categoria_id,
        tag_id=tag_id,
        busqueda=busqueda,
    )

    # Batch-load document counts and tags for this page of movements
    mov_ids = [m.id for m in items]
    doc_counts = svc.documentos_count_por_movimiento(mov_ids)
    tags_map = svc.tags_por_movimientos_batch(mov_ids)

    return MovimientosListResponse(
        items=[_build_movimiento_response(m, doc_counts.get(m.id, 0), tags_map.get(m.id, [])) for m in items],
        total=total,
        page=page,
        page_size=page_size,
        total_ingresos=summary["total_ingresos"],
        total_egresos=summary["total_egresos"],
        saldo_periodo=summary["saldo_periodo"],
    )


@router.post(
    "/cajas/{caja_id}/movimientos",
    response_model=MovimientoResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Registrar movimiento",
)
def registrar_movimiento(
    caja_id: int,
    data: MovimientoCreate,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> MovimientoResponse:
    """Registra un movimiento con balance atómico (ingreso o egreso)."""
    _check_permiso(db, current_user, "administracion.gestionar_caja")
    svc = CajaService(db)
    movimiento = svc.registrar_movimiento(
        caja_id=caja_id,
        fecha=data.fecha,
        detalle=data.detalle,
        tipo=data.tipo,
        monto=Decimal(str(data.monto)),
        user_id=current_user.id,
        categoria_id=data.categoria_id,
        observaciones=data.observaciones,
    )
    db.commit()
    db.refresh(movimiento)
    return _build_movimiento_response(movimiento)


# ──────────────────────────────────────────────
# ENDPOINTS — Categorías
# ──────────────────────────────────────────────


@router.get("/categorias", response_model=list[CategoriaResponse], summary="Listar categorías")
def listar_categorias(
    incluir_inactivas: bool = Query(False),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> list[CategoriaResponse]:
    """Lista categorías de movimiento."""
    _check_permiso(db, current_user, "administracion.ver_caja")
    svc = CajaService(db)
    cats = svc.listar_categorias(incluir_inactivas=incluir_inactivas)
    return [CategoriaResponse(id=c.id, nombre=c.nombre, tipo_aplicable=c.tipo_aplicable, activo=c.activo) for c in cats]


@router.post(
    "/categorias",
    response_model=CategoriaResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Crear categoría",
)
def crear_categoria(
    data: CategoriaCreate,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> CategoriaResponse:
    """Crea una nueva categoría."""
    _check_permiso(db, current_user, "administracion.gestionar_caja")
    svc = CajaService(db)
    cat = svc.crear_categoria(nombre=data.nombre, tipo_aplicable=data.tipo_aplicable)
    db.commit()
    return CategoriaResponse(id=cat.id, nombre=cat.nombre, tipo_aplicable=cat.tipo_aplicable, activo=cat.activo)


@router.put("/categorias/{cat_id}", response_model=CategoriaResponse, summary="Actualizar categoría")
def actualizar_categoria(
    cat_id: int,
    data: CategoriaUpdate,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> CategoriaResponse:
    """Actualiza categoría."""
    _check_permiso(db, current_user, "administracion.gestionar_caja")
    svc = CajaService(db)
    cat = svc.actualizar_categoria(cat_id, nombre=data.nombre, tipo_aplicable=data.tipo_aplicable, activo=data.activo)
    db.commit()
    return CategoriaResponse(id=cat.id, nombre=cat.nombre, tipo_aplicable=cat.tipo_aplicable, activo=cat.activo)


@router.delete(
    "/categorias/{cat_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Eliminar categoría",
)
def eliminar_categoria(
    cat_id: int,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> None:
    """Elimina categoría si no está en uso."""
    _check_permiso(db, current_user, "administracion.gestionar_caja")
    svc = CajaService(db)
    svc.eliminar_categoria(cat_id)
    db.commit()


# ──────────────────────────────────────────────
# ENDPOINTS — Sync
# ──────────────────────────────────────────────


@router.post("/sync", response_model=SyncResponse, summary="Sincronizar desde Google Sheets")
def sincronizar_sheets(
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> SyncResponse:
    """Importa movimientos históricos desde Google Sheets."""
    _check_permiso(db, current_user, "administracion.sincronizar_caja")

    from app.services.caja_sheets_sync import CajaSheetsSync

    try:
        sync_svc = CajaSheetsSync(db)
        result = sync_svc.sincronizar()
        db.commit()
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))
    except ConnectionError as e:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(e))

    return SyncResponse(**result)


# ──────────────────────────────────────────────
# ENDPOINTS — Tipos de Documento
# ──────────────────────────────────────────────


@router.get(
    "/tipo-documentos",
    response_model=list[TipoDocumentoResponse],
    summary="Listar tipos de documento",
)
def listar_tipo_documentos(
    incluir_inactivos: bool = Query(False),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> list[TipoDocumentoResponse]:
    """Lista tipos de documento configurados."""
    _check_permiso(db, current_user, "administracion.ver_caja")
    svc = CajaService(db)
    tipos = svc.listar_tipo_documentos(incluir_inactivos=incluir_inactivos)
    return [TipoDocumentoResponse(id=t.id, nombre=t.nombre, descripcion=t.descripcion, activo=t.activo) for t in tipos]


@router.post(
    "/tipo-documentos",
    response_model=TipoDocumentoResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Crear tipo de documento",
)
def crear_tipo_documento(
    data: TipoDocumentoCreate,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> TipoDocumentoResponse:
    """Crea un nuevo tipo de documento."""
    _check_permiso(db, current_user, "administracion.gestionar_caja")
    svc = CajaService(db)
    tipo = svc.crear_tipo_documento(nombre=data.nombre, descripcion=data.descripcion)
    db.commit()
    return TipoDocumentoResponse(id=tipo.id, nombre=tipo.nombre, descripcion=tipo.descripcion, activo=tipo.activo)


@router.put(
    "/tipo-documentos/{tipo_id}",
    response_model=TipoDocumentoResponse,
    summary="Actualizar tipo de documento",
)
def actualizar_tipo_documento(
    tipo_id: int,
    data: TipoDocumentoUpdate,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> TipoDocumentoResponse:
    """Actualiza tipo de documento."""
    _check_permiso(db, current_user, "administracion.gestionar_caja")
    svc = CajaService(db)
    tipo = svc.actualizar_tipo_documento(tipo_id, nombre=data.nombre, descripcion=data.descripcion, activo=data.activo)
    db.commit()
    return TipoDocumentoResponse(id=tipo.id, nombre=tipo.nombre, descripcion=tipo.descripcion, activo=tipo.activo)


# ──────────────────────────────────────────────
# ENDPOINTS — Documentos
# ──────────────────────────────────────────────


@router.post(
    "/documentos",
    response_model=DocumentoResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Crear documento",
)
def crear_documento(
    data: DocumentoCreate,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> DocumentoResponse:
    """Crea documento, opcionalmente vinculándolo a movimientos."""
    _check_permiso(db, current_user, "administracion.gestionar_caja")
    svc = CajaService(db)
    doc = svc.crear_documento(
        tipo_documento_id=data.tipo_documento_id,
        user_id=current_user.id,
        numero=data.numero,
        descripcion=data.descripcion,
        fecha_documento=data.fecha_documento,
        monto_documento=Decimal(str(data.monto_documento)) if data.monto_documento else None,
        movimiento_ids=data.movimiento_ids,
        entidad_tipo=data.entidad_tipo,
        entidad_id=data.entidad_id,
    )
    db.commit()
    db.refresh(doc)
    # Count linked movements
    mov_count = (
        db.query(sa_func.count(CajaDocumentoMovimiento.id))
        .filter(CajaDocumentoMovimiento.documento_id == doc.id)
        .scalar()
    )
    return _build_documento_response(doc, mov_count)


@router.put(
    "/documentos/{doc_id}",
    response_model=DocumentoResponse,
    summary="Actualizar documento",
)
def actualizar_documento(
    doc_id: int,
    data: DocumentoUpdate,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> DocumentoResponse:
    """Actualiza metadatos de un documento."""
    _check_permiso(db, current_user, "administracion.gestionar_caja")
    svc = CajaService(db)
    doc = svc.actualizar_documento(
        doc_id,
        tipo_documento_id=data.tipo_documento_id,
        numero=data.numero,
        descripcion=data.descripcion,
        fecha_documento=data.fecha_documento,
        monto_documento=Decimal(str(data.monto_documento)) if data.monto_documento else None,
    )
    db.commit()
    db.refresh(doc)
    mov_count = (
        db.query(sa_func.count(CajaDocumentoMovimiento.id))
        .filter(CajaDocumentoMovimiento.documento_id == doc.id)
        .scalar()
    )
    return _build_documento_response(doc, mov_count)


@router.delete(
    "/documentos/{doc_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Eliminar documento",
)
def eliminar_documento(
    doc_id: int,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> None:
    """Elimina documento (solo si no está vinculado a movimientos)."""
    _check_permiso(db, current_user, "administracion.gestionar_caja")
    svc = CajaService(db)
    svc.eliminar_documento(doc_id)
    db.commit()


# ──────────────────────────────────────────────
# ENDPOINTS — Document-Movement Links
# ──────────────────────────────────────────────


@router.post(
    "/documentos/{doc_id}/movimientos/{mov_id}",
    status_code=status.HTTP_201_CREATED,
    summary="Vincular documento a movimiento",
)
def vincular_documento_movimiento(
    doc_id: int,
    mov_id: int,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> dict:
    """Crea vínculo entre documento y movimiento."""
    _check_permiso(db, current_user, "administracion.gestionar_caja")
    svc = CajaService(db)
    svc.vincular_documento_movimiento(doc_id, mov_id)
    db.commit()
    return {"detail": "Vínculo creado"}


@router.delete(
    "/documentos/{doc_id}/movimientos/{mov_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Desvincular documento de movimiento",
)
def desvincular_documento_movimiento(
    doc_id: int,
    mov_id: int,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> None:
    """Elimina vínculo entre documento y movimiento."""
    _check_permiso(db, current_user, "administracion.gestionar_caja")
    svc = CajaService(db)
    svc.desvincular_documento_movimiento(doc_id, mov_id)
    db.commit()


@router.get(
    "/movimientos/{mov_id}/documentos",
    response_model=list[DocumentoResponse],
    summary="Documentos de un movimiento",
)
def documentos_por_movimiento(
    mov_id: int,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> list[DocumentoResponse]:
    """Lista documentos vinculados a un movimiento."""
    _check_permiso(db, current_user, "administracion.ver_caja")
    svc = CajaService(db)
    docs = svc.documentos_por_movimiento(mov_id)
    result = []
    for doc in docs:
        mov_count = (
            db.query(sa_func.count(CajaDocumentoMovimiento.id))
            .filter(CajaDocumentoMovimiento.documento_id == doc.id)
            .scalar()
        )
        result.append(_build_documento_response(doc, mov_count))
    return result


# ──────────────────────────────────────────────
# ENDPOINTS — Archivos
# ──────────────────────────────────────────────


@router.post(
    "/documentos/{doc_id}/archivos",
    response_model=ArchivoResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Subir archivo a documento",
)
def subir_archivo(
    doc_id: int,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> ArchivoResponse:
    """Sube un archivo (PDF, JPEG, PNG, WEBP) a un documento. Max 10MB."""
    _check_permiso(db, current_user, "administracion.gestionar_caja")
    svc = CajaService(db)
    archivo = svc.subir_archivo(doc_id, file, current_user.id)
    db.commit()
    return ArchivoResponse(
        id=archivo.id,
        documento_id=archivo.documento_id,
        nombre_archivo=archivo.nombre_archivo,
        tipo_mime=archivo.tipo_mime,
        tamanio_bytes=archivo.tamanio_bytes,
        created_at=archivo.created_at,
    )


@router.get(
    "/archivos/{archivo_id}",
    summary="Descargar archivo",
)
def descargar_archivo(
    archivo_id: int,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    """Descarga/visualiza un archivo adjunto."""
    _check_permiso(db, current_user, "administracion.ver_caja")
    svc = CajaService(db)
    file_path, content_type = svc.descargar_archivo(archivo_id)
    return FileResponse(file_path, media_type=content_type)


@router.delete(
    "/archivos/{archivo_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Eliminar archivo",
)
def eliminar_archivo(
    archivo_id: int,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> None:
    """Elimina archivo del disco y de la BD."""
    _check_permiso(db, current_user, "administracion.gestionar_caja")
    svc = CajaService(db)
    svc.eliminar_archivo(archivo_id)
    db.commit()


# ──────────────────────────────────────────────
# ENDPOINTS — Tags
# ──────────────────────────────────────────────


@router.get(
    "/tags",
    response_model=list[TagResponse],
    summary="Listar tags",
)
def listar_tags(
    activo: Optional[bool] = None,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> list[TagResponse]:
    """Lista todos los tags de caja."""
    _check_permiso(db, current_user, "administracion.ver_caja")
    svc = CajaService(db)
    tags = svc.listar_tags(solo_activos=activo is True)
    return [TagResponse.model_validate(t) for t in tags]


@router.post(
    "/tags",
    response_model=TagResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Crear tag",
)
def crear_tag(
    data: TagCreate,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> TagResponse:
    """Crea un nuevo tag."""
    _check_permiso(db, current_user, "administracion.gestionar_caja")
    svc = CajaService(db)
    tag = svc.crear_tag(nombre=data.nombre, color=data.color)
    db.commit()
    db.refresh(tag)
    return TagResponse.model_validate(tag)


@router.put(
    "/tags/{tag_id}",
    response_model=TagResponse,
    summary="Actualizar tag",
)
def actualizar_tag(
    tag_id: int,
    data: TagUpdate,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> TagResponse:
    """Actualiza nombre, color o estado de un tag."""
    _check_permiso(db, current_user, "administracion.gestionar_caja")
    svc = CajaService(db)
    tag = svc.actualizar_tag(tag_id, nombre=data.nombre, color=data.color, activo=data.activo)
    db.commit()
    db.refresh(tag)
    return TagResponse.model_validate(tag)


@router.delete(
    "/tags/{tag_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Eliminar tag",
)
def eliminar_tag(
    tag_id: int,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> None:
    """Elimina tag (solo si no está vinculado a movimientos)."""
    _check_permiso(db, current_user, "administracion.gestionar_caja")
    svc = CajaService(db)
    svc.eliminar_tag(tag_id)
    db.commit()


# ──────────────────────────────────────────────
# ENDPOINTS — Clasificación de movimientos
# ──────────────────────────────────────────────


@router.patch(
    "/movimientos/{mov_id}/clasificacion",
    response_model=MovimientoResponse,
    summary="Clasificar movimiento",
)
def clasificar_movimiento(
    mov_id: int,
    data: ClasificacionUpdate,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> MovimientoResponse:
    """Actualiza categoría y/o tags de un movimiento existente."""
    _check_permiso(db, current_user, "administracion.gestionar_caja")
    svc = CajaService(db)
    mov = svc.clasificar_movimiento(
        mov_id=mov_id,
        categoria_id=data.categoria_id,
        clear_categoria=data.clear_categoria,
        tag_ids=data.tag_ids,
    )
    db.commit()
    db.refresh(mov)
    tags_map = svc.tags_por_movimientos_batch([mov.id])
    doc_counts = svc.documentos_count_por_movimiento([mov.id])
    return _build_movimiento_response(mov, doc_counts.get(mov.id, 0), tags_map.get(mov.id, []))
