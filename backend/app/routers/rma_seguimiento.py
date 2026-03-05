"""
Router del módulo RMA Seguimiento.

Endpoints:
- CRUD de casos RMA (crear, listar, obtener, actualizar)
- CRUD de items dentro de un caso
- Gestión de opciones de dropdowns (admin)
- Historial de cambios (auditoría)
- Listado de depósitos desde tb_storage
- Generación automática de número de caso
"""

from datetime import date, datetime, UTC
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func
from sqlalchemy.orm import Session, selectinload

from app.core.database import get_db
from app.core.deps import get_current_user
from app.models.etiqueta_envio import EtiquetaEnvio
from app.models.rma_caso import RmaCaso
from app.models.rma_caso_historial import RmaCasoHistorial
from app.models.rma_caso_item import RmaCasoItem
from app.models.rma_proveedor import RmaProveedor
from app.models.rma_seguimiento_opcion import RmaSeguimientoOpcion
from app.models.tb_storage import TbStorage
from app.models.usuario import Usuario
from app.services.permisos_service import PermisosService

router = APIRouter(prefix="/rma-seguimiento", tags=["rma-seguimiento"])


# ──────────────────────────────────────────────
# SCHEMAS
# ──────────────────────────────────────────────


class OpcionResponse(BaseModel):
    id: int
    categoria: str
    valor: str
    orden: int
    activo: bool
    color: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


class OpcionCreate(BaseModel):
    categoria: str = Field(min_length=1, max_length=50)
    valor: str = Field(min_length=1, max_length=200)
    orden: int = 0
    color: Optional[str] = None


class OpcionUpdate(BaseModel):
    valor: Optional[str] = None
    orden: Optional[int] = None
    activo: Optional[bool] = None
    color: Optional[str] = None


class DepositoResponse(BaseModel):
    stor_id: int
    stor_desc: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


class ItemCreate(BaseModel):
    serial_number: Optional[str] = None
    item_id: Optional[int] = None
    is_id: Optional[int] = None
    it_transaction: Optional[int] = None
    ean: Optional[str] = None
    producto_desc: Optional[str] = None
    precio: Optional[float] = None
    estado_facturacion: Optional[str] = None
    link_ml: Optional[str] = None
    # Proveedor (auto-completado desde traza de compra)
    supp_id: Optional[int] = None
    proveedor_nombre: Optional[str] = None


class ItemUpdate(BaseModel):
    # Recepción
    estado_recepcion_id: Optional[int] = None
    costo_envio: Optional[float] = None
    causa_devolucion_id: Optional[int] = None
    # Revisión
    apto_venta_id: Optional[int] = None
    requirio_reacondicionamiento: Optional[bool] = None
    estado_revision_id: Optional[int] = None
    descripcion_falla: Optional[str] = None
    # Proceso interno
    estado_proceso_id: Optional[int] = None
    deposito_destino_id: Optional[int] = None
    enviado_fisicamente_deposito: Optional[bool] = None
    corroborar_nc: Optional[bool] = None
    requirio_rma_interno: Optional[bool] = None
    # Devolución parcial
    requiere_nota_credito: Optional[bool] = None
    debe_facturarse: Optional[bool] = None
    # Proveedor
    supp_id: Optional[int] = None
    proveedor_nombre: Optional[str] = None
    listo_envio_proveedor: Optional[bool] = None
    enviado_proveedor: Optional[bool] = None
    fecha_envio_proveedor: Optional[str] = None
    fecha_respuesta_proveedor: Optional[str] = None
    estado_proveedor_id: Optional[int] = None
    nc_proveedor: Optional[str] = None
    monto_nc_proveedor: Optional[float] = None
    # Observaciones
    observaciones: Optional[str] = None
    # ERP
    rmah_id: Optional[int] = None
    rmad_id: Optional[int] = None


class ItemResponse(BaseModel):
    id: int
    caso_id: int
    serial_number: Optional[str] = None
    item_id: Optional[int] = None
    is_id: Optional[int] = None
    it_transaction: Optional[int] = None
    ean: Optional[str] = None
    producto_desc: Optional[str] = None
    precio: Optional[float] = None
    estado_facturacion: Optional[str] = None
    link_ml: Optional[str] = None
    # Recepción
    estado_recepcion_id: Optional[int] = None
    estado_recepcion_valor: Optional[str] = None
    estado_recepcion_color: Optional[str] = None
    costo_envio: Optional[float] = None
    causa_devolucion_id: Optional[int] = None
    causa_devolucion_valor: Optional[str] = None
    causa_devolucion_color: Optional[str] = None
    recepcion_usuario_id: Optional[int] = None
    recepcion_fecha: Optional[str] = None
    # Revisión
    apto_venta_id: Optional[int] = None
    apto_venta_valor: Optional[str] = None
    apto_venta_color: Optional[str] = None
    requirio_reacondicionamiento: Optional[bool] = None
    estado_revision_id: Optional[int] = None
    estado_revision_valor: Optional[str] = None
    estado_revision_color: Optional[str] = None
    descripcion_falla: Optional[str] = None
    revision_usuario_id: Optional[int] = None
    revision_fecha: Optional[str] = None
    # Proceso interno
    estado_proceso_id: Optional[int] = None
    estado_proceso_valor: Optional[str] = None
    estado_proceso_color: Optional[str] = None
    deposito_destino_id: Optional[int] = None
    deposito_destino_valor: Optional[str] = None
    deposito_destino_color: Optional[str] = None
    enviado_fisicamente_deposito: Optional[bool] = None
    corroborar_nc: Optional[bool] = None
    requirio_rma_interno: Optional[bool] = None
    # Devolución parcial
    requiere_nota_credito: Optional[bool] = None
    debe_facturarse: Optional[bool] = None
    # Proveedor
    supp_id: Optional[int] = None
    proveedor_nombre: Optional[str] = None
    listo_envio_proveedor: Optional[bool] = None
    enviado_proveedor: Optional[bool] = None
    shipping_id: Optional[str] = None
    fecha_envio_proveedor: Optional[str] = None
    fecha_respuesta_proveedor: Optional[str] = None
    estado_proveedor_id: Optional[int] = None
    estado_proveedor_valor: Optional[str] = None
    estado_proveedor_color: Optional[str] = None
    nc_proveedor: Optional[str] = None
    monto_nc_proveedor: Optional[float] = None
    # Observaciones
    observaciones: Optional[str] = None
    # ERP
    rmah_id: Optional[int] = None
    rmad_id: Optional[int] = None
    created_at: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


