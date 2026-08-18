"""
Router: Administración — Proveedores.

Endpoints:
  GET    /administracion/proveedores              — listar (con búsqueda y paginación)
  GET    /administracion/proveedores/{id}          — detalle (con datos fiscales)
  POST   /administracion/proveedores               — crear proveedor manual
  PUT    /administracion/proveedores/{id}          — actualizar datos
  POST   /administracion/proveedores/sync-erp      — sincronizar desde el ERP (GBP)
  POST   /administracion/proveedores/{id}/consultar-afip — consultar Padrón A4
  GET    /administracion/proveedores/{id}/datos-fiscales — ver datos fiscales cacheados
"""

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.core.database import get_db, get_async_db, get_background_db
from app.core.logging import get_logger
from app.core.sse import sse_publish
from app.api.deps import get_current_user
from app.models.usuario import Usuario
from app.services.permisos_service import PermisosService
from app.services.proveedores_service import ErpSyncError, ProveedoresService
from app.services.afip_service import AfipServiceError

logger = get_logger(__name__)

router = APIRouter(prefix="/administracion/proveedores", tags=["Administración - Proveedores"])

# Canal SSE por el que el sync full publica su resultado. Registrado en
# `app/routers/sse.py::VALID_CHANNELS` (sin eso el frontend no puede suscribirse).
SYNC_ERP_CHANNEL = "proveedores:sync"


# =============================================================================
# SCHEMAS
# =============================================================================


class DatosFiscalesResponse(BaseModel):
    """Datos fiscales cacheados de AFIP."""

    id: int
    proveedor_id: int
    condicion_iva: Optional[str] = None
    inscripto_ganancias: Optional[bool] = None
    estado_clave: Optional[str] = None
    tipo_persona: Optional[str] = None
    forma_juridica: Optional[str] = None
    razon_social_afip: Optional[str] = None
    actividad_principal: Optional[str] = None
    actividad_principal_id: Optional[int] = None
    domicilio_fiscal: Optional[str] = None
    domicilio_fiscal_cp: Optional[str] = None
    domicilio_fiscal_provincia: Optional[str] = None
    domicilio_fiscal_localidad: Optional[str] = None
    cuit_consultado: Optional[str] = None
    ultima_consulta_afip: Optional[datetime] = None
    ultimo_error_afip: Optional[str] = None
    wsid_consultado: Optional[str] = None
    # Regímenes e impuestos extraídos del raw (para la UI)
    impuestos: Optional[list[dict]] = None
    regimenes: Optional[list[dict]] = None

    model_config = ConfigDict(from_attributes=True)


class ProveedorResponse(BaseModel):
    """Proveedor con datos fiscales resumidos."""

    id: int
    supp_id: Optional[int] = None
    comp_id: Optional[int] = None
    nombre: str
    cuit: Optional[str] = None
    origen: str
    direccion: Optional[str] = None
    cp: Optional[str] = None
    ciudad: Optional[str] = None
    provincia: Optional[str] = None
    telefono: Optional[str] = None
    email: Optional[str] = None
    representante: Optional[str] = None
    notas: Optional[str] = None
    activo: bool = True
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    # Resumen fiscal (del cache AFIP)
    condicion_iva: Optional[str] = None
    inscripto_ganancias: Optional[bool] = None
    estado_clave: Optional[str] = None
    ultima_consulta_afip: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class DireccionResponse(BaseModel):
    id: int
    proveedor_id: int
    etiqueta: str
    direccion: str
    cp: Optional[str] = None
    ciudad: Optional[str] = None
    provincia: Optional[str] = None
    horario_recepcion: Optional[str] = None
    contacto_nombre: Optional[str] = None
    contacto_telefono: Optional[str] = None
    notas: Optional[str] = None
    origen: str = "manual"
    activo: bool = True

    model_config = ConfigDict(from_attributes=True)


class BancoResponse(BaseModel):
    id: int
    proveedor_id: int
    banco: str
    tipo_cuenta: Optional[str] = None
    cbu: Optional[str] = None
    alias: Optional[str] = None
    numero_cuenta: Optional[str] = None
    sucursal: Optional[str] = None
    titular: Optional[str] = None
    cuit_titular: Optional[str] = None
    moneda: Optional[str] = "ARS"
    notas: Optional[str] = None
    activo: bool = True

    model_config = ConfigDict(from_attributes=True)


