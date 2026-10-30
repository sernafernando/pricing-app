"""Gestión Full — Full replenishment planning (Reportes)."""

from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Path, Query, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_algun_permiso
from app.core.database import get_db
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
from app.services.pm_scope import is_full_view

router = APIRouter(prefix="/gestion-full", tags=["gestion-full"])

VIEW_PERMISOS = ["productos.ver", "ml_ops.ver"]


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


@router.get(
    "",
    response_model=GestionFullListResponse,
    dependencies=[Depends(require_algun_permiso(VIEW_PERMISOS))],
)
def get_gestion_full(
    q: str = Query("", description="Search EAN, description, inventory_id or MLAU"),
    marca: str = Query("", description="Exact brand filter"),
    categoria: str = Query("", description="Exact category filter"),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> dict[str, Any]:
    """List Full replenishment rows. Everyone with view permission sees all rows; filters are optional."""
    payload = list_gestion_full(db, q=q, marca=marca, categoria=categoria, limit=limit, offset=offset)
    for item in payload["items"]:
        item["puede_editar_override"] = puede_editar_override_para(
            current_user, db, item.get("marca"), item.get("categoria")
        )
    payload["puede_editar_override"] = usuario_puede_editar_algun_override(current_user, db)
    return payload


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
