"""
Router: ML Questions Bot — panel API + permission enforcement (Slice F).

Design §9 endpoint list under `/api/ml-bot`. This slice implements the REST
surface only — no SSE emission yet (that's Slice G) and no frontend (Slice
H). Every endpoint enforces one of the four `ml_bot.*` permission codes
(R-1001) backend-side, independent of any frontend gating.

State-machine notes (design §2, carried from Judgment Day adjudications on
prior slices):
- `take-over` CAS-transitions only from pre-terminal states that a human can
  legitimately intervene on: `received`, `waiting`, `pending_morning`,
  `failed`. It never matches `publishing` — a row claimed by the background
  publisher for an in-flight POST can never be stolen mid-publish (CAS on
  the current status makes this a no-op 409, not a race). `received` was
  added in panel-v2 (see engram sdd/ml-questions-ai/panel-v2 requirement
  #1): with the bot OFF, rows sit in `received` forever with no panel
  action available — a human must be able to take over immediately. This
  is race-safe against `drafting_service._claim_for_drafting`, which only
  claims `status == "received"` in its own CAS: whichever of the two CAS
  UPDATEs commits first wins the row (moves it out of `received`), so the
  other one's `WHERE status IN (...)` / `WHERE status == 'received'`
  simply matches zero rows and reports its own well-defined "lost the
  race" outcome (409 for take-over, `skipped_claimed_elsewhere` for
  drafting) — never a double-claim.
- `publish-now` accepts `waiting`, `taken_over`, `pending_morning`, or
  `failed` as sources. It CAS-transitions the row into `waiting`
  (wait_until=now, so the semantics match "due immediately") in the SAME
  UPDATE, but the `attempts` reset is SOURCE-STATE-DEPENDENT (Judgment Day
  fix — blind-repost prevention). The decision is computed INSIDE the same
  atomic UPDATE via a SQL `CASE` on the row's actual status at UPDATE time
  (never pre-read in Python), so a concurrent transition between two
  in-tuple source states between the read and the write can never apply a
  stale reset value (Judgment Day round 2 fix — TOCTOU):
  - `waiting` / `taken_over` / `pending_morning` -> `attempts = 0` (fresh
    publish budget: these rows never had a real prior publish attempt on
    this cycle, exactly like `drafting_service._resolve_success` /
    `_resolve_fallback` do when a draft first reaches `waiting`).
  - `failed` -> `attempts = 1`. A `failed` row DID have real prior publish
    attempts (that's how it got here); `attempts` is the publisher's CLAIM
    counter (see `publisher_service._claim_for_publishing`), and the very
    first thing `_claim_for_publishing` does on the next claim is bump it
    again, landing at `attempts == 2`. That guarantees `_publish_one`'s
    verify-before-repost gate (`attempts > 1`) ALWAYS fires on a manual
    retry from `failed`, so the panel can never blindly re-POST a question
    ML may have already answered. This is the panel's "retry a failed row"
    action per design §2's `failed -> waiting` (manual retry) transition.
  It then delegates to `publisher_service.publish_question_now()` so the
  wait-loop and the manual path share identical ML-post + idempotency code
  (design §9).
- `hold` CAS-transitions `waiting`/`taken_over` -> `pending_morning`.
- `answer` (PUT) only edits `drafted_answer` on a `taken_over` row — a
  human must explicitly take over before editing, so the bot's own draft
  is never mutated out from under an in-flight bot pipeline stage.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import case, update
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.database import get_db
from app.core.sse import sse_publish_bg
from app.models.ml_bot_admin_pending_request import MlBotAdminPendingRequest
from app.models.ml_bot_answer_example import MlBotAnswerExample
from app.models.ml_bot_config import MlBotConfig
from app.models.mercadolibre_user_data import MercadoLibreUserData
from app.models.ml_bot_message import MlBotMessage
from app.models.ml_bot_question import MlBotQuestion
from app.models.usuario import Usuario
from app.services.afip_service import validar_cuit
from app.services.ml_api_client import MessageSendPermanentError, ml_client
from app.services.ml_messages import admin_pending_service
from app.services.ml_messages.admin_pending_templates import select_ack_template
from app.services.ml_questions import publisher_service
from app.services.ml_questions.policy import get_config, is_auto_publish_enabled
from app.services.permisos_service import PermisosService

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/ml-bot",
    tags=["ML Bot - Preguntas"],
)

# Source states each panel action may legally CAS out of (design §2 + the
# Judgment Day notes above).
_TAKE_OVER_SOURCE_STATES = ("received", "waiting", "pending_morning", "failed")
_HOLD_SOURCE_STATES = ("waiting", "taken_over")
_PUBLISH_NOW_SOURCE_STATES = ("waiting", "taken_over", "pending_morning", "failed")
# Sources whose retry-from-failed history means the next claim must verify
# before re-posting (Judgment Day fix — see module docstring). Every other
# source in `_PUBLISH_NOW_SOURCE_STATES` resets to a fresh `attempts = 0`.
_PUBLISH_NOW_FAILED_RETRY_ATTEMPTS = 1

# Messages (Phase A, PR2, sdd/ml-bot-messages-reply): source states each
# panel action may legally CAS out of on `MlBotMessage.bot_status` (design
# "Interfaces / Contracts" state machine). Mirrors the questions constants
# above but on the separate `bot_status` column.
_MESSAGE_TAKE_OVER_SOURCE_STATES = ("awaiting_human", "blocked_claim", "failed")
_MESSAGE_SEND_SOURCE_STATES = ("taken_over",)

# Admin-pending (Phase B, sdd/ml-bot-admin-pending, PR2): source states each
# transition may legally CAS out of on `MlBotAdminPendingRequest.status`
# (design "Interfaces / Contracts" state machine: new -> in_progress ->
# {done|cancelled}, in_progress -> new on release).
_ADMIN_PENDING_CLAIM_SOURCE_STATES = ("new",)
_ADMIN_PENDING_RELEASE_SOURCE_STATES = ("in_progress",)
_ADMIN_PENDING_DONE_SOURCE_STATES = ("new", "in_progress")
_ADMIN_PENDING_CANCEL_SOURCE_STATES = ("new", "in_progress")
# Enrich is NOT a state transition (it only writes reference `afip_*` fields,
# not `status`), so it uses no CAS. This is just the open-lifecycle guard: on a
# terminal (done/cancelled) row, re-fetching AFIP data changes nothing, so skip
# the external call and no-op. Not a 409 — an idempotent refresh must not error.
_ADMIN_PENDING_OPEN_STATES = ("new", "in_progress")


# =============================================================================
# SCHEMAS
# =============================================================================


class QuestionResponse(BaseModel):
    id: int
    ml_question_id: int
    item_id: str
    item_title: Optional[str] = None
    item_permalink: Optional[str] = None
    buyer_id: Optional[int] = None
    buyer_nickname: Optional[str] = None
    question_text: str
    question_date: datetime
    status: str
    drafted_answer: Optional[str] = None
    answer_source: Optional[str] = None
    confidence: Optional[float] = None
    category: Optional[str] = None
    llm_provider: Optional[str] = None
    injection_flag: bool
    fallback_used: bool
    wait_until: Optional[datetime] = None
    published_at: Optional[datetime] = None
    attempts: int
    last_error: Optional[str] = None
    taken_over_by: Optional[int] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class QuestionListResponse(BaseModel):
    questions: list[QuestionResponse]
    total: int


class BuyerHistoryItem(BaseModel):
    id: int
    question_date: datetime
    question_text: str
    status: str
    drafted_answer: Optional[str] = None
    published_at: Optional[datetime] = None
    item_title: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


class BuyerHistoryResponse(BaseModel):
    buyer_id: Optional[int] = None
    questions: list[BuyerHistoryItem]


class AnswerUpdate(BaseModel):
    drafted_answer: str = Field(min_length=1, max_length=2000)


class ConfigItemResponse(BaseModel):
    clave: str
    valor: str
    descripcion: Optional[str] = None
    tipo: str

    model_config = ConfigDict(from_attributes=True)


class ConfigListResponse(BaseModel):
    items: list[ConfigItemResponse]


class ConfigUpsert(BaseModel):
    valor: str = Field(min_length=1, max_length=4000)
    descripcion: Optional[str] = Field(None, max_length=1000)
    tipo: str = Field("string", max_length=50)


class ToggleRequest(BaseModel):
    enabled: bool


class ToggleResponse(BaseModel):
    bot_enabled: bool


class StatusResponse(BaseModel):
    bot_enabled: bool
    auto_publish_enabled: bool
    messages_send_enabled: bool


class ExampleResponse(BaseModel):
    id: int
    question_example: str
    answer_example: str
    category: Optional[str] = None
    active: bool
    orden: int

    model_config = ConfigDict(from_attributes=True)


class ExampleListResponse(BaseModel):
    examples: list[ExampleResponse]


class MessageResponse(BaseModel):
    id: int
    ml_message_id: str
    pack_id: Optional[str] = None
    buyer_id: Optional[int] = None
    buyer_nickname: Optional[str] = None
    seller_id: int
    subject: Optional[str] = None
    text: str
    status: str
    moderation_status: Optional[str] = None
    is_first_message: bool
    attachments: Optional[list] = None
    received_at: datetime
    read_at: Optional[datetime] = None
    kind: str
    taken_over_by: Optional[int] = None
    notes: Optional[str] = None
    ingested_at: Optional[datetime] = None
    bot_status: Optional[str] = None
    drafted_answer: Optional[str] = None
    intent_category: Optional[str] = None
    confidence: Optional[float] = None
    answer_source: Optional[str] = None
    llm_provider: Optional[str] = None
    attempts: int = 0
    last_error: Optional[str] = None
    drafted_at: Optional[datetime] = None
    bot_updated_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class MessageListResponse(BaseModel):
    messages: list[MessageResponse]
    total: int


class MessageAnswerUpdate(BaseModel):
    drafted_answer: str = Field(min_length=1, max_length=2000)


class MessageSendResponse(BaseModel):
    message: MessageResponse
    sent: bool


class ExampleCreate(BaseModel):
    question_example: str = Field(min_length=1, max_length=2000)
    answer_example: str = Field(min_length=1, max_length=2000)
    category: Optional[str] = Field(None, max_length=40)
    active: bool = True
    orden: int = 0


class AdminPendingResponse(BaseModel):
    id: int
    message_id: Optional[int] = None
    pack_id: Optional[str] = None
    buyer_id: Optional[int] = None
    request_type: str
    source: str
    raw_text: Optional[str] = None
    extracted_cuit: Optional[str] = None
    extracted_name: Optional[str] = None
    cuit_valid: Optional[bool] = None
    prefill_nickname: Optional[str] = None
    prefill_identification_type: Optional[str] = None
    prefill_identification_number: Optional[str] = None
    prefill_billing_doc_type: Optional[str] = None
    prefill_billing_doc_number: Optional[str] = None
    prefill_billing_first_name: Optional[str] = None
    prefill_billing_last_name: Optional[str] = None
    doc_mismatch: bool
    afip_status: Optional[str] = None
    afip_razon_social: Optional[str] = None
    afip_condicion_iva: Optional[str] = None
    afip_domicilio: Optional[str] = None
    afip_checked_at: Optional[datetime] = None
    status: str
    notes: Optional[str] = None
    cancel_reason: Optional[str] = None
    resolved_cuit: Optional[str] = None
    resolved_cuit_valid: Optional[bool] = None
    resolved_by: Optional[int] = None
    resolved_at: Optional[datetime] = None
    created_by: Optional[int] = None
    claimed_by: Optional[int] = None
    claimed_at: Optional[datetime] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class AdminPendingListResponse(BaseModel):
    requests: list[AdminPendingResponse]
    total: int


class AdminPendingDetailResponse(AdminPendingResponse):
    superseded_values: Optional[list[Any]] = None
    suggested_ack_template: str


class AdminPendingCreate(BaseModel):
    pack_id: Optional[str] = Field(None, max_length=32)
    buyer_id: Optional[int] = None
    request_type: str = Field("invoice_cuit_change", max_length=40)
    raw_text: Optional[str] = Field(None, max_length=4000)
    extracted_cuit: Optional[str] = Field(None, max_length=20)
    extracted_name: Optional[str] = Field(None, max_length=255)


class AdminPendingDoneRequest(BaseModel):
    resolved_cuit: str = Field(min_length=1, max_length=20)


class AdminPendingCancelRequest(BaseModel):
    reason: str = Field(min_length=1, max_length=2000)


# =============================================================================
# HELPERS
# =============================================================================


def _check_permiso(db: Session, user: Usuario, permiso: str) -> None:
    svc = PermisosService(db)
    if not svc.tiene_permiso(user, permiso):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=f"Sin permiso: {permiso}")


def _emit_reload_hint() -> None:
    """Fire the `ml_bot:questions` reload-hint SSE event (ADR-8). `sse_publish_bg`
    is documented never-raise, but this defensive guard ensures a future
    refactor there can never take down a panel mutation that already
    committed its DB write."""
    try:
        sse_publish_bg("ml_bot:questions", {"hint": "reload"})
    except Exception:  # noqa: BLE001 — SSE is best-effort, must never break a mutation.
        logger.warning("ml-bot router: sse_publish_bg raised while emitting reload hint", exc_info=True)


def _get_question_or_404(db: Session, question_id: int) -> MlBotQuestion:
    q = db.query(MlBotQuestion).filter(MlBotQuestion.id == question_id).first()
    if q is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Pregunta no encontrada")
    return q


def _cas_transition(
    db: Session,
    question_id: int,
    source_states: tuple[str, ...],
    **values: object,
) -> bool:
    """CAS UPDATE: only applies `values` if the row's current status is one
    of `source_states`. Returns True iff this call performed the
    transition (mirrors `publisher_service._claim_for_publishing`'s CAS
    shape) — a no-op means the row already moved (race lost, or illegal
    source state), which the caller reports as 409, not a silent success.
    """
    result = db.execute(
        update(MlBotQuestion)
        .where(MlBotQuestion.id == question_id, MlBotQuestion.status.in_(source_states))
        .values(**values)
    )
    db.commit()
    return result.rowcount == 1


def _get_message_or_404(db: Session, message_id: int) -> MlBotMessage:
    m = db.query(MlBotMessage).filter(MlBotMessage.id == message_id).first()
    if m is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Mensaje no encontrado")
    return m


def _cas_transition_message(
    db: Session,
    message_id: int,
    source_states: tuple[str, ...],
    **values: object,
) -> bool:
    """CAS UPDATE on `MlBotMessage.bot_status` — mirrors `_cas_transition`
    (questions) but on the messages table's separate lifecycle column."""
    result = db.execute(
        update(MlBotMessage)
        .where(MlBotMessage.id == message_id, MlBotMessage.bot_status.in_(source_states))
        .values(**values)
    )
    db.commit()
    return result.rowcount == 1


