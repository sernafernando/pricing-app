"""Router: ML operations sale-centric view (slice 4 of
ml-ventas-fuente-de-verdad).

Design D4: one storage layer, two read surfaces. This router is the
sale-centric one -- order + items + shipment + linked claim + linked
questions/messages, resolved through `ml_operation_links`. The existing
`ml_bot` router (bot-centric, keyed on question/message) is UNCHANGED by
this module; see `tests/integration/test_ml_ventas_ops_router.py` for the
regression proof.

Gated by:
- `ml_ops.ver` permission (no permission -> 403), checked FIRST.
- `ML_ORDERS_OPS_ENABLED` (flag OFF -> 503, spec: inert by default), checked
  only once permission is confirmed.

Permission is intentionally checked before the flag (same precedent/
rationale as `pxq.py`'s `_SYNC_STATUS_TO_HTTP` comment): a user WITHOUT
permission must always get 403 regardless of flag state, or the response
would leak whether the feature exists/is enabled to someone who cannot use
it either way. 503 then unambiguously means "you can use this, but it's
switched off right now" for a user who already cleared the permission gate.
"""

from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.config import settings
from app.core.database import get_db
from app.models.ml_bot_message import MlBotMessage
from app.models.ml_bot_question import MlBotQuestion
from app.models.ml_orders_ops import (
    UNENUMERABLE_KIND,
    MlOperationLink,
    MlOpsDivergence,
    MlOrderItemOps,
    MlOrdersOps,
    MlShipmentOps,
)
from app.models.rma_claim_ml import RmaClaimML
from app.models.usuario import Usuario
from app.services.permisos_service import PermisosService

DIVERGENCE_KINDS = (
    "missing_in_gbp",
    "missing_in_ml",
    "field_mismatch",
    "out_of_window_update",
    UNENUMERABLE_KIND,
    "unknown",
)
DIVERGENCE_STATES = ("open", "acknowledged", "resolved", "ignored")
# `window_not_enumerable` uses `order_id=0` as a sentinel (no single order
# for an unenumerable leaf, see `sweep_service.record_unenumerable_window`)
# -- MUST NOT render as an order id (mandatory debt from slice 3).
_UNENUMERABLE_SENTINEL_ORDER_ID = 0

router = APIRouter(prefix="/ml-ventas-ops", tags=["ML Ventas Ops"])


def require_permission(permission: str):
    """Dependency for a required permission code -- same pattern as
    `document_templates.py`/`alertas.py`, reused rather than reinvented."""

    def _check_permission(
        current_user: Usuario = Depends(get_current_user),
        db: Session = Depends(get_db),
    ) -> Usuario:
        permisos_service = PermisosService(db)
        if not permisos_service.tiene_permiso(current_user, permission):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"No tienes permiso: {permission}",
            )
        return current_user

    return _check_permission


def _require_flag_enabled() -> None:
    if not settings.ML_ORDERS_OPS_ENABLED:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="ML operations source-of-truth is disabled (ML_ORDERS_OPS_ENABLED=false)",
        )


# ── Schemas ──────────────────────────────────────────────────────


class OrderOpsSummary(BaseModel):
    order_id: int
    pack_id: Optional[int] = None
    status: Optional[str] = None
    status_detail: Optional[str] = None
    buyer_id: Optional[int] = None
    buyer_nickname: Optional[str] = None
    seller_id: int
    total_amount: Optional[float] = None
    paid_amount: Optional[float] = None
    currency_id: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


class OrderItemOpsSummary(BaseModel):
    item_id: str
    variation_id: Optional[int] = None
    seller_sku: Optional[str] = None
    title: Optional[str] = None
    quantity: Optional[int] = None
    unit_price: Optional[float] = None

    model_config = ConfigDict(from_attributes=True)


class ShipmentOpsSummary(BaseModel):
    shipment_id: int
    status: Optional[str] = None
    substatus: Optional[str] = None
    tracking_number: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


class ClaimSummary(BaseModel):
    claim_id: int
    claim_type: Optional[str] = None
    status: Optional[str] = None
    reason_category: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


class QuestionSummary(BaseModel):
    ml_question_id: int
    item_id: str
    question_text: str
    status: str

    model_config = ConfigDict(from_attributes=True)


class MessageSummary(BaseModel):
    ml_message_id: str
    text: str
    status: str

    model_config = ConfigDict(from_attributes=True)