class CasoCreate(BaseModel):
    cust_id: Optional[int] = None
    cliente_nombre: Optional[str] = None
    cliente_dni: Optional[str] = None
    cliente_numero: Optional[int] = None
    ml_id: Optional[str] = None
    origen: Optional[str] = None
    items: list[ItemCreate] = []


class CasoUpdate(BaseModel):
    estado: Optional[str] = None  # legacy — still accepted but ignored if estado_caso_id is set
    estado_caso_id: Optional[int] = None
    # Flag proceso
    marcado_borrar_pedido: Optional[bool] = None
    # Reclamo ML
    estado_reclamo_ml_id: Optional[int] = None
    cobertura_ml_id: Optional[int] = None
    monto_cubierto: Optional[float] = None
    # Observaciones
    observaciones: Optional[str] = None
    # Auditoría
    corroborar_nc: Optional[str] = None
    fecha_caso: Optional[str] = None


class HistorialResponse(BaseModel):
    id: int
    caso_id: int
    caso_item_id: Optional[int] = None
    campo: str
    valor_anterior: Optional[str] = None
    valor_nuevo: Optional[str] = None
    usuario_id: int
    usuario_nombre: Optional[str] = None
    created_at: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


class CasoResponse(BaseModel):
    id: int
    numero_caso: str
    cust_id: Optional[int] = None
    cliente_nombre: Optional[str] = None
    cliente_dni: Optional[str] = None
    cliente_numero: Optional[int] = None
    ml_id: Optional[str] = None
    origen: Optional[str] = None
    estado: str  # legacy — kept for compat, derived from estado_caso or old column
    estado_caso_id: Optional[int] = None
    estado_caso_valor: Optional[str] = None
    estado_caso_color: Optional[str] = None
    # Flag proceso
    marcado_borrar_pedido: Optional[bool] = None
    # Reclamo ML
    estado_reclamo_ml_id: Optional[int] = None
    estado_reclamo_ml_valor: Optional[str] = None
    estado_reclamo_ml_color: Optional[str] = None
    cobertura_ml_id: Optional[int] = None
    cobertura_ml_valor: Optional[str] = None
    cobertura_ml_color: Optional[str] = None
    monto_cubierto: Optional[float] = None
    # Observaciones
    observaciones: Optional[str] = None
    # Auditoría
    corroborar_nc: Optional[str] = None
    fecha_caso: Optional[str] = None
    # Sistema
    creado_por_id: Optional[int] = None
    creado_por_nombre: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    # Items (solo en detalle)
    items: list[ItemResponse] = []
    total_items: int = 0

    model_config = ConfigDict(from_attributes=True)


class CasoListResponse(BaseModel):
    items: list[CasoResponse]
    total: int
    page: int
    page_size: int
    total_pages: int


# ──────────────────────────────────────────────
# HELPERS
# ──────────────────────────────────────────────


def _check_permiso(db: Session, user: Usuario, permiso: str) -> None:
    """Verifica permiso o lanza 403."""
    svc = PermisosService(db)
    if not svc.tiene_permiso(user, permiso):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No tenés permiso para esta operación",
        )


def _generar_numero_caso(db: Session) -> str:
    """Genera número de caso auto-incremental: RMA-YYYY-NNNN."""
    year = datetime.now(UTC).year
    ultimo_caso = (
        db.query(RmaCaso.numero_caso)
        .filter(RmaCaso.numero_caso.like(f"RMA-{year}-%"))
        .order_by(RmaCaso.id.desc())
        .first()
    )
    if ultimo_caso:
        try:
            seq = int(ultimo_caso[0].split("-")[-1]) + 1
        except (ValueError, IndexError):
            seq = 1
    else:
        seq = 1
    return f"RMA-{year}-{seq:04d}"