def _get_admin_pending_or_404(db: Session, request_id: int) -> MlBotAdminPendingRequest:
    row = db.query(MlBotAdminPendingRequest).filter(MlBotAdminPendingRequest.id == request_id).first()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Solicitud no encontrada")
    return row


def _cas_transition_pending(
    db: Session,
    request_id: int,
    source_states: tuple[str, ...],
    **values: object,
) -> bool:
    """CAS UPDATE on `MlBotAdminPendingRequest.status` — mirrors
    `_cas_transition_message` but on the admin-pending lane's own lifecycle
    column (design "Interfaces / Contracts")."""
    result = db.execute(
        update(MlBotAdminPendingRequest)
        .where(MlBotAdminPendingRequest.id == request_id, MlBotAdminPendingRequest.status.in_(source_states))
        .values(**values)
    )
    db.commit()
    return result.rowcount == 1


def _enrich_message_nicknames(db: Session, rows: list[MlBotMessage]) -> dict[int, MessageResponse]:
    """Batch-enriches `buyer_nickname` from `tb_mercadolibre_users_data`
    (design/instruction: ML's `from` on a message only carries `user_id`, the
    real nickname must come from this table, never from ML). Single batched
    query — no N+1 — keyed by `buyer_id`. Falls back to the row's own stored
    `buyer_nickname` (if any) and finally to `None` when neither is available;
    callers may further fall back to the raw `buyer_id` for display."""
    buyer_ids = {r.buyer_id for r in rows if r.buyer_id is not None}
    nickname_by_buyer_id: dict[int, str] = {}
    if buyer_ids:
        nickname_rows = (
            db.query(MercadoLibreUserData.mluser_id, MercadoLibreUserData.nickname)
            .filter(MercadoLibreUserData.mluser_id.in_(buyer_ids))
            .all()
        )
        nickname_by_buyer_id = {mluser_id: nickname for mluser_id, nickname in nickname_rows if nickname}

    responses: dict[int, MessageResponse] = {}
    for row in rows:
        resp = MessageResponse.model_validate(row)
        if row.buyer_id is not None and row.buyer_id in nickname_by_buyer_id:
            resp.buyer_nickname = nickname_by_buyer_id[row.buyer_id]
        responses[row.id] = resp
    return responses


