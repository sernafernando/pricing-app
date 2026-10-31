"""Gestión Full — Full replenishment planning (Reportes)."""

from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Path, Query, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_algun_permiso, require_permiso
from app.core.database import get_db
from app.models.producto import ProductoERP
from app.models.usuario import Usuario
from app.services.gestion_full.inbound import refresh_last_inbound
from app.services.gestion_full.listing import list_gestion_full
from app.services.gestion_full.overrides import (
    clear_override,
    puede_editar_override_para,
    resolve_producto_por_inventory_id,
    upsert_override,
    usuario_puede_editar_algun_override,
)
from app.services.gestion_full.package import (
    get_active_package,
    get_or_create_open_package,
    set_qty_export,
    upsert_package_line,
)
from app.services.gestion_full.pm_ready import (
    get_pm_ready,
    is_line_locked,
    load_row_for_ready,
    mark_pm_ready,
    resolve_ready_key_por_inventory_id,
    unlock_pm_ready,
)
from app.models.gestion_full_package import GestionFullPackageLine
from app.services.gestion_full.unidades_caja import (
    clear_unidades_caja,
    import_unidades_caja_por_ean,
    upsert_unidades_caja,
)
from app.services.permisos_service import PermisosService
from app.services.pm_scope import is_full_view

router = APIRouter(prefix="/gestion-full", tags=["gestion-full"])

VIEW_PERMISOS = ["productos.ver", "ml_ops.ver"]
PERM_DEPOSITOS = "gestion_full.depositos"
PERM_GESTOR = "gestion_full.gestor"


class GestionFullItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    producto_item_id: int
    ean: Optional[str] = None
    descripcion: Optional[str] = None
    marca: Optional[str] = None
    categoria: Optional[str] = None
    inventory_id: str
    user_product_id: Optional[str] = None
    mla: Optional[str] = None
    stock_erp: Optional[int] = None
    stock_full: Optional[int] = None
    ventas_full_7d: Optional[int] = None
    ventas_full_14d: Optional[int] = None
    ventas_full_21d: Optional[int] = None
    ventas_full_30d: Optional[int] = None
    ventas_colecta_flex_7d: Optional[int] = None
    ventas_colecta_flex_30d: Optional[int] = None
    target: Optional[int] = None
    sugerido: Optional[int] = None
    override: Optional[int] = None
    unidades_por_caja: Optional[int] = None
    qty_pm: Optional[int] = None
    pm_ready: bool = False
    puede_editar_override: bool = False


class GestionFullListResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    total: int
    limit: int
    offset: int
    items: list[GestionFullItem]
    puede_editar_override: bool = Field(
        description="True when the caller may write at least one override (full-view or PM/sub-PM scope)."
    )
    puede_editar_caja: bool = Field(
        default=False,
        description="True when the caller has gestion_full.depositos.",
    )
    puede_gestor: bool = Field(
        default=False,
        description="True when the caller has gestion_full.gestor (unlock / export).",
    )


