"""
Router: Administración — Proveedores.

Endpoints:
  GET    /administracion/proveedores              — listar (con búsqueda y paginación)
  GET    /administracion/proveedores/{id}          — detalle (con datos fiscales)
  POST   /administracion/proveedores               — crear proveedor manual
  PUT    /administracion/proveedores/{id}          — actualizar datos
  POST   /administracion/proveedores/sync-erp      — sincronizar desde tb_supplier
  POST   /administracion/proveedores/{id}/consultar-afip — consultar Padrón A4
  GET    /administracion/proveedores/{id}/datos-fiscales — ver datos fiscales cacheados
"""

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import get_current_user
from app.models.usuario import Usuario
from app.services.permisos_service import PermisosService
from app.services.proveedores_service import ProveedoresService
from app.services.afip_service import AfipServiceError

router = APIRouter(prefix="/administracion/proveedores", tags=["Administración - Proveedores"])


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


class ProveedorDetalleResponse(ProveedorResponse):
    """Proveedor con datos fiscales completos."""

    datos_fiscales: Optional[DatosFiscalesResponse] = None


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
async def listar_proveedores(
    search: Optional[str] = Query(None, description="Buscar por nombre, CUIT o ciudad"),
    solo_activos: bool = Query(True, description="Solo proveedores activos"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> ProveedorListResponse:
    """Lista proveedores con búsqueda y paginación."""
    _check_permiso(db, current_user, "administracion.ver_proveedores")

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
async def obtener_proveedor(
    proveedor_id: int,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> ProveedorDetalleResponse:
    """Obtiene un proveedor con sus datos fiscales completos."""
    _check_permiso(db, current_user, "administracion.ver_proveedores")

    svc = ProveedoresService(db)
    prov = svc.obtener(proveedor_id)
    if not prov:
        raise HTTPException(status_code=404, detail="Proveedor no encontrado")

    datos = getattr(prov, "datos_fiscales", None)
    base = _proveedor_to_response(prov)

    return ProveedorDetalleResponse(
        **base.model_dump(),
        datos_fiscales=_datos_fiscales_to_response(datos) if datos else None,
    )


@router.post("", response_model=ProveedorResponse, status_code=status.HTTP_201_CREATED)
async def crear_proveedor(
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
async def actualizar_proveedor(
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


@router.post("/sync-erp", status_code=status.HTTP_200_OK)
async def sync_proveedores_erp(
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> dict:
    """
    Sincroniza proveedores desde tb_supplier (ERP) a la tabla central.
    Vincula rma_proveedores existentes al proveedor central.
    """
    _check_permiso(db, current_user, "administracion.gestionar_proveedores")

    svc = ProveedoresService(db)
    result = svc.sync_desde_erp()

    return {"success": True, **result}


@router.post("/{proveedor_id}/consultar-afip")
async def consultar_afip(
    proveedor_id: int,
    db: Session = Depends(get_db),
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
async def obtener_datos_fiscales(
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