def _serialize_item(item: RmaCasoItem) -> dict:
    """Serializa un item con los valores resueltos de sus opciones."""
    return {
        "id": item.id,
        "caso_id": item.caso_id,
        "serial_number": item.serial_number,
        "item_id": item.item_id,
        "is_id": item.is_id,
        "it_transaction": item.it_transaction,
        "ean": item.ean,
        "producto_desc": item.producto_desc,
        "precio": float(item.precio) if item.precio else None,
        "estado_facturacion": item.estado_facturacion,
        "link_ml": item.link_ml,
        # Recepción
        "estado_recepcion_id": item.estado_recepcion_id,
        "estado_recepcion_valor": item.estado_recepcion.valor if item.estado_recepcion else None,
        "estado_recepcion_color": item.estado_recepcion.color if item.estado_recepcion else None,
        "costo_envio": float(item.costo_envio) if item.costo_envio else None,
        "causa_devolucion_id": item.causa_devolucion_id,
        "causa_devolucion_valor": item.causa_devolucion.valor if item.causa_devolucion else None,
        "causa_devolucion_color": item.causa_devolucion.color if item.causa_devolucion else None,
        "recepcion_usuario_id": item.recepcion_usuario_id,
        "recepcion_fecha": item.recepcion_fecha.isoformat() if item.recepcion_fecha else None,
        # Revisión
        "apto_venta_id": item.apto_venta_id,
        "apto_venta_valor": item.apto_venta.valor if item.apto_venta else None,
        "apto_venta_color": item.apto_venta.color if item.apto_venta else None,
        "requirio_reacondicionamiento": item.requirio_reacondicionamiento,
        "estado_revision_id": item.estado_revision_id,
        "estado_revision_valor": item.estado_revision.valor if item.estado_revision else None,
        "estado_revision_color": item.estado_revision.color if item.estado_revision else None,
        "descripcion_falla": item.descripcion_falla,
        "revision_usuario_id": item.revision_usuario_id,
        "revision_fecha": item.revision_fecha.isoformat() if item.revision_fecha else None,
        # Proceso interno
        "estado_proceso_id": item.estado_proceso_id,
        "estado_proceso_valor": item.estado_proceso.valor if item.estado_proceso else None,
        "estado_proceso_color": item.estado_proceso.color if item.estado_proceso else None,
        "deposito_destino_id": item.deposito_destino_id,
        "deposito_destino_valor": None,  # stor_id directo, nombre se resuelve en frontend
        "deposito_destino_color": None,
        "enviado_fisicamente_deposito": item.enviado_fisicamente_deposito,
        "corroborar_nc": item.corroborar_nc,
        "requirio_rma_interno": item.requirio_rma_interno,
        # Devolución parcial
        "requiere_nota_credito": item.requiere_nota_credito,
        "debe_facturarse": item.debe_facturarse,
        # Proveedor
        "supp_id": item.supp_id,
        "proveedor_nombre": item.proveedor_nombre,
        "listo_envio_proveedor": item.listo_envio_proveedor,
        "enviado_proveedor": item.enviado_proveedor,
        "shipping_id": item.shipping_id,
        "fecha_envio_proveedor": (item.fecha_envio_proveedor.isoformat() if item.fecha_envio_proveedor else None),
        "fecha_respuesta_proveedor": (
            item.fecha_respuesta_proveedor.isoformat() if item.fecha_respuesta_proveedor else None
        ),
        "estado_proveedor_id": item.estado_proveedor_id,
        "estado_proveedor_valor": item.estado_proveedor.valor if item.estado_proveedor else None,
        "estado_proveedor_color": item.estado_proveedor.color if item.estado_proveedor else None,
        "nc_proveedor": item.nc_proveedor,
        "monto_nc_proveedor": float(item.monto_nc_proveedor) if item.monto_nc_proveedor else None,
        # Observaciones
        "observaciones": item.observaciones,
        # ERP
        "rmah_id": item.rmah_id,
        "rmad_id": item.rmad_id,
        "created_at": item.created_at.isoformat() if item.created_at else None,
    }


def _serialize_caso(caso: RmaCaso, include_items: bool = True) -> dict:
    """Serializa un caso con sus relaciones."""
    return {
        "id": caso.id,
        "numero_caso": caso.numero_caso,
        "cust_id": caso.cust_id,
        "cliente_nombre": caso.cliente_nombre,
        "cliente_dni": caso.cliente_dni,
        "cliente_numero": caso.cliente_numero,
        "ml_id": caso.ml_id,
        "origen": caso.origen,
        "estado": (caso.estado_caso.valor if caso.estado_caso else caso.estado),
        "estado_caso_id": caso.estado_caso_id,
        "estado_caso_valor": (caso.estado_caso.valor if caso.estado_caso else None),
        "estado_caso_color": (caso.estado_caso.color if caso.estado_caso else None),
        # Flag proceso
        "marcado_borrar_pedido": caso.marcado_borrar_pedido,
        # Reclamo ML
        "estado_reclamo_ml_id": caso.estado_reclamo_ml_id,
        "estado_reclamo_ml_valor": (caso.estado_reclamo_ml.valor if caso.estado_reclamo_ml else None),
        "estado_reclamo_ml_color": (caso.estado_reclamo_ml.color if caso.estado_reclamo_ml else None),
        "cobertura_ml_id": caso.cobertura_ml_id,
        "cobertura_ml_valor": (caso.cobertura_ml.valor if caso.cobertura_ml else None),
        "cobertura_ml_color": (caso.cobertura_ml.color if caso.cobertura_ml else None),
        "monto_cubierto": float(caso.monto_cubierto) if caso.monto_cubierto else None,
        # Observaciones
        "observaciones": caso.observaciones,
        # Auditoría
        "corroborar_nc": caso.corroborar_nc,
        "fecha_caso": caso.fecha_caso.isoformat() if caso.fecha_caso else None,
        # Sistema
        "creado_por_id": caso.creado_por_id,
        "creado_por_nombre": caso.creado_por.nombre if caso.creado_por else None,
        "created_at": caso.created_at.isoformat() if caso.created_at else None,
        "updated_at": caso.updated_at.isoformat() if caso.updated_at else None,
        # Items
        "items": [_serialize_item(i) for i in caso.items] if include_items else [],
        "total_items": len(caso.items) if caso.items else 0,
    }


