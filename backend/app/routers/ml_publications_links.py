"""Router: product links of the ML publications store (design D20, spec Domain 6).

Every publication unit `(item_id, variation_id)` is linked to one of our products automatically by SKU;
these endpoints are the operator's manual backup: look at a link and its suggestion, fix it by hand,
mark "no product", hand it back to the automatic rule, and review what needs attention.

- Reads (`ml_ops.ver`): one item's units, the lists by class, the coverage report. They never depend on
  `links.enabled`: looking at the state is always allowed.
- Writes (`ml_publicaciones.vincular`, migration `20261007_ml_publicaciones_vincular_perm`): refused with
  409 while `links.enabled` is off. The flag is the operator's kill switch for everything that moves a
  link; honouring it here means "linking off" really freezes the table. Permission is checked before the
  flag (a user without permission never learns whether linking is on).
- Every write goes through `app.services.ml_publications.links`, which writes the link, its change-log row,
  the `product_link_changed` event (when `events.enabled`) and the `auditoria` row in ONE transaction; the
  author is always the authenticated user, never a body field.
- There is no DELETE verb: links are never deleted ("revert to automatic" is the way back).
- This module never touches the product catalog itself: it is read only inside the linking module.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Path, Query, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.database import get_db
from app.models.usuario import Usuario
from app.services.ml_publications import links
from app.services.permisos_service import PermisosService

PERMISO_VER = "ml_ops.ver"
PERMISO_VINCULAR = "ml_publicaciones.vincular"

NOTE_MAX = 500  # `auditoria.comentario` is VARCHAR(500)
SAMPLES_MAX = 50

router = APIRouter(prefix="/ml-publications", tags=["ML Publications Links"])


def require_permission(permission: str):
    """Dependency for a required permission code (same pattern as `ml_ventas_ops.py`)."""

    def _check_permission(
        current_user: Usuario = Depends(get_current_user),
        db: Session = Depends(get_db),
    ) -> Usuario:
        if not PermisosService(db).tiene_permiso(current_user, permission):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=f"No tienes permiso: {permission}")
        return current_user

    return _check_permission


def get_links_db(db: Session = Depends(get_db)) -> Session:
    """The session the link tables are read and written through: the request's own (same database as the
    permission check). A separate dependency only so a test can point the link tables elsewhere."""
    return db


# ── Schemas ──────────────────────────────────────────────────────


class ProductRef(BaseModel):
    item_id: int
    codigo: Optional[str] = None
    descripcion: Optional[str] = None


class LinkOut(BaseModel):
    source: str
    match_status: str
    producto_item_id: Optional[int] = None
    producto: Optional[ProductRef] = None
    dangling: bool
    matched_sku: Optional[str] = None
    sku_field: Optional[str] = None
    linked_by: Optional[int] = None
    linked_at: Optional[datetime] = None
    note: Optional[str] = None
    evaluated_at: Optional[datetime] = None


class SuggestionOut(BaseModel):
    status: str
    producto_item_id: Optional[int] = None
    producto: Optional[ProductRef] = None
    candidates: list[ProductRef]
    candidate_count: int
    differs: bool


class UnitOut(BaseModel):
    variation_id: int
    live: bool
    sku: Optional[str] = None
    sku_field: Optional[str] = None
    link: Optional[LinkOut] = None
    suggestion: SuggestionOut


class ItemLinksOut(BaseModel):
    item_id: str
    title: Optional[str] = None
    status: Optional[str] = None
    units: list[UnitOut]


class WriteOut(BaseModel):
    changed: bool
    unit: UnitOut


class ListRowOut(BaseModel):
    item_id: str
    variation_id: int
    title: Optional[str] = None
    item_status: Optional[str] = None
    source: str
    match_status: str
    producto_item_id: Optional[int] = None
    matched_sku: Optional[str] = None
    sku_field: Optional[str] = None
    suggestion_status: Optional[str] = None
    suggested_producto_item_id: Optional[int] = None
    suggestion_candidates: Optional[int] = None
    linked_by: Optional[int] = None
    linked_at: Optional[datetime] = None
    note: Optional[str] = None
    evaluated_at: Optional[datetime] = None


class ListOut(BaseModel):
    items: list[ListRowOut]
    next_cursor: Optional[str] = None


class SampleOut(BaseModel):
    item_id: str
    variation_id: int


class CoverageOut(BaseModel):
    total_units: int
    classes: dict[str, int]
    by_status: dict[str, dict[str, dict[str, int]]]
    manual_differs: int
    samples: dict[str, list[SampleOut]]


class ManualLinkIn(BaseModel):
    """`extra=forbid`: a body naming `linked_by` (or anything else unknown) is refused, never ignored."""

    model_config = ConfigDict(extra="forbid")

    producto_item_id: int = Field(ge=1)
    note: Optional[str] = Field(default=None, max_length=NOTE_MAX)


class NoteIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    note: Optional[str] = Field(default=None, max_length=NOTE_MAX)


VariationId = Path(ge=0, description="`0` is the item-level unit of an item without variations")


# ── Helpers ──────────────────────────────────────────────────────


def _unit_of(db: Session, item_id: str, variation_id: int) -> dict[str, Any]:
    described = links.describe_item(db, item_id)
    return next(unit for unit in described["units"] if unit["variation_id"] == variation_id)


def _write(
    db: Session,
    item_id: str,
    variation_id: int,
    operation: Callable[..., links.ManualOutcome],
) -> WriteOut:
    """Run one manual operation and commit it, or roll everything back and answer with the refusal.

    `operation(db, now=..., events_enabled=...)` is a closure over the operation's own arguments. The link,
    its history, the event and the audit row are committed together here, in the request's one transaction.
    """
    if not links.read_flag("links"):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="La vinculación de productos está desactivada (links.enabled)",
        )
    events_enabled = links.read_flag("events")
    try:
        outcome = operation(db, now=datetime.now(timezone.utc), events_enabled=events_enabled)
        db.commit()
    except links.UnknownItem as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"No se encontró la publicación {exc}")
    except links.UnknownUnit:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"La variación {variation_id} no pertenece a la publicación {item_id}",
        )
    except links.ProductNotFound as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=f"El producto {exc} no existe")
    except Exception:
        db.rollback()
        raise
    return WriteOut(changed=outcome.changed, unit=_unit_of(db, item_id, variation_id))


# ── Reads (ml_ops.ver) ───────────────────────────────────────────


@router.get("/items/{item_id}/product-links", response_model=ItemLinksOut)
def get_item_links(
    item_id: str,
    _user: Usuario = Depends(require_permission(PERMISO_VER)),
    db: Session = Depends(get_links_db),
) -> dict[str, Any]:
    """The units of a publication (one, or one per variation) with their link and the SKU suggestion."""
    try:
        return links.describe_item(db, item_id)
    except links.UnknownItem:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"No se encontró la publicación {item_id}")


@router.get("/product-links", response_model=ListOut)
def list_links(
    cls: Literal["unmatched", "conflict", "manual_differs", "dangling"] = Query(alias="class"),
    cursor: Optional[str] = Query(default=None, description="`next_cursor` of the previous page"),
    limit: int = Query(default=links.LIST_DEFAULT, ge=1, le=links.LIST_MAX),
    _user: Usuario = Depends(require_permission(PERMISO_VER)),
    db: Session = Depends(get_links_db),
) -> dict[str, Any]:
    """Units of one class, keyset-paginated on `(item_id, variation_id)`."""
    try:
        return links.list_units(db, cls, cursor=cursor, limit=limit)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="Cursor inválido")


@router.get("/product-links/coverage", response_model=CoverageOut)
def get_coverage(
    samples: int = Query(default=links.DEFAULT_SAMPLE_SIZE, ge=0, le=SAMPLES_MAX),
    _user: Usuario = Depends(require_permission(PERMISO_VER)),
    db: Session = Depends(get_links_db),
) -> dict[str, Any]:
    """Link coverage: counts by class and item status, and a bounded sample of each class."""
    return links.coverage(db, sample_size=samples)


# ── Writes (ml_publicaciones.vincular, links.enabled) ────────────


@router.put("/items/{item_id}/product-links/{variation_id}", response_model=WriteOut)
def set_manual_link(
    item_id: str,
    body: ManualLinkIn,
    variation_id: int = VariationId,
    user: Usuario = Depends(require_permission(PERMISO_VINCULAR)),
    db: Session = Depends(get_links_db),
) -> WriteOut:
    """Link a unit to a product by hand (the product must exist). Manual always wins over the SKU rule."""
    return _write(
        db,
        item_id,
        variation_id,
        lambda session, **kw: links.set_manual(
            session, item_id, variation_id, body.producto_item_id, body.note, user.id, **kw
        ),
    )


@router.put("/items/{item_id}/product-links/{variation_id}/none", response_model=WriteOut)
def set_manual_none_link(
    item_id: str,
    body: NoteIn = NoteIn(),
    variation_id: int = VariationId,
    user: Usuario = Depends(require_permission(PERMISO_VINCULAR)),
    db: Session = Depends(get_links_db),
) -> WriteOut:
    """Mark a unit as explicitly having no product."""
    return _write(
        db,
        item_id,
        variation_id,
        lambda session, **kw: links.set_manual_none(session, item_id, variation_id, body.note, user.id, **kw),
    )


@router.post("/items/{item_id}/product-links/{variation_id}/revert-auto", response_model=WriteOut)
def revert_link_to_auto(
    item_id: str,
    variation_id: int = VariationId,
    user: Usuario = Depends(require_permission(PERMISO_VINCULAR)),
    db: Session = Depends(get_links_db),
) -> WriteOut:
    """Hand a unit back to the automatic rule, resolved right now with its current SKU."""
    return _write(
        db,
        item_id,
        variation_id,
        lambda session, **kw: links.revert_to_auto(session, item_id, variation_id, user.id, **kw),
    )