class ContactoResponse(BaseModel):
    id: int
    proveedor_id: int
    nombre: str
    rol: Optional[str] = None
    telefono: Optional[str] = None
    email: Optional[str] = None
    cargo: Optional[str] = None
    notas: Optional[str] = None
    activo: bool = True

    model_config = ConfigDict(from_attributes=True)


class MarcaProveedorResponse(BaseModel):
    """Marca que le compramos a un proveedor (extraída de compras)."""

    brand_id: int
    marca: str
    ultima_compra: Optional[datetime] = None
    cantidad_compras: int = 0


class ProveedorDetalleResponse(ProveedorResponse):
    """Proveedor con datos fiscales completos y sub-entidades."""

    datos_fiscales: Optional[DatosFiscalesResponse] = None
    direcciones: list[DireccionResponse] = []
    bancos: list[BancoResponse] = []
    contactos: list[ContactoResponse] = []


class ProveedorCreate(BaseModel):
    """Crear proveedor manualmente."""

    nombre: str = Field(min_length=1, max_length=255)
    cuit: Optional[str] = Field(None, max_length=20)
    direccion: Optional[str] = Field(None, max_length=500)
    cp: Optional[str] = Field(None, max_length=20)
    ciudad: Optional[str] = Field(None, max_length=255)
    provincia: Optional[str] = Field(None, max_length=255)
    telefono: Optional[str] = Field(None, max_length=100)
    email: Optional[str] = Field(None, max_length=255)
    representante: Optional[str] = Field(None, max_length=255)
    notas: Optional[str] = None


class ProveedorUpdate(BaseModel):
    """Actualizar datos de proveedor."""

    nombre: Optional[str] = Field(None, min_length=1, max_length=255)
    cuit: Optional[str] = Field(None, max_length=20)
    direccion: Optional[str] = Field(None, max_length=500)
    cp: Optional[str] = Field(None, max_length=20)
    ciudad: Optional[str] = Field(None, max_length=255)
    provincia: Optional[str] = Field(None, max_length=255)
    telefono: Optional[str] = Field(None, max_length=100)
    email: Optional[str] = Field(None, max_length=255)
    representante: Optional[str] = Field(None, max_length=255)
    notas: Optional[str] = None
    activo: Optional[bool] = None


class DireccionCreate(BaseModel):
    etiqueta: str = Field(min_length=1, max_length=100)
    direccion: str = Field(min_length=1, max_length=500)
    cp: Optional[str] = Field(None, max_length=20)
    ciudad: Optional[str] = Field(None, max_length=255)
    provincia: Optional[str] = Field(None, max_length=255)
    horario_recepcion: Optional[str] = Field(None, max_length=255)
    contacto_nombre: Optional[str] = Field(None, max_length=255)
    contacto_telefono: Optional[str] = Field(None, max_length=100)
    notas: Optional[str] = None


class BancoCreate(BaseModel):
    banco: str = Field(min_length=1, max_length=255)
    tipo_cuenta: Optional[str] = Field(None, max_length=50)
    cbu: Optional[str] = Field(None, max_length=30)
    alias: Optional[str] = Field(None, max_length=100)
    numero_cuenta: Optional[str] = Field(None, max_length=50)
    sucursal: Optional[str] = Field(None, max_length=100)
    titular: Optional[str] = Field(None, max_length=255)
    cuit_titular: Optional[str] = Field(None, max_length=20)
    moneda: Optional[str] = Field("ARS", max_length=10)
    notas: Optional[str] = None


class ContactoCreate(BaseModel):
    nombre: str = Field(min_length=1, max_length=255)
    rol: Optional[str] = Field(None, max_length=100)
    telefono: Optional[str] = Field(None, max_length=100)
    email: Optional[str] = Field(None, max_length=255)
    cargo: Optional[str] = Field(None, max_length=255)
    notas: Optional[str] = None


class ProveedorListResponse(BaseModel):
    proveedores: list[ProveedorResponse]
    total: int
    page: int
    page_size: int


# =============================================================================
# HELPERS
# =============================================================================


def _check_permiso(db: Session, user: Usuario, permiso: str) -> None:
    svc = PermisosService(db)
    if not svc.tiene_permiso(user, permiso):
        raise HTTPException(status_code=403, detail=f"Sin permiso: {permiso}")