class SaleCentricOperation(BaseModel):
    order: OrderOpsSummary
    items: List[OrderItemOpsSummary]
    shipment: Optional[ShipmentOpsSummary] = None
    claim: Optional[ClaimSummary] = None
    questions: List[QuestionSummary]
    messages: List[MessageSummary]

    model_config = ConfigDict(from_attributes=True)


class DivergenceSummary(BaseModel):
    """A single `ml_ops_divergence` row. `order_id` is `None` for
    `window_not_enumerable` rows (see `_UNENUMERABLE_SENTINEL_ORDER_ID`);
    `window_from`/`window_to` carry that kind's leaf bounds instead."""

    id: int
    order_id: Optional[int] = None
    kind: str
    field: Optional[str] = None
    ml_value: Optional[str] = None
    gbp_value: Optional[str] = None
    window_from: Optional[str] = None
    window_to: Optional[str] = None
    state: str
    assigned_to_id: Optional[int] = None
    note: Optional[str] = None
    detected_at: datetime = Field(
        description=(
            "When this divergence was FIRST detected, or first detected since it last "
            "reopened -- not when it was last seen. Detection skips a divergence whose "
            "values have not changed, so this timestamp does not advance while the same "
            "difference persists. `out_of_window_update` and `window_not_enumerable` "
            "come from a different write path and do mean last seen."
        )
    )
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)

    @classmethod
    def from_row(cls, row: MlOpsDivergence) -> "DivergenceSummary":
        is_unenumerable = row.kind == UNENUMERABLE_KIND and row.order_id == _UNENUMERABLE_SENTINEL_ORDER_ID
        return cls(
            id=row.id,
            order_id=None if is_unenumerable else row.order_id,
            kind=row.kind,
            field=None if is_unenumerable else row.field,
            ml_value=None if is_unenumerable else row.ml_value,
            gbp_value=None if is_unenumerable else row.gbp_value,
            window_from=row.ml_value if is_unenumerable else None,
            window_to=row.gbp_value if is_unenumerable else None,
            state=row.state,
            assigned_to_id=row.assigned_to_id,
            note=row.note,
            detected_at=row.detected_at,
            updated_at=row.updated_at,
        )


class DivergenceListResponse(BaseModel):
    total: int
    limit: int
    offset: int
    divergences: List[DivergenceSummary]


class DivergenceUpdateRequest(BaseModel):
    state: Optional[str] = Field(default=None, description="One of: " + ", ".join(DIVERGENCE_STATES))
    assigned_to_id: Optional[int] = None
    note: Optional[str] = None


# ── Endpoints ────────────────────────────────────────────────────


@router.get("/orders/{order_id}", response_model=SaleCentricOperation)
def obtener_operacion(
    order_id: int,
    current_user: Usuario = Depends(require_permission("ml_ops.ver")),
    db: Session = Depends(get_db),
) -> SaleCentricOperation:
    """Sale-centric view: the order plus everything `ml_operation_links`
    resolved to it (shipment, claim, questions, messages) as one operation.
    Requires `ml_ops.ver`. 503 while `ML_ORDERS_OPS_ENABLED` is false."""
    _require_flag_enabled()

    order = db.query(MlOrdersOps).filter(MlOrdersOps.order_id == order_id).first()
    if order is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Orden no encontrada")

    items = db.query(MlOrderItemOps).filter(MlOrderItemOps.order_id == order_id).all()

    shipment = None
    if order.shipping_id is not None:
        shipment = db.query(MlShipmentOps).filter(MlShipmentOps.shipment_id == order.shipping_id).first()

    links = db.query(MlOperationLink).filter(MlOperationLink.order_id == order_id).all()
    claim_ids = [link.entity_id for link in links if link.entity_type == "claim"]
    question_ids = [link.entity_id for link in links if link.entity_type == "question"]
    message_ids = [link.entity_id for link in links if link.entity_type == "message"]

    claim = None
    if claim_ids:
        claim = db.query(RmaClaimML).filter(RmaClaimML.id.in_(claim_ids)).first()

    questions = db.query(MlBotQuestion).filter(MlBotQuestion.id.in_(question_ids)).all() if question_ids else []
    messages = db.query(MlBotMessage).filter(MlBotMessage.id.in_(message_ids)).all() if message_ids else []

    return SaleCentricOperation(
        order=OrderOpsSummary.model_validate(order),
        items=[OrderItemOpsSummary.model_validate(item) for item in items],
        shipment=ShipmentOpsSummary.model_validate(shipment) if shipment else None,
        claim=ClaimSummary.model_validate(claim) if claim else None,
        questions=[QuestionSummary.model_validate(q) for q in questions],
        messages=[MessageSummary.model_validate(m) for m in messages],
    )


