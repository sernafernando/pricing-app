"""A publication's data overridden locally (Publicaciones ML T8): read it beside its original, and save it.

Reading needs `ml_ops.ver` (the Publicaciones ML screen); saving needs `ml_publicaciones.editar_publicacion`. Saving
never writes to Mercado Libre: the override is kept here and every read answers the original (what ML has), the
override and the applicable data. The rules live in `ml_item_override_service`.

Pushing the override to ML ("Actualizar en ML", T8c) is its own route, with the same permission: only what ML lets
change goes, and every field answers how it went or why it was left out (`ml_item_override_push_service`).
"""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime
from typing import Annotated, Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Path, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, StringConstraints
from sqlalchemy.orm import Session

from app.api.deps import require_permiso
from app.core.database import get_db
from app.models.usuario import Usuario
from app.schemas.publication_data import (
    MAX_ATRIBUTO_VALUE_LENGTH,
    MAX_DESCRIPCION_LENGTH,
    MAX_TITULO_LENGTH,
    NonBlank,
)
from app.services.ml_item_override_push_service import (
    DISABLED,
    NOT_ELIGIBLE,
    NOT_FOUND,
    NOT_SENT,
    NOTHING,
    SENT,
    UNKNOWN_STATUS,
    push_override,
)
from app.services.ml_item_override_service import (
    OverrideView,
    PublicacionNoEditable,
    read_override,
    save_override,
)
from app.services.ml_publications import admin
from app.services.ml_publications.publication_data import DatosNoValidos
from app.services.permisos_service import PermisosService

PERMISO_VER = "ml_ops.ver"
PERMISO_EDITAR = "ml_publicaciones.editar_publicacion"

router = APIRouter(prefix="/ml-item-overrides", tags=["Publicaciones ML"])

ItemId = Annotated[str, Path(pattern=admin.ITEM_ID_PATTERN)]


def get_ml_item_overrides_db(db: Session = Depends(get_db)) -> Session:
    """The session the publication store and the overrides are read and written through: the request's own (same
    database as the permission check). A separate dependency only so a test can point those tables elsewhere."""
    return db


class PublicationData(BaseModel):
    titulo: Optional[str]
    descripcion: Optional[str]
    fotos: list[dict[str, Any]]
    atributos: list[dict[str, Any]]


class OverrideData(BaseModel):
    """Each field None when it is not overridden (it follows ML)."""

    titulo: Optional[str]
    descripcion: Optional[str]
    fotos: Optional[list[dict[str, Any]]]
    atributos: Optional[list[dict[str, Any]]]


class OverrideResponse(BaseModel):
    item_id: str
    original: PublicationData  # what ML has, as the store last read it
    override: Optional[OverrideData]  # None: nothing overridden
    aplicado: PublicationData  # the override where there is one, else the original
    editable: bool  # False for a deleted publication
    updated_at: Optional[datetime]
    can_edit: bool


class AtributoOverride(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: NonBlank
    value_name: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=MAX_ATRIBUTO_VALUE_LENGTH)
    ]


class OverrideRequest(BaseModel):
    """Every field is required: null follows ML, a value overrides it (a blank description overrides with none).
    Every field null drops the override."""

    model_config = ConfigDict(extra="forbid")

    titulo: Optional[
        Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=MAX_TITULO_LENGTH)]
    ]
    descripcion: Optional[Annotated[str, StringConstraints(max_length=MAX_DESCRIPCION_LENGTH)]]
    fotos: Optional[list[NonBlank]]  # the publication's picture ids, in the new order
    atributos: Optional[list[AtributoOverride]]  # the publication's attributes with their new value


def _not_found(mla: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"No se encontró la publicación {mla}")


def _response(view: OverrideView, can_edit: bool) -> OverrideResponse:
    return OverrideResponse(**asdict(view), can_edit=can_edit)


@router.get("/{item_id}", response_model=OverrideResponse)
def get_override(
    item_id: ItemId,
    user: Usuario = Depends(require_permiso(PERMISO_VER)),
    auth_db: Session = Depends(get_db),
    db: Session = Depends(get_ml_item_overrides_db),
) -> OverrideResponse:
    """The publication's original data, its override and the applicable data, and whether the user may edit it."""
    view = read_override(db, item_id)
    if view is None:
        raise _not_found(item_id)
    return _response(view, PermisosService(auth_db).tiene_permiso(user, PERMISO_EDITAR))


@router.put("/{item_id}", response_model=OverrideResponse)
def put_override(
    body: OverrideRequest,
    item_id: ItemId,
    user: Usuario = Depends(require_permiso(PERMISO_EDITAR)),
    db: Session = Depends(get_ml_item_overrides_db),
) -> OverrideResponse:
    """Save the override, never touching ML. 409 for a deleted publication; 422 for a picture or attribute that is
    not the publication's."""
    try:
        view = save_override(
            db,
            item_id,
            body.titulo,
            body.descripcion,
            body.fotos,
            None if body.atributos is None else [(atributo.id, atributo.value_name) for atributo in body.atributos],
            user.id,
        )
    except PublicacionNoEditable as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except DatosNoValidos as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    if view is None:
        raise _not_found(item_id)
    return _response(view, True)


_PUSH_HTTP_STATUS = {
    SENT: 200,
    NOTHING: 200,
    NOT_FOUND: 404,
    NOT_ELIGIBLE: 409,
    DISABLED: 503,
    NOT_SENT: 503,
    UNKNOWN_STATUS: 503,
}


class PushParte(BaseModel):
    campo: str  # titulo, fotos, atributos or descripcion
    estado: str  # submitted, rejected, ambiguous, not_sent or omitted
    motivo: Optional[str]


class PushResponse(BaseModel):
    status: str
    message: Optional[str]
    partes: list[PushParte]


@router.post("/{item_id}/ml", response_model=PushResponse)
async def push_override_to_ml(
    item_id: ItemId,
    user: Usuario = Depends(require_permiso(PERMISO_EDITAR)),
) -> JSONResponse:
    """Send the override to ML. 200 with each field's state when something was sent or nothing could be; 404 for an
    unknown MLA; 409 for a publication ML does not let modify (catalog, deleted, closed); 503 when nothing reached ML
    (the kill switch off, the store unreadable, the proxy not forwarding any write)."""
    outcome = await push_override(item_id, user.id)
    content = PushResponse(
        status=outcome.status,
        message=outcome.message,
        partes=[PushParte(**asdict(parte)) for parte in outcome.partes],
    )
    return JSONResponse(status_code=_PUSH_HTTP_STATUS[outcome.status], content=content.model_dump())