def _registrar_cambio(
    db: Session,
    caso_id: int,
    campo: str,
    valor_anterior: object,
    valor_nuevo: object,
    usuario_id: int,
    caso_item_id: Optional[int] = None,
) -> None:
    """Registra un cambio en el historial de auditoría."""
    if str(valor_anterior) == str(valor_nuevo):
        return
    historial = RmaCasoHistorial(
        caso_id=caso_id,
        caso_item_id=caso_item_id,
        campo=campo,
        valor_anterior=str(valor_anterior) if valor_anterior is not None else None,
        valor_nuevo=str(valor_nuevo) if valor_nuevo is not None else None,
        usuario_id=usuario_id,
    )
    db.add(historial)


def _build_caso_query(db: Session) -> object:
    """Construye el query base para casos con todas las relaciones precargadas."""
    return db.query(RmaCaso).options(
        selectinload(RmaCaso.items).selectinload(RmaCasoItem.estado_recepcion),
        selectinload(RmaCaso.items).selectinload(RmaCasoItem.causa_devolucion),
        selectinload(RmaCaso.items).selectinload(RmaCasoItem.apto_venta),
        selectinload(RmaCaso.items).selectinload(RmaCasoItem.estado_revision),
        selectinload(RmaCaso.items).selectinload(RmaCasoItem.estado_proceso),
        # deposito_destino: ya no es relationship, se almacena stor_id directamente
        selectinload(RmaCaso.items).selectinload(RmaCasoItem.estado_proveedor),
        selectinload(RmaCaso.estado_caso),
        selectinload(RmaCaso.estado_reclamo_ml),
        selectinload(RmaCaso.cobertura_ml),
        selectinload(RmaCaso.creado_por),
    )


def _build_item_query(db: Session) -> object:
    """Construye el query base para items con todas las relaciones precargadas."""
    return db.query(RmaCasoItem).options(
        selectinload(RmaCasoItem.estado_recepcion),
        selectinload(RmaCasoItem.causa_devolucion),
        selectinload(RmaCasoItem.apto_venta),
        selectinload(RmaCasoItem.estado_revision),
        selectinload(RmaCasoItem.estado_proceso),
        # deposito_destino: ya no es relationship, se almacena stor_id directamente
        selectinload(RmaCasoItem.estado_proveedor),
    )


# ──────────────────────────────────────────────
# OPCIONES (Dropdowns configurables)
# ──────────────────────────────────────────────


