"""
Router: RMA Proveedores — ABM de proveedores para el módulo RMA.

Endpoints:
  GET  /rma-proveedores            — listar (con búsqueda y paginación)
  GET  /rma-proveedores/{id}       — detalle
  PUT  /rma-proveedores/{id}       — actualizar datos extendidos
  POST /rma-proveedores/sync       — sincronizar desde tb_supplier (nuevos)
"""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy import func as sa_func
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import get_current_user
from app.models.rma_proveedor import RmaProveedor
from app.models.tb_supplier import TBSupplier
from app.models.usuario import Usuario
from app.services.permisos_service import PermisosService

router = APIRouter(prefix="/rma-proveedores", tags=["RMA Proveedores"])


# =============================================================================
# SCHEMAS
# =============================================================================


class ProveedorResponse(BaseModel):
    id: int
    supp_id: Optional[int] = None
    comp_id: Optional[int] = None
    nombre: str
    cuit: Optional[str] = None
    direccion: Optional[str] = None
    cp: Optional[str] = None
    ciudad: Optional[str] = None
    provincia: Optional[str] = None
    telefono: Optional[str] = None
    email: Optional[str] = None
    representante: Optional[str] = None
    horario: Optional[str] = None
    notas: Optional[str] = None
    unidades_minimas_rma: Optional[int] = None
    activo: bool = True

    model_config = ConfigDict(from_attributes=True)


class ProveedorUpdate(BaseModel):
    nombre: Optional[str] = None
    cuit: Optional[str] = None
    direccion: Optional[str] = None
    cp: Optional[str] = None
    ciudad: Optional[str] = None
    provincia: Optional[str] = None
    telefono: Optional[str] = None
    email: Optional[str] = None
    representante: Optional[str] = None
    horario: Optional[str] = None
    notas: Optional[str] = None
    unidades_minimas_rma: Optional[int] = None
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
    _check_permiso(db, current_user, "rma.ver")

    query = db.query(RmaProveedor)

    if solo_activos:
        query = query.filter(RmaProveedor.activo == True)  # noqa: E712

    if search:
        import re

        like = f"%{search}%"

        # Normalized search: strip non-alphanumeric chars for acronym matching
        # e.g. "bgh" matches "B.G.H.", "B G H", "B-G-H S.A."
        norm_term = re.sub(r"[^a-zA-Z0-9]", "", search).lower()
        strip_re = "[^a-zA-Z0-9]"
        norm_nombre = sa_func.lower(sa_func.regexp_replace(RmaProveedor.nombre, strip_re, "", "g"))

        query = query.filter(
            norm_nombre.like(f"%{norm_term}%")
            | (RmaProveedor.nombre.ilike(like))
            | (RmaProveedor.cuit.ilike(like))
            | (RmaProveedor.ciudad.ilike(like))
            | (RmaProveedor.representante.ilike(like))
        )

    total = query.count()
    proveedores = query.order_by(RmaProveedor.nombre).offset((page - 1) * page_size).limit(page_size).all()

    return ProveedorListResponse(
        proveedores=[ProveedorResponse.model_validate(p) for p in proveedores],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/{proveedor_id}", response_model=ProveedorResponse)
async def obtener_proveedor(
    proveedor_id: int,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> ProveedorResponse:
    """Obtiene un proveedor por ID."""
    _check_permiso(db, current_user, "rma.ver")

    prov = db.query(RmaProveedor).filter(RmaProveedor.id == proveedor_id).first()
    if not prov:
        raise HTTPException(status_code=404, detail="Proveedor no encontrado")

    return ProveedorResponse.model_validate(prov)


@router.put("/{proveedor_id}", response_model=ProveedorResponse)
async def actualizar_proveedor(
    proveedor_id: int,
    data: ProveedorUpdate,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> ProveedorResponse:
    """Actualiza datos extendidos de un proveedor."""
    _check_permiso(db, current_user, "rma.gestionar")

    prov = db.query(RmaProveedor).filter(RmaProveedor.id == proveedor_id).first()
    if not prov:
        raise HTTPException(status_code=404, detail="Proveedor no encontrado")

    update_data = data.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(prov, field, value)

    db.commit()
    db.refresh(prov)

    return ProveedorResponse.model_validate(prov)


@router.post("/sync", status_code=status.HTTP_200_OK)
async def sync_proveedores_desde_erp(
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> dict:
    """
    Sincroniza proveedores desde tb_supplier a rma_proveedores.

    Solo inserta proveedores nuevos (que no existan por supp_id+comp_id).
    Actualiza nombre y CUIT de los existentes si cambiaron en el ERP.
    Nunca pisa campos extendidos (dirección, contacto, config RMA).
    """
    _check_permiso(db, current_user, "rma.gestionar")

    # Todos los suppliers del ERP
    erp_suppliers = db.query(TBSupplier).all()

    # Todos los rma_proveedores indexados por (comp_id, supp_id)
    existing = {
        (p.comp_id, p.supp_id): p for p in db.query(RmaProveedor).filter(RmaProveedor.supp_id.isnot(None)).all()
    }

    insertados = 0
    actualizados = 0

    for supp in erp_suppliers:
        key = (supp.comp_id, supp.supp_id)
        if key in existing:
            prov = existing[key]
            # Solo actualizar nombre y CUIT (no pisar datos extendidos)
            if prov.nombre != supp.supp_name or prov.cuit != supp.supp_tax_number:
                prov.nombre = supp.supp_name
                prov.cuit = supp.supp_tax_number
                actualizados += 1
        else:
            nuevo = RmaProveedor(
                supp_id=supp.supp_id,
                comp_id=supp.comp_id,
                nombre=supp.supp_name,
                cuit=supp.supp_tax_number,
            )
            db.add(nuevo)
            insertados += 1

    db.commit()

    return {
        "success": True,
        "insertados": insertados,
        "actualizados": actualizados,
        "total_erp": len(erp_suppliers),
    }