# Permisos que habilitan la LECTURA de proveedores. El buscador de proveedor del
# módulo Compras (modal de pedido) necesita esto: quien ve/gestiona órdenes de
# compra debe poder buscar proveedores sin tener el permiso de la sección
# Administración → Proveedores.
_PERMISOS_LECTURA_PROVEEDOR: tuple[str, ...] = (
    "administracion.ver_proveedores",
    "administracion.ver_ordenes_compra",
    "administracion.gestionar_ordenes_compra",
)


def _check_permiso_lectura_proveedor(db: Session, user: Usuario) -> None:
    """403 salvo que el usuario tenga alguno de los permisos de lectura de proveedor."""
    svc = PermisosService(db)
    if not any(svc.tiene_permiso(user, p) for p in _PERMISOS_LECTURA_PROVEEDOR):
        raise HTTPException(
            status_code=403,
            detail=f"Sin permiso: requiere uno de {list(_PERMISOS_LECTURA_PROVEEDOR)}",
        )


def _proveedor_to_response(prov: object) -> ProveedorResponse:
    """Convierte un Proveedor ORM a ProveedorResponse con resumen fiscal."""
    datos = getattr(prov, "datos_fiscales", None)
    return ProveedorResponse(
        id=prov.id,
        supp_id=prov.supp_id,
        comp_id=prov.comp_id,
        nombre=prov.nombre,
        cuit=prov.cuit,
        origen=prov.origen,
        direccion=prov.direccion,
        cp=prov.cp,
        ciudad=prov.ciudad,
        provincia=prov.provincia,
        telefono=prov.telefono,
        email=prov.email,
        representante=prov.representante,
        notas=prov.notas,
        activo=prov.activo,
        created_at=prov.created_at,
        updated_at=prov.updated_at,
        condicion_iva=datos.condicion_iva if datos else None,
        inscripto_ganancias=datos.inscripto_ganancias if datos else None,
        estado_clave=datos.estado_clave if datos else None,
        ultima_consulta_afip=datos.ultima_consulta_afip if datos else None,
    )


def _datos_fiscales_to_response(datos: object) -> DatosFiscalesResponse:
    """Convierte ProveedorDatosFiscales ORM a response con impuestos/regímenes."""
    raw = getattr(datos, "padron_a4_raw", None) or {}
    impuestos = raw.get("impuesto", [])
    regimenes = raw.get("regimen", [])

    return DatosFiscalesResponse(
        id=datos.id,
        proveedor_id=datos.proveedor_id,
        condicion_iva=datos.condicion_iva,
        inscripto_ganancias=datos.inscripto_ganancias,
        estado_clave=datos.estado_clave,
        tipo_persona=datos.tipo_persona,
        forma_juridica=datos.forma_juridica,
        razon_social_afip=datos.razon_social_afip,
        actividad_principal=datos.actividad_principal,
        actividad_principal_id=datos.actividad_principal_id,
        domicilio_fiscal=datos.domicilio_fiscal,
        domicilio_fiscal_cp=datos.domicilio_fiscal_cp,
        domicilio_fiscal_provincia=datos.domicilio_fiscal_provincia,
        domicilio_fiscal_localidad=datos.domicilio_fiscal_localidad,
        cuit_consultado=datos.cuit_consultado,
        ultima_consulta_afip=datos.ultima_consulta_afip,
        ultimo_error_afip=datos.ultimo_error_afip,
        wsid_consultado=datos.wsid_consultado,
        impuestos=impuestos,
        regimenes=regimenes,
    )


# =============================================================================
# ENDPOINTS
# =============================================================================


