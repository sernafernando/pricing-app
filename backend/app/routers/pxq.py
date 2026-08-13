"""Router for MercadoLibre PxQ (wholesale, price-by-quantity) tiers (PR 3b).

Two endpoints:
  * `GET /pxq/{item_id}/live` -- always-visible live ML read, pool-safe
    (`get_current_user_transient`, no `Depends(get_db)`; the DB session used
    to load the local mirror is opened and CLOSED before the ML proxy call,
    per `backend/CLAUDE.md`'s QueuePool-exhaustion rule).
  * `POST /pxq/{item_id}/sync` -- the write path, orchestrated entirely by
    `ml_pxq_write_service.sync_pxq_tiers` (kill-switch, permission,
    eligibility, fresh live read, divergence gate, POST, confirmation
    re-read, snapshot). This is a normal bounded request/response, not
    long-lived, so it uses the regular `get_current_user` + `Depends(get_db)`.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_current_user_transient
from app.core.database import get_background_db, get_db
from app.models.ml_pxq_tier import MlPxqTier
from app.models.publicacion_ml import PublicacionML
from app.models.usuario import Usuario
from app.services.ml_pxq_adopt_service import adopt_live_pxq_tiers
from app.services.ml_pxq_write_service import sync_pxq_tiers
from app.services.ml_webhook_client import ml_webhook_client
from app.services.permisos_service import PermisosService
from app.services.pxq_permissions_backfill import PXQ_ESCRIBIR_CODE, PXQ_VER_CODE
from app.services.pxq_tier_service import create_pxq_tier, delete_pxq_tier, update_pxq_tier

router = APIRouter(prefix="/pxq", tags=["ML PxQ"])


class PxqLiveTier(BaseModel):
    """One tier as reported by MercadoLibre right now."""

    id: str
    quantity: int
    amount: float

    model_config = ConfigDict(from_attributes=True)


class PxqMirrorTier(BaseModel):
    """One local mirror row, plain/detached -- loaded inside the short-lived
    session and read only AFTER it is closed."""

    id: int
    cantidad_minima: int
    precio_unitario: float
    costo_envio_total: Optional[float] = None
    ml_price_id: Optional[str] = None
    estado: str

    model_config = ConfigDict(from_attributes=True)


class PxqLiveStateResponse(BaseModel):
    """Response for `GET /pxq/{item_id}/live`. Never server-side cached --
    every call re-hits the proxy. `live_status='unavailable'` still returns
    HTTP 200 with `live_tiers=None` (fail-closed on the client, not a 500)."""

    item_id: str
    live_status: str
    live_tiers: Optional[List[PxqLiveTier]] = None
    mirror_tiers: List[PxqMirrorTier]
    fetched_at: datetime

    model_config = ConfigDict(from_attributes=True)


class PxqSyncRequest(BaseModel):
    allow_clear: bool = False


class PxqCreateTierRequest(BaseModel):
    cantidad_minima: int
    precio_unitario: float
    costo_envio_total: Optional[float] = None


class PxqUpdateTierRequest(BaseModel):
    """All fields optional: only the ones present are changed.

    Deliberately has NO `cantidad_sincronizada`/`precio_sincronizado` fields --
    those are the ML-confirmed snapshot and can only advance via a confirmed
    write (`pxq_confirm`), never through this edit endpoint (see
    `pxq_tier_service.update_pxq_tier`)."""

    cantidad_minima: Optional[int] = None
    precio_unitario: Optional[float] = None
    costo_envio_total: Optional[float] = None


class PxqDivergenceItem(BaseModel):
    ml_price_id: Optional[str] = None
    reason: str
    live: Optional[Dict[str, Any]] = None
    desired: Optional[Dict[str, Any]] = None


class PxqSyncResult(BaseModel):
    synced: bool
    status: str
    detail: Optional[Any] = None
    reason: Optional[str] = None
    divergences: Optional[List[PxqDivergenceItem]] = None
    array: Optional[List[Dict[str, Any]]] = None
    status_code: Optional[int] = None

    model_config = ConfigDict(from_attributes=True)


class PxqSkippedLiveTier(BaseModel):
    """One live MercadoLibre price the import knowingly did NOT mirror.

    Its own shape, NOT `PxqMirrorTier`: there is no mirror row behind it and
    there never will be, so every other field of that model would be a
    fabrication. What it carries is the minimum that identifies the entry on
    MercadoLibre -- `GET /{item_id}/live` will keep reporting it in
    `live_tiers` forever while the mirror column stays one row short, and
    this is what says why.
    """

    ml_price_id: str
    cantidad_minima: int

    model_config = ConfigDict(from_attributes=True)


class PxqAdoptResult(BaseModel):
    """Result of `POST /pxq/{item_id}/adopt-live`.

    `imported` reuses `PxqMirrorTier` rather than declaring a parallel shape:
    these ARE mirror rows, and a second shape for the same table is how the
    panel's rendering and the import's response drift apart.

    `skipped_count`/`skipped` are ADDITIVE -- both default to empty, so a
    client that predates them reads exactly the response it always did. They
    exist because `count` alone is ambiguous: `count == 0` with an empty
    `skipped` means MercadoLibre holds no tiers, and `count == 0` with a
    non-empty one means it holds prices this mirror cannot represent. Those
    are opposite facts and the panel says opposite things about them."""

    item_id: str
    count: int
    imported: List[PxqMirrorTier]
    skipped_count: int = 0
    skipped: List[PxqSkippedLiveTier] = Field(default_factory=list)

    model_config = ConfigDict(from_attributes=True)


def _unavailable_response(item_id, mirror_tiers, fetched_at) -> PxqLiveStateResponse:
    """The single shape for "we could not read live state".

    `live_tiers` is None, never []. An empty list asserts that MercadoLibre
    holds no tiers, and that is a claim we do not have — a client would render
    "0 live tiers" where the truth is "unknown", on the money path.
    """
    return PxqLiveStateResponse(
        item_id=item_id,
        live_status="unavailable",
        live_tiers=None,
        mirror_tiers=mirror_tiers,
        fetched_at=fetched_at,
    )


def _parse_live_tiers(live_raw: Optional[list]) -> Optional[List[PxqLiveTier]]:
    """Parses the proxy payload, or returns None if it cannot be trusted.

    None means the same as no read at all: the endpoint answers 200 with
    `live_status="unavailable"`. A malformed entry is not an error to raise at
    the client — this endpoint exists to SHOW live state beside local state,
    and a 500 shows nothing.

    `id` is coerced explicitly because MercadoLibre may return it as a number
    and pydantic v2 does not coerce int to str. The write service already did
    `str(entry["id"])` on this same payload, so both paths now read one source
    under one contract. An earlier fix swapped subscripts for `.get()`, which
    only turned KeyError into ValidationError — both still reached the client
    as a 500.
    """
    if live_raw is None:
        return None
    try:
        return [
            PxqLiveTier(
                id=str(entry["id"]),
                quantity=entry["quantity"],
                amount=entry["amount"],
            )
            for entry in live_raw
        ]
    except (KeyError, TypeError, ValidationError):
        return None


def _error_detail_from_outcome(outcome: dict) -> dict:
    """Keeps the whole outcome as the error detail.

    Collapsing it to a status string discarded the `divergences` payload, and
    the spec requires a refused write to DISPLAY the divergence for manual
    resolution — without it the UI has a 409 and nothing to show. Also
    preserves `status_code` on a proxy rejection.
    """
    detail = {k: v for k, v in outcome.items() if k != "synced"}
    detail.setdefault("status", outcome.get("status"))
    return detail


# Every non-success status MUST appear here. An unmapped one falls through to
# 200 OK, which is exactly how `submitted_unconfirmed` reached callers as a
# finished write.
_SYNC_STATUS_TO_HTTP = {
    # 503, not 403: a user WITH permission hitting a disabled feature and a
    # user WITHOUT permission must not get the same answer, or the UI cannot
    # tell "ask for access" from "this is switched off".
    "disabled": status.HTTP_503_SERVICE_UNAVAILABLE,
    "rejected_not_eligible": status.HTTP_422_UNPROCESSABLE_ENTITY,
    "rejected_read_unavailable": status.HTTP_503_SERVICE_UNAVAILABLE,
    # Transient, like the read failure — not a 422 about the account.
    "rejected_eligibility_unknown": status.HTTP_503_SERVICE_UNAVAILABLE,
    "divergence": status.HTTP_409_CONFLICT,
    "rejected_by_proxy": status.HTTP_422_UNPROCESSABLE_ENTITY,
    # Neither of these is a success: the write's real outcome is unknown and a
    # human has to reconcile before anything else is attempted.
    "submitted_unconfirmed": status.HTTP_502_BAD_GATEWAY,
    "ambiguous_needs_reconcile": status.HTTP_502_BAD_GATEWAY,
}


def _require_pxq_read(current_user: Usuario, db: Session) -> None:
    """Checks `pxq.ver` for a user that may be DETACHED.

    `get_current_user_transient` deliberately returns a user unbound from the
    session that loaded it, so the permission lookup — which walks `rol_obj`
    and the override relationships — raised DetachedInstanceError on the first
    lazy load. It never surfaced because every test for this endpoint patched
    this function out, leaving the one control guarding live ML data
    unexercised.

    Re-loading the user inside the caller's session keeps the check real
    without holding a session across the proxy call.
    """
    bound_user = db.get(Usuario, current_user.id)
    if bound_user is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=f"No tienes permiso: {PXQ_VER_CODE}")
    permisos = PermisosService(db)
    if not permisos.tiene_permiso(bound_user, PXQ_VER_CODE):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=f"No tienes permiso: {PXQ_VER_CODE}")


def _require_pxq_write(current_user: Usuario, db: Session) -> None:
    """Checks `pxq.escribir` for create/update/delete on tiers."""
    permisos = PermisosService(db)
    if not permisos.tiene_permiso(current_user, PXQ_ESCRIBIR_CODE):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=f"No tienes permiso: {PXQ_ESCRIBIR_CODE}")


def _get_publicacion_or_404(db: Session, item_id: str) -> PublicacionML:
    publicacion = db.query(PublicacionML).filter(PublicacionML.mla == item_id).first()
    if publicacion is None:
        raise HTTPException(status_code=404, detail=f"item_id={item_id} does not exist")
    return publicacion


def _get_tier_for_item_or_404(db: Session, item_id: str, tier_id: int) -> MlPxqTier:
    """Loads a tier and confirms it belongs to `item_id`.

    `tier_id` alone is enough for the service layer to find the row, but the
    path also carries `item_id` (to match every other endpoint here) -- a
    mismatch means the caller is aiming at the wrong publication's tier, so it
    is treated the same as "not found" rather than silently operating on it.
    """
    tier = db.get(MlPxqTier, tier_id)
    if tier is None or tier.item_id != item_id:
        raise HTTPException(status_code=404, detail=f"tier_id={tier_id} does not exist for item_id={item_id}")
    return tier


@router.post("/{item_id}/tiers", response_model=PxqMirrorTier, status_code=status.HTTP_201_CREATED)
def crear_tier_pxq(
    item_id: str,
    body: PxqCreateTierRequest,
    current_user: Usuario = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> PxqMirrorTier:
    """Creates a local PxQ tier for `item_id`. This endpoint only touches our
    own DB (no ML call), so unlike the live-read endpoint it does not need the
    transient-user/short-session dance -- an ordinary bounded request/response
    is fine here (see module docstring)."""
    _require_pxq_write(current_user, db)
    publicacion = _get_publicacion_or_404(db, item_id)
    tier = create_pxq_tier(
        db,
        publicacion_ml_id=publicacion.id,
        item_id=item_id,
        cantidad_minima=body.cantidad_minima,
        precio_unitario=body.precio_unitario,
        usuario_id=current_user.id,
        costo_envio_total=body.costo_envio_total,
    )
    db.commit()
    db.refresh(tier)
    return PxqMirrorTier.model_validate(tier)


@router.patch("/{item_id}/tiers/{tier_id}", response_model=PxqMirrorTier)
def editar_tier_pxq(
    item_id: str,
    tier_id: int,
    body: PxqUpdateTierRequest,
    current_user: Usuario = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> PxqMirrorTier:
    """Edits quantity/price on an existing tier. Same no-ML-call reasoning as
    `crear_tier_pxq` applies -- ordinary session, no transient-user dance.

    Never advances `cantidad_sincronizada`/`precio_sincronizado`: see
    `pxq_tier_service.update_pxq_tier`."""
    _require_pxq_write(current_user, db)
    _get_tier_for_item_or_404(db, item_id, tier_id)
    tier = update_pxq_tier(
        db,
        tier_id=tier_id,
        cantidad_minima=body.cantidad_minima,
        precio_unitario=body.precio_unitario,
        costo_envio_total=body.costo_envio_total,
    )
    db.commit()
    db.refresh(tier)
    return PxqMirrorTier.model_validate(tier)


@router.delete("/{item_id}/tiers/{tier_id}", status_code=status.HTTP_204_NO_CONTENT)
def eliminar_tier_pxq(
    item_id: str,
    tier_id: int,
    current_user: Usuario = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> None:
    """Deletes the local mirror row only. This does NOT remove the tier from
    MercadoLibre by itself: the array-replace diff (PR 3) reads from this
    table, so ML still holds the old tier until the next `POST
    /{item_id}/sync`. If the deleted row had an `ml_price_id`, that sync is
    still pending after this call returns 204 -- there is nothing left in this
    endpoint's response to say so, so callers that care must check for a
    pending sync via the live/mirror comparison on `GET /{item_id}/live`."""
    _require_pxq_write(current_user, db)
    _get_tier_for_item_or_404(db, item_id, tier_id)
    delete_pxq_tier(db, tier_id=tier_id)
    db.commit()


@router.get("/{item_id}/live", response_model=PxqLiveStateResponse)
async def obtener_estado_live_pxq(
    item_id: str,
    current_user: Usuario = Depends(get_current_user_transient),
) -> PxqLiveStateResponse:
    """Loads the local mirror in a short `with` block (closed before any ML
    call), then performs the fresh proxy read with NO session held -- see
    module docstring / `backend/CLAUDE.md`."""
    with get_background_db() as db:
        _require_pxq_read(current_user, db)
        # Explicitly ordered, not left to the storage engine. A tier is a
        # QUANTITY THRESHOLD, so an endpoint that hands thresholds back in
        # arbitrary row order is a latent defect for every consumer, not just
        # the panel reading it today. The frontend sorts as well -- that is what
        # guarantees what the operator actually sees, cache included -- but the
        # API has to be deterministic on its own.
        mirror_tiers = [
            PxqMirrorTier.model_validate(row)
            for row in db.query(MlPxqTier)
            .filter(MlPxqTier.item_id == item_id)
            .order_by(MlPxqTier.cantidad_minima)
            .all()
        ]
    # Session is closed here -- the proxy call below holds no DB session.

    live_raw = await ml_webhook_client.get_pxq_prices(item_id)
    fetched_at = datetime.now(timezone.utc)
    if live_raw is None:
        return _unavailable_response(item_id, mirror_tiers, fetched_at)
    live_tiers = _parse_live_tiers(live_raw)
    if live_tiers is None:
        return _unavailable_response(item_id, mirror_tiers, fetched_at)
    return PxqLiveStateResponse(
        item_id=item_id,
        live_status="ok",
        live_tiers=live_tiers,
        mirror_tiers=mirror_tiers,
        fetched_at=fetched_at,
    )


@router.post("/{item_id}/sync", response_model=PxqSyncResult)
def sincronizar_pxq(
    item_id: str,
    body: PxqSyncRequest,
    current_user: Usuario = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> PxqSyncResult:
    """Orchestrates a full PxQ sync via `ml_pxq_write_service.sync_pxq_tiers`
    (kill-switch -> permission -> eligibility -> fresh live read ->
    divergence -> POST -> confirmation re-read -> snapshot). Declared `def`
    (not `async def`): the service performs synchronous DB writes bridged
    with the async client via `resolve_maybe_async` -- same pattern as
    `refrescar_competencia_catalogo_item`."""
    outcome = sync_pxq_tiers(db, current_user, item_id, allow_clear=body.allow_clear)
    http_status = _SYNC_STATUS_TO_HTTP.get(outcome["status"])
    if http_status is not None:
        raise HTTPException(status_code=http_status, detail=_error_detail_from_outcome(outcome))
    return PxqSyncResult(**outcome)


@router.post("/{item_id}/adopt-live", response_model=PxqAdoptResult)
def adoptar_tramos_live_pxq(
    item_id: str,
    current_user: Usuario = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> PxqAdoptResult:
    """Imports MercadoLibre's LIVE PxQ tiers into an EMPTY local mirror, via
    `ml_pxq_adopt_service.adopt_live_pxq_tiers`. Import-only: no ML write
    endpoint is called on any path, and it is deliberately NOT gated by
    `PXQ_WRITE_ENABLED` -- that switch scopes the irreversible outbound
    array-replace POST, while this writes only local, reversible rows.

    No request body: there is no option to express here, and an optional flag
    on an import verb is exactly how `sync` acquired `allow_clear`.

    Declared `def` (not `async def`) for the same reason as `sincronizar_pxq`:
    the service performs synchronous DB writes and bridges the async client
    with `resolve_maybe_async`.

    Dependencies are `get_current_user` + `Depends(get_db)`, NOT the
    transient/short-session pair `GET /{item_id}/live` uses. Two reasons, and
    the second is decisive: (a) the QueuePool rule is about endpoints whose
    session stays pinned for an UNBOUNDED response lifetime (SSE, WebSocket),
    not about "a proxy call happens" -- `POST /{item_id}/sync` already makes
    up to four proxy calls while holding `Depends(get_db)`, and this path makes
    one READ; (b) `get_current_user_transient` returns a DETACHED user, and
    unlike `_require_pxq_read` (whose docstring records why it must)
    `_require_pxq_write` does not re-bind it -- handing it a detached user
    would raise DetachedInstanceError on the permission walk, on the one
    control guarding a write.

    Refusals raised by the service (409 `adopt_conflict`, 503
    `adopt_read_unavailable`) propagate untouched: their `detail` dicts carry
    the conflicting quantities and tier ids the operator needs, and flattening
    them to a status string leaves a refusal with nothing to act on.

    A PARTIAL import is a 200, not a refusal: the service skips live prices
    this mirror cannot represent (`cantidad_minima <= 1`) and reports them in
    `skipped`. Surfaced rather than swallowed because no mirror row is created
    for them, while `GET /{item_id}/live` goes on reporting them in
    `live_tiers` -- so the panel shows a live tier with no counterpart, and
    this response is the only thing that accounts for the difference.
    """
    # Defence in depth: `adopt_live_pxq_tiers` checks `pxq.escribir` again.
    # That duplication is DELIBERATE -- do not "de-duplicate" it. It mirrors
    # the three CRUD routes above, and it is what guarantees the permission
    # refuses before any ML traffic regardless of how the service is reordered
    # or who else calls it later.
    _require_pxq_write(current_user, db)
    publicacion = _get_publicacion_or_404(db, item_id)
    # The service commits exactly once, and that commit is what releases the
    # publication row lock -- so the router must NOT commit as well.
    outcome = adopt_live_pxq_tiers(db, current_user, item_id, publicacion_ml_id=publicacion.id)
    return PxqAdoptResult(
        item_id=item_id,
        count=len(outcome.imported),
        imported=[PxqMirrorTier.model_validate(row) for row in outcome.imported],
        skipped_count=len(outcome.skipped),
        skipped=[PxqSkippedLiveTier.model_validate(entry) for entry in outcome.skipped],
    )