# =============================================================================
# QUESTIONS ENDPOINTS
# =============================================================================


@router.get("/questions", response_model=QuestionListResponse)
def listar_preguntas(
    status_filter: Optional[str] = Query(None, alias="status"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> QuestionListResponse:
    """Lista preguntas del bot (paginado, filtrable por status). Requiere `ml_bot.ver`.

    Nota adjudicada (Judgment Day): `last_error` se expone intencionalmente
    acá — es visible para cualquiera con `ml_bot.ver` (personal interno),
    no es información sensible de cara al comprador.
    """
    _check_permiso(db, current_user, "ml_bot.ver")

    query = db.query(MlBotQuestion)
    if status_filter:
        query = query.filter(MlBotQuestion.status == status_filter)

    total = query.count()
    rows = query.order_by(MlBotQuestion.question_date.desc()).offset(offset).limit(limit).all()
    return QuestionListResponse(
        questions=[QuestionResponse.model_validate(r) for r in rows],
        total=total,
    )


@router.get("/messages", response_model=MessageListResponse)
def listar_mensajes(
    status_filter: Optional[str] = Query(None, alias="status"),
    buyer_id: Optional[int] = Query(None),
    pack_id: Optional[str] = Query(None),
    has_read: Optional[bool] = Query(None),
    include_moderated: bool = Query(False),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> MessageListResponse:
    """Lista mensajes postventa (paginado, filtrable). Requiere `ml_bot.messages.ver`.

    `pack_id=none` es un sentinel especial que filtra por `pack_id IS NULL`
    (mensajes sin pack asociado) en lugar de una igualdad exacta (design
    §Interfaces). `include_moderated=false` (default) oculta filas con
    `moderation_status` no nulo y distinto de `'clean'`; filas con
    `moderation_status IS NULL` siempre se muestran (unknown/pass, design
    decision #3).
    """
    _check_permiso(db, current_user, "ml_bot.messages.ver")

    query = db.query(MlBotMessage)
    if status_filter:
        query = query.filter(MlBotMessage.status == status_filter)
    if buyer_id is not None:
        query = query.filter(MlBotMessage.buyer_id == buyer_id)
    if pack_id is not None:
        if pack_id == "none":
            query = query.filter(MlBotMessage.pack_id.is_(None))
        else:
            query = query.filter(MlBotMessage.pack_id == pack_id)
    if has_read is not None:
        if has_read:
            query = query.filter(MlBotMessage.read_at.isnot(None))
        else:
            query = query.filter(MlBotMessage.read_at.is_(None))
    if not include_moderated:
        query = query.filter(
            ~(MlBotMessage.moderation_status.isnot(None) & (MlBotMessage.moderation_status != "clean"))
        )

    total = query.count()
    rows = query.order_by(MlBotMessage.received_at.desc()).offset(offset).limit(limit).all()
    enriched = _enrich_message_nicknames(db, rows)
    return MessageListResponse(
        messages=[enriched[r.id] for r in rows],
        total=total,
    )


@router.post("/messages/{message_id}/take-over", response_model=MessageResponse)
def tomar_mensaje(
    message_id: int,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> MessageResponse:
    """Un humano toma un mensaje postventa `awaiting_human`/`blocked_claim`/`failed`.
    Requiere `ml_bot.messages.responder` (Phase A, PR2).

    CAS desde `awaiting_human`/`blocked_claim`/`failed` -> `taken_over`; nunca
    puede robar una fila en `drafting` (el draft cycle la está procesando) ni
    una ya `taken_over`/`sent`/`superseded`/`pending` (mirrors
    `tomar_pregunta`'s race-safety notes). `failed` es recuperable (review
    finding Phase A FE): un envío con falla PERMANENTE (`MessageSendPermanentError`)
    deja la fila en `failed` y sin este take-over sería un callejón sin salida
    para el operador — mirrors `tomar_pregunta`, donde `failed` ya es fuente
    válida.
    """
    _check_permiso(db, current_user, "ml_bot.messages.responder")
    _get_message_or_404(db, message_id)

    ok = _cas_transition_message(
        db,
        message_id,
        _MESSAGE_TAKE_OVER_SOURCE_STATES,
        bot_status="taken_over",
        taken_over_by=current_user.id,
    )
    if not ok:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="El mensaje ya no está en un estado tomable",
        )

    _emit_reload_hint()
    row = _get_message_or_404(db, message_id)
    return _enrich_message_nicknames(db, [row])[row.id]


@router.put("/messages/{message_id}/answer", response_model=MessageResponse)
def editar_respuesta_mensaje(
    message_id: int,
    data: MessageAnswerUpdate,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> MessageResponse:
    """Edita el borrador de un mensaje ya tomado por un humano. Requiere
    `ml_bot.messages.responder` (Phase A, PR2).

    `answer_source` queda `human_edited` si ya existía un borrador del bot
    (el humano lo modificó) o `human_verbatim` si no había borrador previo
    (el humano lo escribió desde cero) — mirrors `editar_respuesta`'s
    human-content-exempt-from-denylist note: un operador con
    `ml_bot.messages.responder` es responsable de lo que escribe, sin
    validación de contenido adicional acá.
    """
    _check_permiso(db, current_user, "ml_bot.messages.responder")
    m = _get_message_or_404(db, message_id)

    if m.bot_status != "taken_over":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Solo se puede editar la respuesta de un mensaje tomado (taken_over)",
        )

    had_prior_draft = bool(m.drafted_answer)
    m.drafted_answer = data.drafted_answer
    m.answer_source = "human_edited" if had_prior_draft else "human_verbatim"
    db.commit()
    db.refresh(m)
    _emit_reload_hint()
    return _enrich_message_nicknames(db, [m])[m.id]


@router.post("/messages/{message_id}/send", response_model=MessageSendResponse)
async def enviar_mensaje(
    message_id: int,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> MessageSendResponse:
    """Envía la respuesta de un mensaje `taken_over` al comprador vía ML.
    Requiere `ml_bot.messages.responder` (Phase A, PR2).

    NUNCA auto-envía: esta es la ÚNICA vía de envío en Phase A, siempre
    disparada por una acción humana explícita. Fail-closed (409) mientras
    `messages_send_enabled` (default `False`) no esté prendido — el gate
    solo puede activarse después del live-verify user-owned (T0.1, design
    "send_message seam"). Éxito -> `bot_status='sent'` (`bot_updated_at`
    sirve de timestamp de envío, vía `onupdate`). Falla permanente (4xx no
    transitorio) -> `bot_status='failed'` + `last_error` poblado, nunca
    silenciosamente descartado. Falla transitoria (None) -> el mensaje
    queda en `taken_over` para reintentar manualmente.
    """
    _check_permiso(db, current_user, "ml_bot.messages.responder")
    m = _get_message_or_404(db, message_id)

    send_enabled = get_config(db, "messages_send_enabled", cast=bool, default=False)
    if not send_enabled:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="El envío de mensajes está deshabilitado (messages_send_enabled=False)",
        )

    if m.bot_status not in _MESSAGE_SEND_SOURCE_STATES:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="El mensaje no está en un estado enviable (debe estar taken_over)",
        )
    if not m.drafted_answer:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No hay respuesta cargada para enviar")
    if m.pack_id is None or m.buyer_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="El mensaje no tiene pack_id/buyer_id para enviar"
        )

    pack_id = m.pack_id
    buyer_id = m.buyer_id
    seller_id = m.seller_id
    text_to_send = m.drafted_answer

    try:
        result = await ml_client.send_message(pack_id, buyer_id, text_to_send, seller_id=seller_id)
    except MessageSendPermanentError as exc:
        _cas_transition_message(
            db,
            message_id,
            _MESSAGE_SEND_SOURCE_STATES,
            bot_status="failed",
            last_error=str(exc)[:2000],
        )
        _emit_reload_hint()
        row = _get_message_or_404(db, message_id)
        return MessageSendResponse(message=_enrich_message_nicknames(db, [row])[row.id], sent=False)

    if result is None:
        # Transient failure — stays `taken_over` for a manual retry (never
        # auto-retried, this is a human-send-only endpoint).
        row = _get_message_or_404(db, message_id)
        return MessageSendResponse(message=_enrich_message_nicknames(db, [row])[row.id], sent=False)

    _cas_transition_message(db, message_id, _MESSAGE_SEND_SOURCE_STATES, bot_status="sent")
    _emit_reload_hint()
    row = _get_message_or_404(db, message_id)
    return MessageSendResponse(message=_enrich_message_nicknames(db, [row])[row.id], sent=True)


@router.post("/questions/{question_id}/take-over", response_model=QuestionResponse)
def tomar_pregunta(
    question_id: int,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> QuestionResponse:
    """Un humano toma una pregunta pendiente/held/failed. Requiere `ml_bot.responder`.

    CAS desde `received`/`waiting`/`pending_morning`/`failed` -> `taken_over`;
    nunca puede robar una fila que el publisher tiene en `publishing` (fuera
    del conjunto de estados fuente), ni una que `drafting_service` ya haya
    empezado a procesar (fuera de `received`).
    """
    _check_permiso(db, current_user, "ml_bot.responder")
    _get_question_or_404(db, question_id)

    ok = _cas_transition(
        db,
        question_id,
        _TAKE_OVER_SOURCE_STATES,
        status="taken_over",
        taken_over_by=current_user.id,
        updated_at=datetime.now(timezone.utc),
    )
    if not ok:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="La pregunta ya no está en un estado tomable (puede estar publicándose o ya resuelta)",
        )

    _emit_reload_hint()
    return QuestionResponse.model_validate(_get_question_or_404(db, question_id))


@router.put("/questions/{question_id}/answer", response_model=QuestionResponse)
def editar_respuesta(
    question_id: int,
    data: AnswerUpdate,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> QuestionResponse:
    """Edita el borrador de una pregunta ya tomada por un humano. Requiere `ml_bot.responder`.

    Nota adjudicada (Judgment Day): el contenido escrito acá por un humano
    queda intencionalmente EXENTO de la denylist del bot (R-502 aplica solo
    a contenido generado por el bot). Un operador con `ml_bot.responder` es
    responsable de lo que escribe manualmente, igual que si respondiera
    directamente en ML — no hay validación de contenido adicional sobre
    `drafted_answer` en este endpoint.
    """
    _check_permiso(db, current_user, "ml_bot.responder")
    q = _get_question_or_404(db, question_id)

    if q.status != "taken_over":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Solo se puede editar la respuesta de una pregunta tomada (taken_over)",
        )

    q.drafted_answer = data.drafted_answer
    q.answer_source = "human"
    db.commit()
    db.refresh(q)
    _emit_reload_hint()
    return QuestionResponse.model_validate(q)


@router.post("/questions/{question_id}/publish-now", response_model=QuestionResponse)
async def publicar_ahora(
    question_id: int,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> QuestionResponse:
    """Publica inmediatamente (bypass wait-window). Requiere `ml_bot.responder`.

    CAS desde `waiting`/`taken_over`/`pending_morning`/`failed` -> `waiting`
    con `wait_until=now`. El reset de `attempts` depende del estado de
    origen y se calcula ATÓMICAMENTE dentro del mismo UPDATE vía SQL `CASE`
    sobre el status real de la fila (ver docstring del módulo — evita TOCTOU
    entre la lectura previa y el UPDATE): `failed` -> `attempts=1` (esta fila
    tuvo intentos de publicación reales; el próximo claim del publisher lo
    sube a 2, lo que fuerza el gate de verificación-antes-de-repostear de
    `_publish_one` y evita un repost ciego de una pregunta que ML ya pudo
    haber respondido). Cualquier otro origen -> `attempts=0` (fresh publish
    budget genuino, nunca publicado). Esto es también la acción del panel
    "reintentar una fila fallida" según la transición manual `failed ->
    waiting` del §2 del diseño. Luego delega a
    `publisher_service.publish_question_now()` para reusar exactamente el
    mismo pipeline de POST + idempotencia que el loop de background.
    """
    _check_permiso(db, current_user, "ml_bot.responder")
    q = _get_question_or_404(db, question_id)

    if q.status not in _PUBLISH_NOW_SOURCE_STATES:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="La pregunta no está en un estado publicable ahora",
        )
    if not q.drafted_answer:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No hay respuesta cargada para publicar")

    now = datetime.now(timezone.utc)
    ok = _cas_transition(
        db,
        question_id,
        _PUBLISH_NOW_SOURCE_STATES,
        status="waiting",
        wait_until=now,
        attempts=case(
            (MlBotQuestion.status == "failed", _PUBLISH_NOW_FAILED_RETRY_ATTEMPTS),
            else_=0,
        ),
        updated_at=now,
    )
    if not ok:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="La pregunta cambió de estado antes de poder publicarla",
        )

    await publisher_service.publish_question_now(question_id)

    _emit_reload_hint()
    return QuestionResponse.model_validate(_get_question_or_404(db, question_id))


