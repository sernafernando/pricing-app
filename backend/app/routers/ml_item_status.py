"""Pause or activate one publication at ML (Publicaciones ML, `ml_publicaciones.pausar`).

The decision lives in `ml_item_status_write_service`; this router gates it and maps each outcome to its HTTP answer:
a write done or not needed is 200, a write that may have landed is 202 (the item is being re-read), a publication that
cannot take that status is 409, ML refusing it is 422 with ML's message, and nothing reaching ML (the kill switch
off, the proxy not sending it, the store unreadable) is 503.

The bulk route writes one small batch the page sends in turn (the set comes from `view/status-item-ids`), so no
request waits on hundreds of ML writes; it answers each publication's outcome, always 200.
"""

from __future__ import annotations

from typing import Annotated, Literal, Optional

from fastapi import APIRouter, Depends, Path
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from app.api.deps import require_permiso
from app.models.usuario import Usuario
from app.services.ml_item_status_write_service import (
    AMBIGUOUS,
    DISABLED,
    NOT_ELIGIBLE,
    NOT_SENT,
    REJECTED,
    SUBMITTED,
    UNCHANGED,
    UNKNOWN_STATUS,
    set_item_status,
)
from app.services.ml_publications import admin

PERMISO_PAUSAR = "ml_publicaciones.pausar"

# The most publications one bulk request writes: each is a separate write through the proxy's throttle.
BULK_BATCH_SIZE = 20

router = APIRouter(prefix="/ml-publications", tags=["ML Publications Status"])

_HTTP_STATUS = {
    SUBMITTED: 200,
    UNCHANGED: 200,
    AMBIGUOUS: 202,
    NOT_ELIGIBLE: 409,
    REJECTED: 422,
    DISABLED: 503,
    NOT_SENT: 503,
    UNKNOWN_STATUS: 503,
}


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
) -> JSONResponse:
    outcome = await set_item_status(item_id, body.status, user.id)
    return JSONResponse(
        status_code=_HTTP_STATUS[outcome.status],
        content=ItemStatusResponse(status=outcome.status, message=outcome.message).model_dump(),
    )


ItemId = Annotated[str, StringConstraints(pattern=admin.ITEM_ID_PATTERN)]


class ItemStatusBulkRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["paused", "active"]
    item_ids: list[ItemId] = Field(..., min_length=1, max_length=BULK_BATCH_SIZE)


class ItemStatusBulkResult(ItemStatusResponse):
    item_id: str


class ItemStatusBulkResponse(BaseModel):
    results: list[ItemStatusBulkResult]


@router.post("/items/status-bulk", response_model=ItemStatusBulkResponse)
async def change_items_status(
    body: ItemStatusBulkRequest,
    user: Usuario = Depends(require_permiso(PERMISO_PAUSAR)),
) -> dict:
    """Writes one batch of a bulk pause / activate: each publication once (a repeated MLA is dropped), in the order
    asked, each through `set_item_status`, which checks it again. Always 200, with every publication's own outcome:
    one refused never stops the rest. At most `BULK_BATCH_SIZE` per request -- the page sends the set in batches."""
    results = []
    for item_id in dict.fromkeys(body.item_ids):  # one write per publication, in the order asked
        outcome = await set_item_status(item_id, body.status, user.id)
        results.append({"item_id": item_id, "status": outcome.status, "message": outcome.message})
    return {"results": results}
