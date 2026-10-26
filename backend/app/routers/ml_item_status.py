"""Pause or activate one publication at ML (Publicaciones ML, `ml_publicaciones.pausar`).

The decision lives in `ml_item_status_write_service`; this router gates it and maps each outcome to its HTTP answer:
a write done or not needed is 200, a write that may have landed is 202 (the item is being re-read), a publication that
cannot take that status is 409, ML refusing it is 422 with ML's message, and the kill switch off is 503.
"""

from __future__ import annotations

from typing import Literal, Optional

from fastapi import APIRouter, Depends, Path
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from app.api.deps import require_permiso
from app.core.database import get_db
from app.models.usuario import Usuario
from app.services.ml_item_status_write_service import (
    AMBIGUOUS,
    DISABLED,
    NOT_ELIGIBLE,
    REJECTED,
    SUBMITTED,
    UNCHANGED,
    set_item_status,
)
from app.services.ml_publications import admin

PERMISO_PAUSAR = "ml_publicaciones.pausar"

router = APIRouter(prefix="/ml-publications", tags=["ML Publications Status"])

_HTTP_STATUS = {SUBMITTED: 200, UNCHANGED: 200, AMBIGUOUS: 202, NOT_ELIGIBLE: 409, REJECTED: 422, DISABLED: 503}


class ItemStatusRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["paused", "active"]


class ItemStatusResponse(BaseModel):
    status: str
    message: Optional[str]


@router.post("/items/{item_id}/status", response_model=ItemStatusResponse)
async def change_item_status(
    body: ItemStatusRequest,
    item_id: str = Path(..., pattern=admin.ITEM_ID_PATTERN),
    user: Usuario = Depends(require_permiso(PERMISO_PAUSAR)),
    db: Session = Depends(get_db),
) -> JSONResponse:
    outcome = await set_item_status(db, item_id, body.status, user.id)
    return JSONResponse(
        status_code=_HTTP_STATUS[outcome.status],
        content=ItemStatusResponse(status=outcome.status, message=outcome.message).model_dump(),
    )