@router.post("/questions/{question_id}/hold", response_model=QuestionResponse)
def retener_pregunta(
    question_id: int,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> QuestionResponse:
    """Retiene la pregunta para revisión humana de la mañana. Requiere `ml_bot.responder`."""
    _check_permiso(db, current_user, "ml_bot.responder")
    _get_question_or_404(db, question_id)

    ok = _cas_transition(
        db,
        question_id,
        _HOLD_SOURCE_STATES,
        status="pending_morning",
        updated_at=datetime.now(timezone.utc),
    )
    if not ok:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="La pregunta ya no está en un estado retenible",
        )

    _emit_reload_hint()
    return QuestionResponse.model_validate(_get_question_or_404(db, question_id))


@router.get("/questions/{question_id}/buyer-history", response_model=BuyerHistoryResponse)
def historial_comprador(
    question_id: int,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> BuyerHistoryResponse:
    """Historial de OTRAS preguntas del mismo comprador (panel-v2 requisito
    #3) — hasta 20 filas de `ml_bot_questions` con el mismo `buyer_id`, más
    recientes primero, EXCLUYENDO la pregunta actual por id (no por fecha:
    si el comprador tiene una pregunta más nueva que la consultada, también
    aparece — da todo el contexto disponible del comprador, no solo el
    pasado). Requiere `ml_bot.ver`.

    404 si la pregunta no existe; lista vacía si `buyer_id` es null (no hay
    forma de correlacionar comprador).
    """
    _check_permiso(db, current_user, "ml_bot.ver")
    question = _get_question_or_404(db, question_id)

    if question.buyer_id is None:
        return BuyerHistoryResponse(buyer_id=None, questions=[])

    rows = (
        db.query(MlBotQuestion)
        .filter(
            MlBotQuestion.buyer_id == question.buyer_id,
            MlBotQuestion.id != question_id,
        )
        .order_by(MlBotQuestion.question_date.desc())
        .limit(20)
        .all()
    )
    return BuyerHistoryResponse(
        buyer_id=question.buyer_id,
        questions=[BuyerHistoryItem.model_validate(r) for r in rows],
    )


@router.get("/status", response_model=StatusResponse)
def obtener_status(
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> StatusResponse:
    """Estado del bot visible para CUALQUIER usuario con `ml_bot.ver` (el
    permiso más bajo de los cuatro `ml_bot.*`) — `bot_enabled` y
    `auto_publish_enabled` son booleanos no sensibles (a diferencia de
    `GET /config`, que expone la configuración de negocio completa y sigue
    reservado a `ml_bot.config`). Esto cierra dos hallazgos de Judgment Day:
    el badge de modo supervisado (y el de bot on/off) eran invisibles para
    operadores con solo `ml_bot.ver`/`ml_bot.responder`, y el frontend
    parseaba `valor === 'true'` en vez de reusar el `_cast_bool` real del
    backend (ver `policy.py`).

    `messages_send_enabled` se agrega por el mismo motivo (Phase A PR3
    review): el gate de envío de mensajes (default `False`, ver
    `enviar_mensaje`) era invisible para el frontend, que
    renderizaba "Enviar" habilitado y disparaba un 409 en producción por
    default. Se lee con el mismo accessor fail-safe (`get_config` con
    `default=False`) que usa el propio gate."""
    _check_permiso(db, current_user, "ml_bot.ver")
    bot_enabled = get_config(db, "bot_enabled", cast=bool, default=False)
    auto_publish_enabled = is_auto_publish_enabled(db)
    messages_send_enabled = get_config(db, "messages_send_enabled", cast=bool, default=False)
    return StatusResponse(
        bot_enabled=bot_enabled,
        auto_publish_enabled=auto_publish_enabled,
        messages_send_enabled=messages_send_enabled,
    )


# =============================================================================
# CONFIG ENDPOINTS
# =============================================================================


@router.get("/config", response_model=ConfigListResponse)
def listar_config(
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> ConfigListResponse:
    """Lista las variables de configuración del bot. Requiere `ml_bot.config`."""
    _check_permiso(db, current_user, "ml_bot.config")
    rows = db.query(MlBotConfig).order_by(MlBotConfig.clave).all()
    return ConfigListResponse(items=[ConfigItemResponse.model_validate(r) for r in rows])


@router.put("/config/{clave}", response_model=ConfigItemResponse)
def actualizar_config(
    clave: str,
    data: ConfigUpsert,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> ConfigItemResponse:
    """Crea o actualiza una variable de configuración (ABM libre por clave,
    ADR-4: el panel edita conocimiento de negocio sin redeploy). Requiere
    `ml_bot.config`.

    Validación superficial solamente (no vacío, longitud acotada) — los
    lectores (`policy.get_config` y afines) YA son fail-safe ante valores
    malformados (timezone/hora/JSON inválidos degradan a un default
    seguro sin crashear), así que esta escritura no necesita duplicar esa
    validación semántica por clave; solo evita basura evidente.
    """
    _check_permiso(db, current_user, "ml_bot.config")

    row = db.query(MlBotConfig).filter(MlBotConfig.clave == clave).first()
    if row is None:
        row = MlBotConfig(clave=clave, valor=data.valor, descripcion=data.descripcion, tipo=data.tipo)
        db.add(row)
    else:
        row.valor = data.valor
        row.descripcion = data.descripcion
        row.tipo = data.tipo

    db.commit()
    db.refresh(row)
    _emit_reload_hint()
    return ConfigItemResponse.model_validate(row)


@router.post("/toggle", response_model=ToggleResponse)
def alternar_bot(
    data: ToggleRequest,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> ToggleResponse:
    """Prende/apaga el bot globalmente (kill switch, R-803). Requiere `ml_bot.on_off`."""
    _check_permiso(db, current_user, "ml_bot.on_off")

    row = db.query(MlBotConfig).filter(MlBotConfig.clave == "bot_enabled").first()
    valor = "true" if data.enabled else "false"
    if row is None:
        row = MlBotConfig(clave="bot_enabled", valor=valor, tipo="bool")
        db.add(row)
    else:
        row.valor = valor
        row.tipo = "bool"

    db.commit()
    _emit_reload_hint()
    return ToggleResponse(bot_enabled=data.enabled)


# =============================================================================
# EXAMPLES (few-shot) ENDPOINTS
# =============================================================================


@router.get("/examples", response_model=ExampleListResponse)
def listar_ejemplos(
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> ExampleListResponse:
    """Lista los ejemplos few-shot de tono. Requiere `ml_bot.config`."""
    _check_permiso(db, current_user, "ml_bot.config")
    rows = db.query(MlBotAnswerExample).order_by(MlBotAnswerExample.orden, MlBotAnswerExample.id).all()
    return ExampleListResponse(examples=[ExampleResponse.model_validate(r) for r in rows])


@router.post("/examples", response_model=ExampleResponse, status_code=status.HTTP_201_CREATED)
def crear_ejemplo(
    data: ExampleCreate,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> ExampleResponse:
    """Crea un ejemplo few-shot de tono. Requiere `ml_bot.config`."""
    _check_permiso(db, current_user, "ml_bot.config")
    example = MlBotAnswerExample(**data.model_dump())
    db.add(example)
    db.commit()
    db.refresh(example)
    return ExampleResponse.model_validate(example)


@router.delete("/examples/{example_id}", status_code=status.HTTP_204_NO_CONTENT)
def borrar_ejemplo(
    example_id: int,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> None:
    """Elimina un ejemplo few-shot. Requiere `ml_bot.config`."""
    _check_permiso(db, current_user, "ml_bot.config")
    example = db.query(MlBotAnswerExample).filter(MlBotAnswerExample.id == example_id).first()
    if example is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ejemplo no encontrado")
    db.delete(example)
    db.commit()


# =============================================================================
# ADMIN-PENDING ENDPOINTS (Phase B, sdd/ml-bot-admin-pending, PR2)
# =============================================================================


@router.get("/admin-pending", response_model=AdminPendingListResponse)
def listar_pendientes(
    status_filter: Optional[str] = Query(None, alias="status"),
    source: Optional[str] = Query(None),
    pack_id: Optional[str] = Query(None),
    buyer_id: Optional[int] = Query(None),
    cuit_valid: Optional[bool] = Query(None),
    doc_mismatch: Optional[bool] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> AdminPendingListResponse:
    """Lista solicitudes pendientes de la lane derive-to-admin (paginado,
    filtrable). Requiere `ml_bot.admin_pending.ver`."""
    _check_permiso(db, current_user, "ml_bot.admin_pending.ver")

    query = db.query(MlBotAdminPendingRequest)
    if status_filter:
        query = query.filter(MlBotAdminPendingRequest.status == status_filter)
    if source:
        query = query.filter(MlBotAdminPendingRequest.source == source)
    if pack_id:
        query = query.filter(MlBotAdminPendingRequest.pack_id == pack_id)
    if buyer_id is not None:
        query = query.filter(MlBotAdminPendingRequest.buyer_id == buyer_id)
    if cuit_valid is not None:
        query = query.filter(MlBotAdminPendingRequest.cuit_valid == cuit_valid)
    if doc_mismatch is not None:
        query = query.filter(MlBotAdminPendingRequest.doc_mismatch == doc_mismatch)

    total = query.count()
    rows = query.order_by(MlBotAdminPendingRequest.created_at.desc()).offset(offset).limit(limit).all()
    return AdminPendingListResponse(
        requests=[AdminPendingResponse.model_validate(r) for r in rows],
        total=total,
    )


@router.get("/admin-pending/{request_id}", response_model=AdminPendingDetailResponse)
def detalle_pendiente(
    request_id: int,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> AdminPendingDetailResponse:
    """Detalle de una solicitud pendiente, incluyendo `superseded_values`
    (design decision #4) y `suggested_ack_template` computado desde los
    flags de la fila (design decision #7: single source of truth, la FE
    nunca decide el template). Requiere `ml_bot.admin_pending.ver`."""
    _check_permiso(db, current_user, "ml_bot.admin_pending.ver")
    row = _get_admin_pending_or_404(db, request_id)

    template = select_ack_template(cuit_valid=row.cuit_valid, doc_mismatch=row.doc_mismatch)
    base = AdminPendingResponse.model_validate(row).model_dump()
    return AdminPendingDetailResponse(**base, superseded_values=row.superseded_values, suggested_ack_template=template)


@router.post("/admin-pending", response_model=AdminPendingResponse, status_code=status.HTTP_201_CREATED)
def crear_pendiente_manual(
    data: AdminPendingCreate,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> AdminPendingResponse:
    """Crea una solicitud pendiente manualmente (design "manual creation") —
    un operador que detecta un pedido de cambio de factura fuera del flujo
    de derive automático puede cargarla a mano. `source='manual'`,
    `created_by=current_user.id`, `status='new'`. Requiere
    `ml_bot.admin_pending.gestionar`."""
    _check_permiso(db, current_user, "ml_bot.admin_pending.gestionar")

    row = MlBotAdminPendingRequest(
        pack_id=data.pack_id,
        buyer_id=data.buyer_id,
        request_type=data.request_type,
        raw_text=data.raw_text,
        extracted_cuit=data.extracted_cuit,
        extracted_name=data.extracted_name,
        source="manual",
        status="new",
        created_by=current_user.id,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    _emit_reload_hint()
    return AdminPendingResponse.model_validate(row)


@router.post("/admin-pending/{request_id}/claim", response_model=AdminPendingResponse)
def reclamar_pendiente(
    request_id: int,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> AdminPendingResponse:
    """Un humano toma una solicitud `new`. CAS `new` -> `in_progress`,
    estampa `claimed_by`/`claimed_at`. Requiere `ml_bot.admin_pending.gestionar`."""
    _check_permiso(db, current_user, "ml_bot.admin_pending.gestionar")
    _get_admin_pending_or_404(db, request_id)

    ok = _cas_transition_pending(
        db,
        request_id,
        _ADMIN_PENDING_CLAIM_SOURCE_STATES,
        status="in_progress",
        claimed_by=current_user.id,
        claimed_at=datetime.now(timezone.utc),
    )
    if not ok:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="La solicitud ya no está en un estado reclamable",
        )

    _emit_reload_hint()
    return AdminPendingResponse.model_validate(_get_admin_pending_or_404(db, request_id))


@router.post("/admin-pending/{request_id}/release", response_model=AdminPendingResponse)
def liberar_pendiente(
    request_id: int,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> AdminPendingResponse:
    """Libera una solicitud `in_progress` de vuelta a `new`, limpiando el
    claim. Requiere `ml_bot.admin_pending.gestionar`."""
    _check_permiso(db, current_user, "ml_bot.admin_pending.gestionar")
    _get_admin_pending_or_404(db, request_id)

    ok = _cas_transition_pending(
        db,
        request_id,
        _ADMIN_PENDING_RELEASE_SOURCE_STATES,
        status="new",
        claimed_by=None,
        claimed_at=None,
    )
    if not ok:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="La solicitud no está en un estado liberable",
        )

    _emit_reload_hint()
    return AdminPendingResponse.model_validate(_get_admin_pending_or_404(db, request_id))


@router.post("/admin-pending/{request_id}/done", response_model=AdminPendingResponse)
def resolver_pendiente(
    request_id: int,
    data: AdminPendingDoneRequest,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> AdminPendingResponse:
    """Marca una solicitud como resuelta — transición de auditoría fiscal
    (design decision #5): REQUIERE `resolved_cuit` no vacío (enforced por
    `AdminPendingDoneRequest.min_length=1`) y estampa `resolved_cuit`/
    `resolved_cuit_valid`/`resolved_by`/`resolved_at` en la MISMA transición
    CAS — el CUIT finalmente facturado puede diferir del extraído
    originalmente, nunca es un simple cambio de estado. `resolved_cuit_valid`
    viene de `validar_cuit()` (nunca se autocorrige el CUIT, design "PII /
    Threat"). Requiere `ml_bot.admin_pending.gestionar`."""
    _check_permiso(db, current_user, "ml_bot.admin_pending.gestionar")
    _get_admin_pending_or_404(db, request_id)

    clean_cuit = re.sub(r"[^0-9]", "", data.resolved_cuit)
    resolved_cuit_valid = validar_cuit(clean_cuit) if clean_cuit else False

    ok = _cas_transition_pending(
        db,
        request_id,
        _ADMIN_PENDING_DONE_SOURCE_STATES,
        status="done",
        resolved_cuit=data.resolved_cuit,
        resolved_cuit_valid=resolved_cuit_valid,
        resolved_by=current_user.id,
        resolved_at=datetime.now(timezone.utc),
    )
    if not ok:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="La solicitud ya no está en un estado resoluble",
        )

    _emit_reload_hint()
    return AdminPendingResponse.model_validate(_get_admin_pending_or_404(db, request_id))


@router.post("/admin-pending/{request_id}/cancel", response_model=AdminPendingResponse)
def cancelar_pendiente(
    request_id: int,
    data: AdminPendingCancelRequest,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> AdminPendingResponse:
    """Cancela una solicitud `new`/`in_progress`, estampando `cancel_reason`.
    Requiere `ml_bot.admin_pending.gestionar`."""
    _check_permiso(db, current_user, "ml_bot.admin_pending.gestionar")
    _get_admin_pending_or_404(db, request_id)

    ok = _cas_transition_pending(
        db,
        request_id,
        _ADMIN_PENDING_CANCEL_SOURCE_STATES,
        status="cancelled",
        cancel_reason=data.reason,
    )
    if not ok:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="La solicitud ya no está en un estado cancelable",
        )

    _emit_reload_hint()
    return AdminPendingResponse.model_validate(_get_admin_pending_or_404(db, request_id))


@router.post("/admin-pending/{request_id}/enrich-afip", response_model=AdminPendingResponse)
async def reenriquecer_afip(
    request_id: int,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
) -> AdminPendingResponse:
    """Re-corre el enriquecimiento AFIP best-effort (mismo seam que
    `admin_pending_service._enrich_afip`, design decision #6) sobre el CUIT
    resuelto si ya hay uno, o el extraído en su defecto. Nunca falla: un
    resultado `unavailable`/`not_found`/`skipped` se persiste igual que en el
    derive original. Requiere `ml_bot.admin_pending.gestionar`."""
    _check_permiso(db, current_user, "ml_bot.admin_pending.gestionar")
    row = _get_admin_pending_or_404(db, request_id)

    # Terminal rows (done/cancelled) are a clean no-op: skip the AFIP call and
    # return current state unchanged (see `_ADMIN_PENDING_OPEN_STATES`).
    if row.status not in _ADMIN_PENDING_OPEN_STATES:
        return AdminPendingResponse.model_validate(row)

    cuit = row.resolved_cuit or row.extracted_cuit
    afip_status_value, afip_fields = await admin_pending_service._enrich_afip(cuit)

    row.afip_status = afip_status_value
    row.afip_checked_at = datetime.now(timezone.utc) if afip_status_value != "skipped" else row.afip_checked_at
    for key, value in afip_fields.items():
        setattr(row, key, value)

    db.commit()
    db.refresh(row)
    _emit_reload_hint()
    return AdminPendingResponse.model_validate(row)