@router.get("/opciones", response_model=list[OpcionResponse])
async def listar_opciones(
    categoria: Optional[str] = Query(None, description="Filtrar por categoría"),
    solo_activas: bool = Query(True, description="Solo opciones activas"),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> list[OpcionResponse]:
    """Lista opciones de dropdowns, opcionalmente filtradas por categoría."""
    query = db.query(RmaSeguimientoOpcion)
    if categoria:
        query = query.filter(RmaSeguimientoOpcion.categoria == categoria)
    if solo_activas:
        query = query.filter(RmaSeguimientoOpcion.activo.is_(True))
    return query.order_by(RmaSeguimientoOpcion.categoria, RmaSeguimientoOpcion.orden).all()


@router.get("/opciones/categorias")
async def listar_categorias(
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> list[str]:
    """Lista todas las categorías de opciones disponibles."""
    rows = db.query(RmaSeguimientoOpcion.categoria).distinct().order_by(RmaSeguimientoOpcion.categoria).all()
    return [r[0] for r in rows]


@router.post("/opciones", response_model=OpcionResponse, status_code=status.HTTP_201_CREATED)
async def crear_opcion(
    data: OpcionCreate,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> OpcionResponse:
    """Crea una nueva opción de dropdown. Requiere permiso admin."""
    _check_permiso(db, current_user, "rma.admin_opciones")
    existe = (
        db.query(RmaSeguimientoOpcion)
        .filter(
            RmaSeguimientoOpcion.categoria == data.categoria,
            RmaSeguimientoOpcion.valor == data.valor,
        )
        .first()
    )
    if existe:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Ya existe la opción '{data.valor}' en la categoría '{data.categoria}'",
        )
    opcion = RmaSeguimientoOpcion(
        categoria=data.categoria,
        valor=data.valor,
        orden=data.orden,
        color=data.color,
    )
    db.add(opcion)
    db.commit()
    db.refresh(opcion)
    return opcion


@router.put("/opciones/{opcion_id}", response_model=OpcionResponse)
async def actualizar_opcion(
    opcion_id: int,
    data: OpcionUpdate,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> OpcionResponse:
    """Actualiza una opción de dropdown. Requiere permiso admin."""
    _check_permiso(db, current_user, "rma.admin_opciones")
    opcion = db.query(RmaSeguimientoOpcion).filter(RmaSeguimientoOpcion.id == opcion_id).first()
    if not opcion:
        raise HTTPException(status_code=404, detail="Opción no encontrada")
    update_data = data.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(opcion, key, value)
    db.commit()
    db.refresh(opcion)
    return opcion


# ──────────────────────────────────────────────
# DEPÓSITOS (desde tb_storage del ERP)
# ──────────────────────────────────────────────


@router.get("/depositos", response_model=list[DepositoResponse])
async def listar_depositos(
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> list[DepositoResponse]:
    """Lista depósitos activos desde tb_storage. Para el dropdown de destino."""
    depositos = db.query(TbStorage).filter(TbStorage.stor_disabled.is_(False)).order_by(TbStorage.stor_desc).all()
    return depositos


# ──────────────────────────────────────────────
# CASOS RMA
# ──────────────────────────────────────────────


@router.get("", response_model=CasoListResponse)
async def listar_casos(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    search: Optional[str] = Query(None, description="Buscar por nro caso, cliente, ML ID, serial"),
    estado: Optional[str] = Query(None, description="Filtrar por estado (legacy string)"),
    estado_caso_id: Optional[int] = Query(None, description="Filtrar por estado_caso_id (nuevo)"),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> CasoListResponse:
    """Lista casos RMA con paginación y búsqueda."""
    _check_permiso(db, current_user, "rma.ver")

    query = _build_caso_query(db).filter(RmaCaso.activo == True)  # noqa: E712

    if estado_caso_id:
        query = query.filter(RmaCaso.estado_caso_id == estado_caso_id)
    elif estado:
        # Legacy fallback — filter by old string column
        query = query.filter(RmaCaso.estado == estado)

    if search:
        search_term = f"%{search}%"
        item_caso_ids = (
            db.query(RmaCasoItem.caso_id)
            .filter((RmaCasoItem.serial_number.ilike(search_term)) | (RmaCasoItem.producto_desc.ilike(search_term)))
            .distinct()
            .subquery()
        )
        query = query.filter(
            (RmaCaso.numero_caso.ilike(search_term))
            | (RmaCaso.cliente_nombre.ilike(search_term))
            | (RmaCaso.ml_id.ilike(search_term))
            | (RmaCaso.id.in_(item_caso_ids))
        )

    total = query.count()
    total_pages = (total + page_size - 1) // page_size

    casos = query.order_by(RmaCaso.id.desc()).offset((page - 1) * page_size).limit(page_size).all()

    return CasoListResponse(
        items=[_serialize_caso(c, include_items=True) for c in casos],
        total=total,
        page=page,
        page_size=page_size,
        total_pages=total_pages,
    )


@router.get("/{caso_id}", response_model=CasoResponse)
async def obtener_caso(
    caso_id: int,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> CasoResponse:
    """Obtiene un caso RMA con todos sus items."""
    _check_permiso(db, current_user, "rma.ver")

    caso = _build_caso_query(db).filter(RmaCaso.id == caso_id).first()
    if not caso:
        raise HTTPException(status_code=404, detail="Caso no encontrado")
    return _serialize_caso(caso)


@router.post("", response_model=CasoResponse, status_code=status.HTTP_201_CREATED)
async def crear_caso(
    data: CasoCreate,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> CasoResponse:
    """Crea un nuevo caso RMA con sus items iniciales."""
    _check_permiso(db, current_user, "rma.gestionar")

    if not data.items:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="El caso debe tener al menos un artículo.",
        )

    numero_caso = _generar_numero_caso(db)

    # Resolve default estado_caso_id ("Abierto")
    estado_abierto = (
        db.query(RmaSeguimientoOpcion)
        .filter(
            RmaSeguimientoOpcion.categoria == "estado_caso",
            RmaSeguimientoOpcion.valor == "Abierto",
            RmaSeguimientoOpcion.activo == True,  # noqa: E712
        )
        .first()
    )

    caso = RmaCaso(
        numero_caso=numero_caso,
        cust_id=data.cust_id,
        cliente_nombre=data.cliente_nombre,
        cliente_dni=data.cliente_dni,
        cliente_numero=data.cliente_numero,
        ml_id=data.ml_id,
        origen=data.origen,
        estado="abierto",
        estado_caso_id=estado_abierto.id if estado_abierto else None,
        creado_por_id=current_user.id,
        fecha_caso=datetime.now(UTC).date(),
    )
    db.add(caso)
    db.flush()

    for item_data in data.items:
        item = RmaCasoItem(
            caso_id=caso.id,
            serial_number=item_data.serial_number,
            item_id=item_data.item_id,
            is_id=item_data.is_id,
            it_transaction=item_data.it_transaction,
            ean=item_data.ean,
            producto_desc=item_data.producto_desc,
            precio=item_data.precio,
            estado_facturacion=item_data.estado_facturacion,
            link_ml=item_data.link_ml,
            supp_id=item_data.supp_id,
            proveedor_nombre=item_data.proveedor_nombre,
        )
        db.add(item)

    _registrar_cambio(db, caso.id, "caso_creado", None, numero_caso, current_user.id)

    db.commit()

    return await obtener_caso(caso.id, db, current_user)


@router.put("/{caso_id}", response_model=CasoResponse)
async def actualizar_caso(
    caso_id: int,
    data: CasoUpdate,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> CasoResponse:
    """Actualiza campos a nivel caso (reclamo ML, observaciones, flags)."""
    _check_permiso(db, current_user, "rma.gestionar")

    caso = db.query(RmaCaso).filter(RmaCaso.id == caso_id).first()
    if not caso:
        raise HTTPException(status_code=404, detail="Caso no encontrado")

    update_data = data.model_dump(exclude_unset=True)

    for key, value in update_data.items():
        old_value = getattr(caso, key)
        if key == "fecha_caso" and isinstance(value, str):
            from datetime import date

            try:
                value = date.fromisoformat(value)
            except ValueError:
                pass
        setattr(caso, key, value)
        _registrar_cambio(db, caso_id, key, old_value, value, current_user.id)

    db.commit()
    return await obtener_caso(caso_id, db, current_user)


# ──────────────────────────────────────────────
# ITEMS DEL CASO
# ──────────────────────────────────────────────


@router.post("/{caso_id}/items", response_model=ItemResponse, status_code=status.HTTP_201_CREATED)
async def agregar_item(
    caso_id: int,
    data: ItemCreate,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> ItemResponse:
    """Agrega un artículo a un caso existente."""
    _check_permiso(db, current_user, "rma.gestionar")

    caso = db.query(RmaCaso).filter(RmaCaso.id == caso_id).first()
    if not caso:
        raise HTTPException(status_code=404, detail="Caso no encontrado")

    item = RmaCasoItem(
        caso_id=caso_id,
        serial_number=data.serial_number,
        item_id=data.item_id,
        is_id=data.is_id,
        it_transaction=data.it_transaction,
        ean=data.ean,
        producto_desc=data.producto_desc,
        precio=data.precio,
        estado_facturacion=data.estado_facturacion,
        link_ml=data.link_ml,
        supp_id=data.supp_id,
        proveedor_nombre=data.proveedor_nombre,
    )
    db.add(item)
    db.flush()

    _registrar_cambio(
        db,
        caso_id,
        "item_agregado",
        None,
        data.producto_desc or data.serial_number,
        current_user.id,
        caso_item_id=item.id,
    )
    db.commit()

    item = _build_item_query(db).filter(RmaCasoItem.id == item.id).first()
    return _serialize_item(item)


@router.put("/{caso_id}/items/{item_id}", response_model=ItemResponse)
async def actualizar_item(
    caso_id: int,
    item_id: int,
    data: ItemUpdate,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> ItemResponse:
    """Actualiza un artículo del caso (recepción, revisión, proceso, proveedor)."""
    _check_permiso(db, current_user, "rma.gestionar")

    item = db.query(RmaCasoItem).filter(RmaCasoItem.id == item_id, RmaCasoItem.caso_id == caso_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Item no encontrado en este caso")

    update_data = data.model_dump(exclude_unset=True)
    now = datetime.now(UTC)

    for key, value in update_data.items():
        old_value = getattr(item, key)

        if key in ("fecha_envio_proveedor", "fecha_respuesta_proveedor") and isinstance(value, str):
            try:
                value = datetime.fromisoformat(value)
            except ValueError:
                pass

        setattr(item, key, value)
        _registrar_cambio(db, caso_id, key, old_value, value, current_user.id, caso_item_id=item_id)

    # Auto-set usuario y fecha de etapa si corresponde
    if "estado_recepcion_id" in update_data and not item.recepcion_usuario_id:
        item.recepcion_usuario_id = current_user.id
        item.recepcion_fecha = now
    if "estado_revision_id" in update_data and not item.revision_usuario_id:
        item.revision_usuario_id = current_user.id
        item.revision_fecha = now

    db.commit()

    item = _build_item_query(db).filter(RmaCasoItem.id == item_id).first()
    return _serialize_item(item)


@router.delete("/{caso_id}/items/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
async def eliminar_item(
    caso_id: int,
    item_id: int,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> None:
    """Elimina un artículo de un caso."""
    _check_permiso(db, current_user, "rma.gestionar")

    item = db.query(RmaCasoItem).filter(RmaCasoItem.id == item_id, RmaCasoItem.caso_id == caso_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Item no encontrado en este caso")

    _registrar_cambio(
        db,
        caso_id,
        "item_eliminado",
        item.producto_desc or item.serial_number,
        None,
        current_user.id,
        caso_item_id=item_id,
    )
    db.delete(item)
    db.commit()


# ──────────────────────────────────────────────
# SOFT DELETE (Caso completo)
# ──────────────────────────────────────────────


class EliminarCasoBody(BaseModel):
    motivo: Optional[str] = Field(None, max_length=500)


@router.delete("/{caso_id}", status_code=status.HTTP_200_OK)
async def eliminar_caso(
    caso_id: int,
    body: EliminarCasoBody = EliminarCasoBody(),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> dict:
    """Soft-delete de un caso RMA. Marca activo=False y registra auditoría."""
    _check_permiso(db, current_user, "rma.eliminar")

    caso = db.query(RmaCaso).filter(RmaCaso.id == caso_id).first()
    if not caso:
        raise HTTPException(status_code=404, detail="Caso no encontrado")

    if not caso.activo:
        raise HTTPException(status_code=400, detail="El caso ya fue eliminado")

    # Registrar en historial ANTES de marcar como inactivo
    motivo = body.motivo or "Sin motivo"
    _registrar_cambio(
        db,
        caso_id,
        "caso_eliminado",
        caso.numero_caso,
        f"Eliminado: {motivo}",
        current_user.id,
    )

    # Soft delete
    caso.activo = False
    caso.eliminado_por_id = current_user.id
    caso.eliminado_at = datetime.now(UTC)
    caso.eliminado_motivo = motivo

    db.commit()

    return {"ok": True, "numero_caso": caso.numero_caso}


# ──────────────────────────────────────────────
# HISTORIAL (Auditoría)
# ──────────────────────────────────────────────


@router.get("/{caso_id}/historial", response_model=list[HistorialResponse])
async def obtener_historial(
    caso_id: int,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> list[HistorialResponse]:
    """Obtiene el historial completo de cambios de un caso."""
    _check_permiso(db, current_user, "rma.ver")

    registros = (
        db.query(RmaCasoHistorial)
        .options(selectinload(RmaCasoHistorial.usuario))
        .filter(RmaCasoHistorial.caso_id == caso_id)
        .order_by(RmaCasoHistorial.created_at.desc())
        .all()
    )
    return [
        {
            "id": r.id,
            "caso_id": r.caso_id,
            "caso_item_id": r.caso_item_id,
            "campo": r.campo,
            "valor_anterior": r.valor_anterior,
            "valor_nuevo": r.valor_nuevo,
            "usuario_id": r.usuario_id,
            "usuario_nombre": r.usuario.nombre if r.usuario else None,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in registros
    ]


# ──────────────────────────────────────────────
# ESTADÍSTICAS (para el dashboard del encargado)
# ──────────────────────────────────────────────


@router.get("/stats/resumen")
async def obtener_resumen(
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> dict:
    """Resumen rápido: casos abiertos, cerrados, por estado."""
    _check_permiso(db, current_user, "rma.ver")

    base = db.query(func.count(RmaCaso.id)).filter(RmaCaso.activo == True)  # noqa: E712
    total = base.scalar()

    # Dynamic per-state counts
    from sqlalchemy.orm import aliased

    EstadoOpc = aliased(RmaSeguimientoOpcion)
    por_estado = (
        db.query(
            EstadoOpc.id,
            EstadoOpc.valor,
            EstadoOpc.color,
            func.count(RmaCaso.id).label("cantidad"),
        )
        .join(RmaCaso, RmaCaso.estado_caso_id == EstadoOpc.id)
        .filter(
            RmaCaso.activo == True,  # noqa: E712
            EstadoOpc.categoria == "estado_caso",
            EstadoOpc.activo == True,  # noqa: E712
        )
        .group_by(EstadoOpc.id, EstadoOpc.valor, EstadoOpc.color)
        .order_by(EstadoOpc.id)
        .all()
    )

    # Legacy compat fields
    abiertos = sum(r.cantidad for r in por_estado if r.valor == "Abierto")
    cerrados = sum(r.cantidad for r in por_estado if r.valor == "Cerrado")

    top_causas = (
        db.query(
            RmaSeguimientoOpcion.valor,
            func.count(RmaCasoItem.id).label("cantidad"),
        )
        .join(RmaCasoItem, RmaCasoItem.causa_devolucion_id == RmaSeguimientoOpcion.id)
        .join(RmaCaso, RmaCasoItem.caso_id == RmaCaso.id)
        .filter(RmaCaso.activo == True)  # noqa: E712
        .group_by(RmaSeguimientoOpcion.valor)
        .order_by(func.count(RmaCasoItem.id).desc())
        .limit(10)
        .all()
    )

    return {
        "total": total,
        "abiertos": abiertos,
        "cerrados": cerrados,
        "por_estado": [{"id": r.id, "valor": r.valor, "color": r.color, "cantidad": r.cantidad} for r in por_estado],
        "top_causas_devolucion": [{"causa": r[0], "cantidad": r[1]} for r in top_causas],
    }


# ──────────────────────────────────────────────
# ENVÍOS A PROVEEDOR (items agrupados por proveedor)
# ──────────────────────────────────────────────


def _serialize_proveedor(prov: Optional[RmaProveedor], fallback_nombre: Optional[str]) -> dict:
    """Serializa datos del proveedor para envíos."""
    if not prov:
        return {"id": None, "nombre": fallback_nombre}
    return {
        "id": prov.id,
        "nombre": prov.nombre,
        "direccion": prov.direccion,
        "cp": prov.cp,
        "ciudad": prov.ciudad,
        "provincia": prov.provincia,
        "telefono": prov.telefono,
        "email": prov.email,
        "representante": prov.representante,
        "horario": prov.horario,
        "unidades_minimas_rma": prov.unidades_minimas_rma,
    }


@router.get("/envios-proveedor/pendientes")
async def listar_items_envio_proveedor(
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> list:
    """Items pendientes de envío a proveedor, agrupados por supp_id.

    Incluye items que tienen supp_id seteado y enviado_proveedor != true,
    de casos activos. Cada grupo trae datos del proveedor desde rma_proveedores.
    """
    _check_permiso(db, current_user, "rma.ver")

    # Items with supp_id set, not yet sent, from active cases
    items = (
        _build_item_query(db)
        .join(RmaCaso, RmaCasoItem.caso_id == RmaCaso.id)
        .filter(
            RmaCaso.activo == True,  # noqa: E712
            RmaCasoItem.supp_id.isnot(None),
            (RmaCasoItem.enviado_proveedor.is_(None)) | (RmaCasoItem.enviado_proveedor == False),  # noqa: E712
        )
        .order_by(RmaCasoItem.supp_id, RmaCasoItem.id)
        .all()
    )

    # Group by supp_id
    from collections import defaultdict

    groups: dict = defaultdict(list)
    caso_cache: dict = {}
    for item in items:
        groups[item.supp_id].append(item)
        if item.caso_id not in caso_cache:
            caso_cache[item.caso_id] = item.caso

    # Fetch supplier extended data
    supp_ids = list(groups.keys())
    proveedores = {
        p.supp_id: p
        for p in db.query(RmaProveedor)
        .filter(RmaProveedor.supp_id.in_(supp_ids), RmaProveedor.activo == True)  # noqa: E712
        .all()
    }

    result = []
    for supp_id, supp_items in groups.items():
        prov = proveedores.get(supp_id)
        result.append(
            {
                "supp_id": supp_id,
                "proveedor_nombre": supp_items[0].proveedor_nombre,
                "proveedor": _serialize_proveedor(prov, supp_items[0].proveedor_nombre),
                "cantidad_items": len(supp_items),
                "items": [
                    {
                        "id": i.id,
                        "caso_id": i.caso_id,
                        "numero_caso": caso_cache.get(i.caso_id).numero_caso if caso_cache.get(i.caso_id) else None,
                        "serial_number": i.serial_number,
                        "producto_desc": i.producto_desc,
                        "ean": i.ean,
                        "precio": float(i.precio) if i.precio else None,
                        "descripcion_falla": i.descripcion_falla,
                        "listo_envio_proveedor": i.listo_envio_proveedor or False,
                        "estado_proveedor_valor": i.estado_proveedor.valor if i.estado_proveedor else None,
                        "estado_proveedor_color": i.estado_proveedor.color if i.estado_proveedor else None,
                    }
                    for i in supp_items
                ],
            }
        )

    # Sort by quantity desc (biggest groups first)
    result.sort(key=lambda g: g["cantidad_items"], reverse=True)

    return result


# ──────────────────────────────────────────────
# CREAR ENVÍO A PROVEEDOR (EtiquetaEnvio + link items)
# ──────────────────────────────────────────────


class CrearEnvioProveedorRequest(BaseModel):
    """Crea un envío manual a proveedor y vincula los items RMA seleccionados."""

    supp_id: int = Field(description="ID del proveedor (tb_supplier.supp_id)")
    item_ids: list[int] = Field(min_length=1, description="IDs de rma_caso_items a incluir")
    fecha_envio: date = Field(description="Fecha programada del envío")
    comment: Optional[str] = Field(None, max_length=1000, description="Observaciones del envío")


class CrearEnvioProveedorResponse(BaseModel):
    ok: bool = True
    shipping_id: str
    items_vinculados: int
    mensaje: str


@router.post("/envios-proveedor/crear-envio", response_model=CrearEnvioProveedorResponse)
async def crear_envio_proveedor(
    data: CrearEnvioProveedorRequest,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> CrearEnvioProveedorResponse:
    """Crea un envío manual a proveedor y vincula los items RMA.

    1. Valida que todos los items pertenezcan al supp_id indicado y no estén ya enviados
    2. Obtiene datos del proveedor desde rma_proveedores para llenar dirección
    3. Crea un EtiquetaEnvio manual (es_manual=True)
    4. Vincula cada item con shipping_id, marca enviado_proveedor=True, fecha_envio_proveedor=now
    5. Registra cambios en historial de auditoría de cada caso afectado
    """
    _check_permiso(db, current_user, "rma.gestionar")

    # 1. Fetch and validate items
    items = (
        db.query(RmaCasoItem)
        .join(RmaCaso, RmaCasoItem.caso_id == RmaCaso.id)
        .filter(
            RmaCasoItem.id.in_(data.item_ids),
            RmaCaso.activo == True,  # noqa: E712
        )
        .all()
    )

    if len(items) != len(data.item_ids):
        found_ids = {i.id for i in items}
        missing = [iid for iid in data.item_ids if iid not in found_ids]
        raise HTTPException(status_code=404, detail=f"Items no encontrados o de casos inactivos: {missing}")

    # Validate all belong to the same supplier and not yet shipped
    for item in items:
        if item.supp_id != data.supp_id:
            raise HTTPException(
                status_code=400,
                detail=f"Item {item.id} pertenece a proveedor {item.supp_id}, no a {data.supp_id}",
            )
        if item.enviado_proveedor and item.shipping_id:
            raise HTTPException(
                status_code=400,
                detail=f"Item {item.id} ya fue enviado (shipping_id={item.shipping_id})",
            )

    # 2. Get supplier extended data for address
    prov = (
        db.query(RmaProveedor)
        .filter(RmaProveedor.supp_id == data.supp_id, RmaProveedor.activo == True)  # noqa: E712
        .first()
    )

    receiver_name = prov.nombre if prov else items[0].proveedor_nombre or f"Proveedor #{data.supp_id}"
    street_name = prov.direccion if prov else "S/D"
    zip_code = prov.cp if prov else "0000"
    city_name = prov.ciudad if prov else "S/D"
    phone = prov.telefono if prov else None

    # 3. Create EtiquetaEnvio manual
    now = datetime.now(UTC)
    seq = db.query(func.count(EtiquetaEnvio.id)).filter(EtiquetaEnvio.es_manual == True).scalar() or 0  # noqa: E712
    shipping_id = f"RMA_{now.strftime('%Y%m%d%H%M%S')}_{seq + 1}"

    envio = EtiquetaEnvio(
        shipping_id=shipping_id,
        fecha_envio=data.fecha_envio,
        es_manual=True,
        manual_receiver_name=receiver_name,
        manual_street_name=street_name,
        manual_street_number="S/N",
        manual_zip_code=zip_code,
        manual_city_name=city_name,
        manual_phone=phone,
        manual_status="ready_to_ship",
        manual_comment=data.comment or f"RMA a proveedor: {receiver_name} ({len(items)} items)",
        creado_por_usuario_id=current_user.id,
    )
    db.add(envio)
    db.flush()  # Ensure shipping_id is persisted before linking items

    # 4. Link items and mark as shipped
    for item in items:
        old_enviado = item.enviado_proveedor
        old_shipping = item.shipping_id
        old_fecha = item.fecha_envio_proveedor

        item.shipping_id = shipping_id
        item.enviado_proveedor = True
        item.fecha_envio_proveedor = now

        _registrar_cambio(
            db, item.caso_id, "shipping_id", old_shipping, shipping_id, current_user.id, caso_item_id=item.id
        )
        _registrar_cambio(
            db, item.caso_id, "enviado_proveedor", old_enviado, True, current_user.id, caso_item_id=item.id
        )
        _registrar_cambio(
            db,
            item.caso_id,
            "fecha_envio_proveedor",
            old_fecha,
            now.isoformat(),
            current_user.id,
            caso_item_id=item.id,
        )

    db.commit()

    return CrearEnvioProveedorResponse(
        shipping_id=shipping_id,
        items_vinculados=len(items),
        mensaje=f"Envío {shipping_id} creado con {len(items)} items a {receiver_name}",
    )