@router.get("", response_model=ProveedorListResponse)
def listar_proveedores(
    search: Optional[str] = Query(None, description="Buscar por nombre, CUIT o ciudad"),
    solo_activos: bool = Query(True, description="Solo proveedores activos"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> ProveedorListResponse:
    """Lista proveedores con búsqueda y paginación."""
    _check_permiso_lectura_proveedor(db, current_user)

    svc = ProveedoresService(db)
    proveedores, total = svc.listar(
        search=search,
        solo_activos=solo_activos,
        page=page,
        page_size=page_size,
    )

    return ProveedorListResponse(
        proveedores=[_proveedor_to_response(p) for p in proveedores],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/{proveedor_id}", response_model=ProveedorDetalleResponse)
def obtener_proveedor(
    proveedor_id: int,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> ProveedorDetalleResponse:
    """Obtiene un proveedor con sus datos fiscales completos."""
    # El autocomplete de compras precarga el proveedor por id al editar un pedido.
    _check_permiso_lectura_proveedor(db, current_user)

    svc = ProveedoresService(db)
    prov = svc.obtener(proveedor_id)
    if not prov:
        raise HTTPException(status_code=404, detail="Proveedor no encontrado")

    datos = getattr(prov, "datos_fiscales", None)
    base = _proveedor_to_response(prov)

    # Sub-entidades: solo activas
    direcciones_activas = [d for d in (prov.direcciones or []) if d.activo]
    bancos_activos = [b for b in (prov.bancos or []) if b.activo]
    contactos_activos = [c for c in (prov.contactos or []) if c.activo]

    return ProveedorDetalleResponse(
        **base.model_dump(),
        datos_fiscales=_datos_fiscales_to_response(datos) if datos else None,
        direcciones=[DireccionResponse.model_validate(d) for d in direcciones_activas],
        bancos=[BancoResponse.model_validate(b) for b in bancos_activos],
        contactos=[ContactoResponse.model_validate(c) for c in contactos_activos],
    )


@router.post("", response_model=ProveedorResponse, status_code=status.HTTP_201_CREATED)
def crear_proveedor(
    data: ProveedorCreate,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> ProveedorResponse:
    """Crea un proveedor manualmente."""
    _check_permiso(db, current_user, "administracion.gestionar_proveedores")

    svc = ProveedoresService(db)

    # Verificar CUIT duplicado
    if data.cuit:
        existing = svc.obtener_por_cuit(data.cuit)
        if existing:
            raise HTTPException(
                status_code=409,
                detail=f"Ya existe un proveedor con CUIT {data.cuit}: {existing.nombre}",
            )

    prov = svc.crear(**data.model_dump(exclude_unset=True))
    db.commit()
    db.refresh(prov)

    return _proveedor_to_response(prov)


@router.put("/{proveedor_id}", response_model=ProveedorResponse)
def actualizar_proveedor(
    proveedor_id: int,
    data: ProveedorUpdate,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> ProveedorResponse:
    """Actualiza datos de un proveedor."""
    _check_permiso(db, current_user, "administracion.gestionar_proveedores")

    svc = ProveedoresService(db)

    # Si cambia el CUIT, verificar duplicado
    update_data = data.model_dump(exclude_unset=True)
    new_cuit = update_data.get("cuit")
    if new_cuit:
        existing = svc.obtener_por_cuit(new_cuit)
        if existing and existing.id != proveedor_id:
            raise HTTPException(
                status_code=409,
                detail=f"Ya existe un proveedor con CUIT {new_cuit}: {existing.nombre}",
            )

    prov = svc.actualizar(proveedor_id, update_data)
    if not prov:
        raise HTTPException(status_code=404, detail="Proveedor no encontrado")

    db.commit()
    db.refresh(prov)

    return _proveedor_to_response(prov)


async def _publicar_resultado_sync(payload: dict) -> None:
    """
    Publica el resultado del sync full en el canal SSE `proveedores:sync`.

    Se usa `sse_publish` (la variante async) y no `sse_publish_bg` porque el job
    de background es `async def`: FastAPI lo corre en el event loop principal,
    que es exactamente donde `sse_publish` necesita estar. `sse_publish_bg` solo
    existe para saltar desde un thread del threadpool al event loop.

    Fail-soft por contrato: `sse_publish` ya se traga los errores de Redis y, si
    Redis nunca se configuró (`set_redis`), solo loguea un warning y retorna. El
    try/except adicional protege de que un refactor futuro allí tire abajo un
    sync que YA commiteó: la notificación es un aviso, nunca un motivo para
    perder el resultado.
    """
    try:
        await sse_publish(SYNC_ERP_CHANNEL, payload)
    except Exception:  # noqa: BLE001 — SSE es best-effort, nunca rompe el sync.
        logger.warning(
            "Sync proveedores ERP: falló la publicación SSE (canal=%s)",
            SYNC_ERP_CHANNEL,
            exc_info=True,
        )


async def _sync_proveedores_erp_background() -> None:
    """
    Job de background del sync FULL de proveedores contra el ERP (GBP).

    Vive acá y no en el servicio a propósito: es orquestación de transporte
    (ciclo de vida de la sesión + notificación al panel), no lógica de dominio.
    `ProveedoresService.sync_desde_erp()` sigue siendo la cadena canónica y la
    comparte con el cron (`app.scripts.sync_suppliers`), que no debe arrastrar
    una dependencia de Redis/SSE.

    Abre su PROPIA sesión con `get_background_db()`: la sesión del endpoint ya
    está cerrada cuando esta tarea corre (la respuesta 202 se envió antes).
    La sesión no toma una conexión del pool hasta el primer query, así que la
    llamada HTTP al ERP no retiene conexión.

    Nunca levanta: el resultado (contadores o error) se publica por SSE y se
    loguea. Una excepción acá quedaría huérfana en el task de Starlette.
    """
    try:
        with get_background_db() as db:
            result = await ProveedoresService(db).sync_desde_erp()
    except ErpSyncError as e:
        logger.warning("Sync proveedores ERP (background): el ERP no devolvió datos utilizables — %s", e)
        await _publicar_resultado_sync({"success": False, "error": str(e)})
        return
    except Exception as e:  # noqa: BLE001 — el job no puede propagar nada.
        logger.exception("Sync proveedores ERP (background): error inesperado")
        await _publicar_resultado_sync({"success": False, "error": f"Error inesperado en el sync: {e}"})
        return

    logger.info(
        "Sync proveedores ERP (background) finalizado: total_erp=%d, insertados=%d, actualizados=%d, "
        "rma_insertados=%d, vinculados_rma=%d",
        result["total_erp"],
        result["insertados"],
        result["actualizados"],
        result["rma_insertados"],
        result["vinculados_rma"],
    )
    await _publicar_resultado_sync({"success": True, **result})


@router.post(
    "/sync-erp",
    status_code=status.HTTP_200_OK,
    responses={
        202: {"description": "Sync full encolado; el resultado llega por SSE (canal `proveedores:sync`)"},
        502: {"description": "El ERP falló o no devolvió datos (solo en el camino sincrónico con `supp_id`)"},
    },
)
async def sync_proveedores_erp(
    background_tasks: BackgroundTasks,
    response: Response,
    supp_id: Optional[int] = Query(None, description="ID de proveedor del ERP a sincronizar (opcional)"),
    db: Session = Depends(get_async_db),
    current_user: Usuario = Depends(get_current_user),
) -> dict:
    """
    Sincroniza proveedores contra el ERP (GBP). Tiene dos caminos:

    1. Con `supp_id` → SINCRÓNICO, **200**. Es una sola fila del ERP y tarda
       menos de un segundo: se ejecuta dentro del request y se devuelven los
       contadores reales. Es el camino que usa el operador para traer un
       proveedor puntual y verlo al instante. Si el ERP falla o no devuelve
       datos responde **502**: nunca un éxito con contadores en cero.

    2. Sin `supp_id` (sync full) → ENCOLADO, **202**. La cadena completa
       (gbp-parser → mirror `tb_supplier` → tabla `proveedores` →
       `rma_proveedores`) recorre toda la tabla del ERP y no puede retener el
       request, un worker del threadpool y la transacción durante todo el
       round-trip. Se encola con `BackgroundTasks` y se responde de inmediato;
       el job publica los contadores (o el error) en el canal SSE
       `proveedores:sync` cuando termina.

    El permiso se verifica SIEMPRE en el request, antes de encolar: el job de
    background no tiene usuario ni sesión de request para chequearlo.
    """
    _check_permiso(db, current_user, "administracion.gestionar_proveedores")

    if supp_id is None:
        # `response.status_code` (y no un JSONResponse) para que las dos ramas
        # sigan devolviendo un dict por el pipeline normal de FastAPI: con
        # JSONResponse habría que serializar a mano también la rama sincrónica
        # solo por simetría, y el contrato del 200 no cambió.
        background_tasks.add_task(_sync_proveedores_erp_background)
        response.status_code = status.HTTP_202_ACCEPTED
        return {
            "success": True,
            "queued": True,
            "channel": SYNC_ERP_CHANNEL,
            "message": "Sincronización con el ERP en curso. El resultado llega al finalizar.",
        }

    svc = ProveedoresService(db)

    try:
        result = await svc.sync_desde_erp(supp_id=supp_id)
    except ErpSyncError as e:
        raise HTTPException(status_code=502, detail=str(e)) from e

    return {"success": True, "queued": False, **result}


@router.post("/{proveedor_id}/consultar-afip")
async def consultar_afip(
    proveedor_id: int,
    db: Session = Depends(get_async_db),
    current_user: Usuario = Depends(get_current_user),
) -> dict:
    """
    Consulta AFIP Padrón A4 para el proveedor y persiste datos fiscales.

    Requiere que el proveedor tenga CUIT cargado.
    Si AFIP falla, guarda el error pero no pierde datos previos.
    """
    _check_permiso(db, current_user, "administracion.consultar_afip")

    svc = ProveedoresService(db)

    try:
        datos = await svc.consultar_afip(proveedor_id)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except AfipServiceError as e:
        raise HTTPException(
            status_code=502,
            detail={"message": e.message, "afip_detail": e.detail},
        )

    return {
        "success": True,
        "condicion_iva": datos.condicion_iva,
        "inscripto_ganancias": datos.inscripto_ganancias,
        "estado_clave": datos.estado_clave,
        "razon_social_afip": datos.razon_social_afip,
        "actividad_principal": datos.actividad_principal,
        "ultima_consulta_afip": datos.ultima_consulta_afip.isoformat() if datos.ultima_consulta_afip else None,
    }


@router.get("/{proveedor_id}/datos-fiscales", response_model=DatosFiscalesResponse)
def obtener_datos_fiscales(
    proveedor_id: int,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> DatosFiscalesResponse:
    """Obtiene los datos fiscales cacheados de un proveedor."""
    _check_permiso(db, current_user, "administracion.ver_proveedores")

    from app.models.proveedor_datos_fiscales import ProveedorDatosFiscales

    datos = db.query(ProveedorDatosFiscales).filter(ProveedorDatosFiscales.proveedor_id == proveedor_id).first()

    if not datos:
        raise HTTPException(
            status_code=404,
            detail="No hay datos fiscales cargados. Consultá AFIP primero.",
        )

    return _datos_fiscales_to_response(datos)


# =============================================================================
# DIRECCIONES
# =============================================================================


@router.get("/{proveedor_id}/direcciones", response_model=list[DireccionResponse])
def listar_direcciones(
    proveedor_id: int,
    incluir_inactivas: bool = Query(False),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> list[DireccionResponse]:
    """Lista direcciones/depósitos de un proveedor."""
    _check_permiso(db, current_user, "administracion.ver_proveedores")

    from app.models.proveedor_direccion import ProveedorDireccion

    query = db.query(ProveedorDireccion).filter(ProveedorDireccion.proveedor_id == proveedor_id)
    if not incluir_inactivas:
        query = query.filter(ProveedorDireccion.activo == True)  # noqa: E712
    return [DireccionResponse.model_validate(d) for d in query.order_by(ProveedorDireccion.etiqueta).all()]


@router.post("/{proveedor_id}/direcciones", response_model=DireccionResponse, status_code=201)
def crear_direccion(
    proveedor_id: int,
    data: DireccionCreate,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> DireccionResponse:
    """Agrega una dirección/depósito al proveedor."""
    _check_permiso(db, current_user, "administracion.gestionar_proveedores")

    from app.models.proveedor_direccion import ProveedorDireccion

    d = ProveedorDireccion(proveedor_id=proveedor_id, **data.model_dump())
    db.add(d)
    db.commit()
    db.refresh(d)
    return DireccionResponse.model_validate(d)


@router.put("/direcciones/{direccion_id}", response_model=DireccionResponse)
def actualizar_direccion(
    direccion_id: int,
    data: DireccionCreate,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> DireccionResponse:
    """Actualiza una dirección."""
    _check_permiso(db, current_user, "administracion.gestionar_proveedores")

    from app.models.proveedor_direccion import ProveedorDireccion

    d = db.query(ProveedorDireccion).filter(ProveedorDireccion.id == direccion_id).first()
    if not d:
        raise HTTPException(status_code=404, detail="Dirección no encontrada")
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(d, field, value)
    db.commit()
    db.refresh(d)
    return DireccionResponse.model_validate(d)


@router.patch("/direcciones/{direccion_id}/toggle", response_model=DireccionResponse)
def toggle_direccion(
    direccion_id: int,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> DireccionResponse:
    """Habilita/deshabilita una dirección (soft delete)."""
    _check_permiso(db, current_user, "administracion.gestionar_proveedores")

    from app.models.proveedor_direccion import ProveedorDireccion

    d = db.query(ProveedorDireccion).filter(ProveedorDireccion.id == direccion_id).first()
    if not d:
        raise HTTPException(status_code=404, detail="Dirección no encontrada")
    d.activo = not d.activo
    db.commit()
    db.refresh(d)
    return DireccionResponse.model_validate(d)


# =============================================================================
# BANCOS
# =============================================================================


@router.get("/{proveedor_id}/bancos", response_model=list[BancoResponse])
def listar_bancos(
    proveedor_id: int,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> list[BancoResponse]:
    """Lista cuentas bancarias de un proveedor."""
    _check_permiso(db, current_user, "administracion.ver_proveedores")

    from app.models.proveedor_banco import ProveedorBanco

    bancos = (
        db.query(ProveedorBanco)
        .filter(ProveedorBanco.proveedor_id == proveedor_id, ProveedorBanco.activo == True)  # noqa: E712
        .order_by(ProveedorBanco.banco)
        .all()
    )
    return [BancoResponse.model_validate(b) for b in bancos]


@router.post("/{proveedor_id}/bancos", response_model=BancoResponse, status_code=201)
def crear_banco(
    proveedor_id: int,
    data: BancoCreate,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> BancoResponse:
    """Agrega una cuenta bancaria al proveedor."""
    _check_permiso(db, current_user, "administracion.gestionar_proveedores")

    from app.models.proveedor_banco import ProveedorBanco

    b = ProveedorBanco(proveedor_id=proveedor_id, **data.model_dump())
    db.add(b)
    db.commit()
    db.refresh(b)
    return BancoResponse.model_validate(b)


@router.put("/bancos/{banco_id}", response_model=BancoResponse)
def actualizar_banco(
    banco_id: int,
    data: BancoCreate,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> BancoResponse:
    """Actualiza una cuenta bancaria."""
    _check_permiso(db, current_user, "administracion.gestionar_proveedores")

    from app.models.proveedor_banco import ProveedorBanco

    b = db.query(ProveedorBanco).filter(ProveedorBanco.id == banco_id).first()
    if not b:
        raise HTTPException(status_code=404, detail="Cuenta bancaria no encontrada")
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(b, field, value)
    db.commit()
    db.refresh(b)
    return BancoResponse.model_validate(b)


@router.delete("/bancos/{banco_id}", status_code=204)
def eliminar_banco(
    banco_id: int,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> None:
    """Elimina (soft) una cuenta bancaria."""
    _check_permiso(db, current_user, "administracion.gestionar_proveedores")

    from app.models.proveedor_banco import ProveedorBanco

    b = db.query(ProveedorBanco).filter(ProveedorBanco.id == banco_id).first()
    if not b:
        raise HTTPException(status_code=404, detail="Cuenta bancaria no encontrada")
    b.activo = False
    db.commit()


# =============================================================================
# CONTACTOS
# =============================================================================


@router.get("/{proveedor_id}/contactos", response_model=list[ContactoResponse])
def listar_contactos(
    proveedor_id: int,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> list[ContactoResponse]:
    """Lista contactos de un proveedor."""
    _check_permiso(db, current_user, "administracion.ver_proveedores")

    from app.models.proveedor_contacto import ProveedorContacto

    contactos = (
        db.query(ProveedorContacto)
        .filter(ProveedorContacto.proveedor_id == proveedor_id, ProveedorContacto.activo == True)  # noqa: E712
        .order_by(ProveedorContacto.nombre)
        .all()
    )
    return [ContactoResponse.model_validate(c) for c in contactos]


@router.post("/{proveedor_id}/contactos", response_model=ContactoResponse, status_code=201)
def crear_contacto(
    proveedor_id: int,
    data: ContactoCreate,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> ContactoResponse:
    """Agrega un contacto al proveedor."""
    _check_permiso(db, current_user, "administracion.gestionar_proveedores")

    from app.models.proveedor_contacto import ProveedorContacto

    c = ProveedorContacto(proveedor_id=proveedor_id, **data.model_dump())
    db.add(c)
    db.commit()
    db.refresh(c)
    return ContactoResponse.model_validate(c)


@router.put("/contactos/{contacto_id}", response_model=ContactoResponse)
def actualizar_contacto(
    contacto_id: int,
    data: ContactoCreate,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> ContactoResponse:
    """Actualiza un contacto."""
    _check_permiso(db, current_user, "administracion.gestionar_proveedores")

    from app.models.proveedor_contacto import ProveedorContacto

    c = db.query(ProveedorContacto).filter(ProveedorContacto.id == contacto_id).first()
    if not c:
        raise HTTPException(status_code=404, detail="Contacto no encontrado")
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(c, field, value)
    db.commit()
    db.refresh(c)
    return ContactoResponse.model_validate(c)


@router.delete("/contactos/{contacto_id}", status_code=204)
def eliminar_contacto(
    contacto_id: int,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> None:
    """Elimina (soft) un contacto."""
    _check_permiso(db, current_user, "administracion.gestionar_proveedores")

    from app.models.proveedor_contacto import ProveedorContacto

    c = db.query(ProveedorContacto).filter(ProveedorContacto.id == contacto_id).first()
    if not c:
        raise HTTPException(status_code=404, detail="Contacto no encontrado")
    c.activo = False
    db.commit()


# =============================================================================
# MARCAS (read-only, extraídas de compras en GBP)
# =============================================================================


@router.get("/{proveedor_id}/marcas", response_model=list[MarcaProveedorResponse])
def marcas_por_proveedor(
    proveedor_id: int,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> list[MarcaProveedorResponse]:
    """
    Marcas que le compramos a un proveedor.
    Extrae de item_transactions (puco_id=10) cruzando con tb_item → tb_brand.
    """
    _check_permiso(db, current_user, "administracion.ver_proveedores")

    from app.models.proveedor import Proveedor

    prov = db.query(Proveedor).filter(Proveedor.id == proveedor_id).first()
    if not prov or not prov.supp_id:
        return []

    from sqlalchemy import text

    results = db.execute(
        text("""
            SELECT b.brand_id, b.brand_desc, MAX(ct.ct_date) as ultima_compra, COUNT(DISTINCT ct.ct_transaction) as cant
            FROM tb_item_transactions it
            JOIN tb_commercial_transactions ct ON it.ct_transaction = ct.ct_transaction
            JOIN tb_item i ON it.item_id = i.item_id AND it.comp_id = i.comp_id
            JOIN tb_brand b ON i.brand_id = b.brand_id AND i.comp_id = b.comp_id
            WHERE it.supp_id = :supp_id AND it.puco_id = 10
            GROUP BY b.brand_id, b.brand_desc
            ORDER BY cant DESC
        """),
        {"supp_id": prov.supp_id},
    ).fetchall()

    return [
        MarcaProveedorResponse(
            brand_id=r[0],
            marca=r[1],
            ultima_compra=r[2],
            cantidad_compras=r[3],
        )
        for r in results
    ]


@router.get("/buscar-por-marca", response_model=list[ProveedorResponse])
def buscar_proveedores_por_marca(
    marca: str = Query(..., min_length=1, description="Nombre de marca a buscar"),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> list[ProveedorResponse]:
    """
    Busca proveedores a los que les compramos una marca determinada.
    Ej: "¿a quién le compro Logitech?"
    """
    _check_permiso(db, current_user, "administracion.ver_proveedores")

    from sqlalchemy import text

    results = db.execute(
        text("""
            SELECT DISTINCT p.id
            FROM proveedores p
            JOIN tb_item_transactions it ON it.supp_id = p.supp_id
            JOIN tb_item i ON it.item_id = i.item_id AND it.comp_id = i.comp_id
            JOIN tb_brand b ON i.brand_id = b.brand_id AND i.comp_id = b.comp_id
            WHERE it.puco_id = 10 AND b.brand_desc ILIKE :marca AND p.activo = true
            ORDER BY p.id
        """),
        {"marca": f"%{marca}%"},
    ).fetchall()

    prov_ids = [r[0] for r in results]
    if not prov_ids:
        return []

    from app.models.proveedor import Proveedor

    proveedores = db.query(Proveedor).filter(Proveedor.id.in_(prov_ids)).all()
    return [_proveedor_to_response(p) for p in proveedores]
