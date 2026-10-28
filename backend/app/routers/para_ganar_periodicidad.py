"""PARA GANAR — Periodicidad subscription CRUD (P2)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload

from app.api.deps import get_current_user, require_permiso
from app.core.database import get_db
from app.models.para_ganar_periodicidad import (
    ParaGanarPeriodicidadEan,
    ParaGanarPeriodicidadEanMla,
)
from app.models.usuario import Usuario
from app.services.para_ganar_periodicidad import normalize_ean, validate_scope_payload

router = APIRouter(prefix="/para-ganar", tags=["PARA GANAR"])


class PeriodicidadEanResponse(BaseModel):
    ean: str
    enabled: bool
    scope_mode: str
    mlas: List[str] = Field(default_factory=list)
    tipos_publicacion: List[str] = Field(default_factory=list)
    pricelist_ids: List[int] = Field(default_factory=list)
    tienda_oficial_ids: List[int] = Field(default_factory=list)
    updated_at: Optional[datetime] = None
    updated_by_id: Optional[int] = None

    model_config = ConfigDict(from_attributes=True)


class PeriodicidadEanUpsert(BaseModel):
    enabled: bool = True
    scope_mode: str = "all"
    mlas: List[str] = Field(default_factory=list)
    tipos_publicacion: List[str] = Field(default_factory=list)
    pricelist_ids: List[int] = Field(default_factory=list)
    tienda_oficial_ids: List[int] = Field(default_factory=list)

    model_config = ConfigDict(from_attributes=True)


class PeriodicidadEanListResponse(BaseModel):
    total: int
    page: int
    page_size: int
    items: List[PeriodicidadEanResponse]

    model_config = ConfigDict(from_attributes=True)


def _as_str_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value]


def _as_int_list(value: object) -> list[int]:
    if not isinstance(value, list):
        return []
    out: list[int] = []
    for item in value:
        try:
            out.append(int(item))
        except (TypeError, ValueError):
            continue
    return out


def _to_response(row: ParaGanarPeriodicidadEan) -> PeriodicidadEanResponse:
    return PeriodicidadEanResponse(
        ean=row.ean,
        enabled=bool(row.enabled),
        scope_mode=row.scope_mode,
        mlas=sorted(link.mla for link in (row.mlas or [])),
        tipos_publicacion=_as_str_list(row.tipos_publicacion),
        pricelist_ids=_as_int_list(row.pricelist_ids),
        tienda_oficial_ids=_as_int_list(row.tienda_oficial_ids),
        updated_at=row.updated_at,
        updated_by_id=row.updated_by_id,
    )


@router.get(
    "/periodicidad",
    response_model=PeriodicidadEanListResponse,
    dependencies=[Depends(require_permiso("productos.ver"))],
)
def listar_periodicidad(
    q: Optional[str] = Query(None, max_length=64),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    _user: Usuario = Depends(get_current_user),
) -> PeriodicidadEanListResponse:
    """Paginated list of EAN periodicidad subscriptions."""
    query = db.query(ParaGanarPeriodicidadEan)
    ean_q = normalize_ean(q or "")
    if ean_q:
        like = f"%{ean_q.lower()}%"
        query = query.filter(func.lower(ParaGanarPeriodicidadEan.ean).like(like))
    total = query.count()
    rows = (
        query.options(joinedload(ParaGanarPeriodicidadEan.mlas))
        .order_by(ParaGanarPeriodicidadEan.ean.asc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return PeriodicidadEanListResponse(
        total=total,
        page=page,
        page_size=page_size,
        items=[_to_response(row) for row in rows],
    )


@router.get(
    "/periodicidad/{ean}",
    response_model=PeriodicidadEanResponse,
    dependencies=[Depends(require_permiso("productos.ver"))],
)
def obtener_periodicidad(
    ean: str,
    db: Session = Depends(get_db),
    _user: Usuario = Depends(get_current_user),
) -> PeriodicidadEanResponse:
    """Return one EAN periodicidad subscription or 404 if not subscribed."""
    ean_norm = normalize_ean(ean)
    if not ean_norm:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="EAN inválido")
    row = (
        db.query(ParaGanarPeriodicidadEan)
        .options(joinedload(ParaGanarPeriodicidadEan.mlas))
        .filter(ParaGanarPeriodicidadEan.ean == ean_norm)
        .one_or_none()
    )
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Suscripción no encontrada")
    return _to_response(row)


@router.put(
    "/periodicidad/{ean}",
    response_model=PeriodicidadEanResponse,
    dependencies=[Depends(require_permiso("productos.editar_precios"))],
)
def upsert_periodicidad(
    ean: str,
    body: PeriodicidadEanUpsert,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> PeriodicidadEanResponse:
    """Create or replace periodicidad subscription for an EAN."""
    ean_norm = normalize_ean(ean)
    if not ean_norm:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="EAN inválido")
    try:
        cleaned = validate_scope_payload(
            scope_mode=body.scope_mode,
            mlas=body.mlas,
            tipos_publicacion=body.tipos_publicacion,
            pricelist_ids=body.pricelist_ids,
            tienda_oficial_ids=body.tienda_oficial_ids,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc

    row = db.get(ParaGanarPeriodicidadEan, ean_norm)
    if row is None:
        row = ParaGanarPeriodicidadEan(ean=ean_norm)
        db.add(row)

    row.enabled = bool(body.enabled)
    row.scope_mode = cleaned["scope_mode"]
    row.tipos_publicacion = cleaned["tipos_publicacion"]
    row.pricelist_ids = cleaned["pricelist_ids"]
    row.tienda_oficial_ids = cleaned["tienda_oficial_ids"]
    row.updated_by_id = current_user.id
    row.updated_at = datetime.now(UTC)

    # Replace MLA links
    row.mlas.clear()
    for mla in cleaned["mlas"]:
        row.mlas.append(ParaGanarPeriodicidadEanMla(ean=ean_norm, mla=mla))

    db.commit()
    db.refresh(row)
    row = (
        db.query(ParaGanarPeriodicidadEan)
        .options(joinedload(ParaGanarPeriodicidadEan.mlas))
        .filter(ParaGanarPeriodicidadEan.ean == ean_norm)
        .one()
    )
    return _to_response(row)


@router.delete(
    "/periodicidad/{ean}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_permiso("productos.editar_precios"))],
)
def borrar_periodicidad(
    ean: str,
    db: Session = Depends(get_db),
    _user: Usuario = Depends(get_current_user),
) -> None:
    """Remove the EAN from periodic review (cascade drops explicit MLA rows)."""
    ean_norm = normalize_ean(ean)
    if not ean_norm:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="EAN inválido")
    row = db.get(ParaGanarPeriodicidadEan, ean_norm)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Suscripción no encontrada")
    db.delete(row)
    db.commit()
    return None
