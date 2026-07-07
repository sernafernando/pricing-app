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
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import case, update
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.database import get_db
from app.core.sse import sse_publish_bg
from app.models.ml_bot_answer_example import MlBotAnswerExample
from app.models.ml_bot_config import MlBotConfig
from app.models.ml_bot_question import MlBotQuestion
from app.models.usuario import Usuario
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


class ExampleCreate(BaseModel):
    question_example: str = Field(min_length=1, max_length=2000)
    answer_example: str = Field(min_length=1, max_length=2000)
    category: Optional[str] = Field(None, max_length=40)
    active: bool = True
    orden: int = 0


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
    backend (ver `policy.py`)."""
    _check_permiso(db, current_user, "ml_bot.ver")
    bot_enabled = get_config(db, "bot_enabled", cast=bool, default=False)
    auto_publish_enabled = is_auto_publish_enabled(db)
    return StatusResponse(bot_enabled=bot_enabled, auto_publish_enabled=auto_publish_enabled)


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