class GestionFullOverrideBody(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    cantidad: Optional[int] = Field(
        default=None,
        description="Override qty; null or omit-with-clear clears the stored override.",
        ge=0,
    )


class GestionFullOverrideResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    inventory_id: str
    override: Optional[int] = None


class GestionFullTargetResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    inventory_id: str
    target: Optional[int] = None
    occurred_at: Optional[str] = None


class GestionFullUnidadesCajaBody(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    unidades: Optional[int] = Field(
        default=None,
        description="Units per closed box; null clears the stored value.",
        ge=1,
    )


class GestionFullUnidadesCajaResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    producto_item_id: int
    unidades_por_caja: Optional[int] = None


class GestionFullUnidadesCajaImportRow(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    ean: str = Field(..., min_length=1)
    unidades: int = Field(..., ge=1)


class GestionFullUnidadesCajaImportBody(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    rows: list[GestionFullUnidadesCajaImportRow] = Field(..., min_length=1, max_length=5000)


class GestionFullUnidadesCajaImportResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    updated: int
    errors: list[dict[str, Any]] = Field(default_factory=list)


class GestionFullPmReadyBody(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    producto_item_id: int = Field(..., ge=1)
    user_product_id: str = Field(..., min_length=1, max_length=128)


class GestionFullPmReadyResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    producto_item_id: int
    user_product_id: str
    inventory_id: str
    qty_pm: int
    pm_ready: bool = True


class GestionFullPackageLineOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    producto_item_id: int
    user_product_id: str
    inventory_id: str
    qty_pm: int
    qty_export: int
    qty_export_reason: Optional[str] = None
    inbound_id: Optional[str] = None


class GestionFullPackageResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    week_monday: str
    status: str
    lines: list[GestionFullPackageLineOut] = Field(default_factory=list)


class GestionFullPackageLineBody(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    producto_item_id: int = Field(..., ge=1)
    user_product_id: str = Field(..., min_length=1, max_length=128)


class GestionFullQtyExportBody(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    qty_export: int = Field(..., ge=0)
    reason: Optional[str] = Field(default=None, max_length=500)
    stock_erp: Optional[int] = Field(default=None, ge=0)


@router.get(
    "",
    response_model=GestionFullListResponse,
    dependencies=[Depends(require_algun_permiso(VIEW_PERMISOS))],
)
def get_gestion_full(
    q: str = Query("", description="Search EAN, description, inventory_id or MLAU"),
    marca: str = Query("", description="Exact brand filter"),
    categoria: str = Query("", description="Exact category filter"),
    full_mode: str = Query(
        "en",
        description="en Full | fuera de Full | todos (en = stock_full>0 OR ventas Full 30d>0)",
        pattern="^(en|fuera|todos)$",
    ),
    include_zero_stock: bool = Query(
        False,
        description="When false (default), hide rows with stock_erp 0/null",
    ),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> dict[str, Any]:
    """List Full replenishment rows. Defaults: en Full + hide zero ERP stock."""
    payload = list_gestion_full(
        db,
        q=q,
        marca=marca,
        categoria=categoria,
        full_mode=full_mode,
        include_zero_stock=include_zero_stock,
        limit=limit,
        offset=offset,
    )
    perms = PermisosService(db)
    for item in payload["items"]:
        in_scope = puede_editar_override_para(
            current_user, db, item.get("marca"), item.get("categoria")
        )
        item["puede_editar_override"] = in_scope and not item.get("pm_ready")
    payload["puede_editar_override"] = usuario_puede_editar_algun_override(current_user, db)
    payload["puede_editar_caja"] = perms.tiene_permiso(current_user, PERM_DEPOSITOS)
    payload["puede_gestor"] = perms.tiene_permiso(current_user, PERM_GESTOR)
    return payload


@router.post(
    "/ready",
    response_model=GestionFullPmReadyResponse,
    dependencies=[Depends(require_algun_permiso(VIEW_PERMISOS))],
)
def post_pm_ready(
    body: GestionFullPmReadyBody,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> dict[str, Any]:
    """PM closes their part: freeze qty_pm and lock override on this ERP+MLAU line."""
    preview = load_row_for_ready(
        db,
        producto_item_id=body.producto_item_id,
        user_product_id=body.user_product_id,
    )
    if preview is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="fila Gestión Full no encontrada",
        )
    if not puede_editar_override_para(
        current_user, db, preview.get("marca"), preview.get("categoria")
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Sin permiso para cerrar esta línea",
        )
    try:
        row = mark_pm_ready(
            db,
            producto_item_id=body.producto_item_id,
            user_product_id=body.user_product_id,
            usuario=current_user,
        )
    except LookupError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="fila Gestión Full no encontrada",
        ) from None
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from None
    return {
        "producto_item_id": row.producto_item_id,
        "user_product_id": row.user_product_id,
        "inventory_id": row.inventory_id,
        "qty_pm": row.qty_pm,
        "pm_ready": True,
    }


@router.post(
    "/unlock",
    response_model=GestionFullPmReadyResponse,
    dependencies=[Depends(require_permiso(PERM_GESTOR))],
)
def post_pm_unlock(
    body: GestionFullPmReadyBody,
    db: Session = Depends(get_db),
    _current_user: Usuario = Depends(get_current_user),
) -> dict[str, Any]:
    """Gestor unlocks a PM-ready line so the PM can edit override again."""
    existing = get_pm_ready(
        db,
        producto_item_id=body.producto_item_id,
        user_product_id=body.user_product_id,
    )
    if existing is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="línea no está cerrada por el PM",
        )
    inventory_id = existing.inventory_id
    qty_pm = existing.qty_pm
    unlock_pm_ready(
        db,
        producto_item_id=body.producto_item_id,
        user_product_id=body.user_product_id,
    )
    return {
        "producto_item_id": body.producto_item_id,
        "user_product_id": body.user_product_id,
        "inventory_id": inventory_id,
        "qty_pm": qty_pm,
        "pm_ready": False,
    }


@router.get(
    "/package",
    response_model=GestionFullPackageResponse,
    dependencies=[Depends(require_algun_permiso(VIEW_PERMISOS))],
)
def get_package(db: Session = Depends(get_db)) -> dict[str, Any]:
    """Return the active send package (open/exported) or 404."""
    pkg = get_active_package(db)
    if pkg is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="no hay paquete activo",
        )
    return {
        "id": pkg.id,
        "week_monday": pkg.week_monday.isoformat(),
        "status": pkg.status,
        "lines": [
            {
                "id": ln.id,
                "producto_item_id": ln.producto_item_id,
                "user_product_id": ln.user_product_id,
                "inventory_id": ln.inventory_id,
                "qty_pm": ln.qty_pm,
                "qty_export": ln.qty_export,
                "qty_export_reason": ln.qty_export_reason,
                "inbound_id": ln.inbound_id,
            }
            for ln in pkg.lines
        ],
    }


@router.post(
    "/package/lines",
    response_model=GestionFullPackageLineOut,
    dependencies=[Depends(require_permiso(PERM_GESTOR))],
)
def post_package_line(
    body: GestionFullPackageLineBody,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> dict[str, Any]:
    """Add/refresh a package line from an existing PM-ready freeze."""
    ready = get_pm_ready(
        db,
        producto_item_id=body.producto_item_id,
        user_product_id=body.user_product_id,
    )
    if ready is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="la línea debe estar cerrada por el PM (ready)",
        )
    pkg = get_or_create_open_package(db, usuario=current_user)
    if pkg.status == "locked":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="paquete hard-locked",
        )
    line = upsert_package_line(
        db,
        package=pkg,
        producto_item_id=ready.producto_item_id,
        user_product_id=ready.user_product_id,
        inventory_id=ready.inventory_id,
        qty_pm=ready.qty_pm,
    )
    return {
        "id": line.id,
        "producto_item_id": line.producto_item_id,
        "user_product_id": line.user_product_id,
        "inventory_id": line.inventory_id,
        "qty_pm": line.qty_pm,
        "qty_export": line.qty_export,
        "qty_export_reason": line.qty_export_reason,
        "inbound_id": line.inbound_id,
    }


@router.patch(
    "/package/lines/{line_id}/qty-export",
    response_model=GestionFullPackageLineOut,
    dependencies=[Depends(require_permiso(PERM_GESTOR))],
)
def patch_package_qty_export(
    body: GestionFullQtyExportBody,
    line_id: int = Path(..., ge=1),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> dict[str, Any]:
    """Gestor adjusts qty_export (optional reason); writes audit."""
    line = db.get(GestionFullPackageLine, line_id)
    if line is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="línea no encontrada")
    try:
        line = set_qty_export(
            db,
            line=line,
            qty_export=body.qty_export,
            usuario=current_user,
            reason=body.reason,
            stock_erp=body.stock_erp,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from None
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from None
    return {
        "id": line.id,
        "producto_item_id": line.producto_item_id,
        "user_product_id": line.user_product_id,
        "inventory_id": line.inventory_id,
        "qty_pm": line.qty_pm,
        "qty_export": line.qty_export,
        "qty_export_reason": line.qty_export_reason,
        "inbound_id": line.inbound_id,
    }


@router.post(
    "/unidades-caja/import",
    response_model=GestionFullUnidadesCajaImportResponse,
    dependencies=[Depends(require_permiso(PERM_DEPOSITOS))],
)
def post_unidades_caja_import(
    body: GestionFullUnidadesCajaImportBody,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> dict[str, Any]:
    """Bulk upsert units-per-box by ERP EAN (Sheet / CSV paste)."""
    return import_unidades_caja_por_ean(
        db,
        rows=[r.model_dump() for r in body.rows],
        usuario=current_user,
    )


@router.patch(
    "/unidades-caja/{producto_item_id}",
    response_model=GestionFullUnidadesCajaResponse,
    dependencies=[Depends(require_permiso(PERM_DEPOSITOS))],
)
def patch_unidades_caja(
    body: GestionFullUnidadesCajaBody,
    producto_item_id: int = Path(..., ge=1),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> dict[str, Any]:
    """Upsert or clear units-per-closed-box for one ERP product."""
    if db.get(ProductoERP, producto_item_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="producto ERP no encontrado")

    if body.unidades is None:
        clear_unidades_caja(db, producto_item_id=producto_item_id)
        return {"producto_item_id": producto_item_id, "unidades_por_caja": None}

    row = upsert_unidades_caja(
        db,
        producto_item_id=producto_item_id,
        unidades=body.unidades,
        usuario=current_user,
    )
    return {"producto_item_id": row.producto_item_id, "unidades_por_caja": row.unidades}


@router.patch(
    "/{inventory_id}",
    response_model=GestionFullOverrideResponse,
    dependencies=[Depends(require_algun_permiso(VIEW_PERMISOS))],
)
def patch_gestion_full_override(
    body: GestionFullOverrideBody,
    inventory_id: str = Path(..., min_length=1, max_length=128),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> dict[str, Any]:
    """Upsert or clear the PM override for one Full inventory_id."""
    producto = resolve_producto_por_inventory_id(db, inventory_id)
    if producto is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="inventory_id no vinculado")

    if not puede_editar_override_para(current_user, db, producto["marca"], producto["categoria"]):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Sin permiso para editar override de este producto",
        )

    ready_key = resolve_ready_key_por_inventory_id(db, inventory_id)
    if ready_key is not None and is_line_locked(
        db,
        producto_item_id=ready_key["producto_item_id"],
        user_product_id=ready_key["user_product_id"],
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Línea cerrada por el PM; el gestor debe desbloquearla",
        )

    if body.cantidad is None:
        clear_override(db, inventory_id=inventory_id)
        return {"inventory_id": inventory_id, "override": None}

    row = upsert_override(db, inventory_id=inventory_id, cantidad=body.cantidad, usuario=current_user)
    return {"inventory_id": row.inventory_id, "override": row.cantidad}


@router.post(
    "/{inventory_id}/refresh-inbound",
    response_model=GestionFullTargetResponse,
    dependencies=[Depends(require_algun_permiso(VIEW_PERMISOS))],
)
def post_refresh_inbound(
    inventory_id: str = Path(..., min_length=1, max_length=128),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> dict[str, Any]:
    """Pull the latest Full inbound reception from ML and store it as Target.

    Restricted to full-view users to protect the ML operations quota; a Monday
    batch job can refresh everyone later.
    """
    if not is_full_view(current_user, db):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Solo admin/full-view puede refrescar inbound",
        )

    producto = resolve_producto_por_inventory_id(db, inventory_id)
    if producto is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="inventory_id no vinculado")

    row = refresh_last_inbound(db, inventory_id)
    if row is None:
        return {"inventory_id": inventory_id, "target": None, "occurred_at": None}
    return {
        "inventory_id": row.inventory_id,
        "target": row.cantidad,
        "occurred_at": row.occurred_at.isoformat() if row.occurred_at else None,
    }