@router.get("/divergences", response_model=DivergenceListResponse)
def listar_divergencias(
    kind: Optional[str] = Query(default=None, description="Filter by kind"),
    state: Optional[str] = Query(default=None, description="Filter by state"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    current_user: Usuario = Depends(require_permission("ml_ops.ver")),
    db: Session = Depends(get_db),
) -> DivergenceListResponse:
    """Paginated (slice 4a precedent: every list endpoint MUST paginate).
    Requires `ml_ops.ver`. 503 while `ML_ORDERS_OPS_ENABLED` is false."""
    _require_flag_enabled()

    if kind is not None and kind not in DIVERGENCE_KINDS:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f"kind inválido: {kind}")
    if state is not None and state not in DIVERGENCE_STATES:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f"state inválido: {state}")

    query = db.query(MlOpsDivergence)
    if kind is not None:
        query = query.filter(MlOpsDivergence.kind == kind)
    if state is not None:
        query = query.filter(MlOpsDivergence.state == state)

    total = query.count()
    rows = (
        query.order_by(MlOpsDivergence.detected_at.desc(), MlOpsDivergence.id.desc()).limit(limit).offset(offset).all()
    )

    return DivergenceListResponse(
        total=total,
        limit=limit,
        offset=offset,
        divergences=[DivergenceSummary.from_row(row) for row in rows],
    )


@router.get("/divergences/{divergence_id}", response_model=DivergenceSummary)
def obtener_divergencia(
    divergence_id: int,
    current_user: Usuario = Depends(require_permission("ml_ops.ver")),
    db: Session = Depends(get_db),
) -> DivergenceSummary:
    """Requires `ml_ops.ver`. 503 while `ML_ORDERS_OPS_ENABLED` is false."""
    _require_flag_enabled()

    row = db.query(MlOpsDivergence).filter(MlOpsDivergence.id == divergence_id).first()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Divergencia no encontrada")
    return DivergenceSummary.from_row(row)


@router.patch("/divergences/{divergence_id}", response_model=DivergenceSummary)
def actualizar_divergencia(
    divergence_id: int,
    payload: DivergenceUpdateRequest,
    current_user: Usuario = Depends(require_permission("ml_ops.gestionar")),
    db: Session = Depends(get_db),
) -> DivergenceSummary:
    """State/assignee/note changes. Requires `ml_ops.gestionar`, distinct
    from the read-only `ml_ops.ver`. 503 while `ML_ORDERS_OPS_ENABLED` is
    false. Never touches the ML/GBP data the divergence describes -- only
    this row's own bookkeeping (`state`, `assigned_to_id`, `note`)."""
    _require_flag_enabled()

    row = db.query(MlOpsDivergence).filter(MlOpsDivergence.id == divergence_id).first()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Divergencia no encontrada")

    # `exclude_unset` via `model_fields_set` distinguishes an ABSENT field
    # (leave alone) from an EXPLICIT `null` (clear it) -- a plain
    # `is not None` check treated both the same, so `{"assigned_to_id":
    # null}` silently did nothing while still returning 200 with the old
    # assignee: the operator believes they released it, and they have not.
    fields_set = payload.model_fields_set

    if "state" in fields_set:
        if payload.state is not None and payload.state not in DIVERGENCE_STATES:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f"state inválido: {payload.state}"
            )
        row.state = payload.state
    if "assigned_to_id" in fields_set:
        if payload.assigned_to_id is not None:
            # The column is an FK to usuarios.id; a nonexistent id used to
            # reach `db.commit()` unvalidated and raise IntegrityError --
            # a 500 that also left the session broken. Validated the same
            # way `state` is: reject before touching the row.
            assignee_exists = db.query(Usuario.id).filter(Usuario.id == payload.assigned_to_id).first() is not None
            if not assignee_exists:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=f"assigned_to_id inválido: no existe el usuario {payload.assigned_to_id}",
                )
        row.assigned_to_id = payload.assigned_to_id
    if "note" in fields_set:
        row.note = payload.note
    # `updated_at` is NOT set here: the column already has
    # `onupdate=func.now()`, and setting it by hand overwrites the
    # database's clock with the app server's -- two different clocks for
    # one column.

    db.commit()
    db.refresh(row)
    return DivergenceSummary.from_row(row)
