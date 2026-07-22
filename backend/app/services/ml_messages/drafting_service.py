"""
Drafting + classification orchestration for the ML postventa messages bot
(Phase A, sdd/ml-bot-messages-reply, PR1).

Mirrors `app.services.ml_questions.drafting_service`'s pipeline shape (CAS
claim -> manipulation check -> context+LLM outside any DB session -> parse ->
classify -> terminal write) but is THREAD-scoped and NEVER auto-sends
(design "Key Decisions" / "State machine").

Draft unit = anchor (design "Draft unit = anchor"): `bot_status` is non-NULL
only on the latest still-unresolved buyer message per `pack_id`. Earlier
messages in the same pack stay `bot_status IS NULL` forever — the aggregated
buyer turn + conversation history are reconstructed on every tick from a
LIVE pack-thread fetch (`ml_client.get_pack_thread`), never from local rows,
because ingestion drops outgoing seller messages (they are never persisted).

`bot_status` state machine (see `app.models.ml_bot_message` docstring):
    (NULL|pending) -> drafting -> {awaiting_human|blocked_claim|failed}
    drafting -> pending                      (bounded retry / stale reclaim)
    awaiting_human -> superseded             (a newer buyer message arrives)
    {awaiting_human|blocked_claim} -> taken_over -> {sent|failed}   (PR2/human)
    failed -> pending                        (manual retry, human/PR2)

Session discipline (ADR-5, mirrors `ml_questions.drafting_service`): every DB
read/write is its own short `get_background_db()` block. The live pack-thread
fetch and the LLM call NEVER happen while a DB session from this module is
open.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import or_, func, update

from app.core.database import get_background_db
from app.models.ml_bot_message import MlBotMessage
from app.services.ml_api_client import ml_client
from app.services.ml_messages import context_builder
from app.services.ml_questions import policy
from app.services.ml_questions.llm_provider import LlmProvider, LlmProviderError, parse_llm_output
from app.services.ml_questions.provider_rotation import RotatingProvider

logger = logging.getLogger(__name__)

_BATCH_LIMIT = 20
_MAX_ATTEMPTS = 3
_DRAFTING_STALE_MINUTES = 15
_DEFAULT_SETTLE_MINUTES = 5
_DEFAULT_ANSWER_MAX_CHARS = 400

# design "Categories per spec": claims are hard-blocked from drafting.
_CLAIM_CATEGORIES = frozenset({"claim"})

_SAFE_FALLBACK_TEXT = (
    "¡Hola! Gracias por tu mensaje, ya lo derivamos a nuestro equipo para que te respondan a la brevedad."
)

# `bot_status` values considered "not yet claimed" — a fresh anchor or a
# bounded-retry/manual-retry row waiting to be picked up again.
_CLAIMABLE_STATUSES = (None, "pending")


def _resolve_settle_minutes(db: Any) -> int:
    """Fail-safe settle/debounce window (design "Stateless settle window"),
    mirrors `policy.resolve_wait_minutes`'s fail-safe int convention."""
    raw = policy.get_config(db, "messages_settle_minutes", cast=str, default=str(_DEFAULT_SETTLE_MINUTES))
    try:
        value = int(raw)
    except (ValueError, TypeError):
        logger.warning(
            "ml-bot messages drafting: malformed messages_settle_minutes=%r; falling back to default=%d",
            raw,
            _DEFAULT_SETTLE_MINUTES,
        )
        return _DEFAULT_SETTLE_MINUTES
    if value < 0:
        return _DEFAULT_SETTLE_MINUTES
    return value


def is_settled(now: datetime, last_received_at: datetime, settle_minutes: int) -> bool:
    """R-2: an anchor is settled when no new buyer message has arrived within
    `settle_minutes` of `now`. Timezone-naive `last_received_at` is treated
    as UTC (matches `_parse_message_date`'s ingestion convention)."""
    if last_received_at.tzinfo is None:
        last_received_at = last_received_at.replace(tzinfo=timezone.utc)
    return (now - last_received_at) >= timedelta(minutes=settle_minutes)


def _build_default_provider() -> LlmProvider:
    return RotatingProvider()


def _resolve_provider_label(provider: LlmProvider) -> Optional[str]:
    last_used = getattr(provider, "last_used_provider", None)
    if last_used:
        return last_used
    name = getattr(provider, "name", None)
    return str(name) if name else None


def _supersede_stale_awaiting_human() -> int:
    """T2.5/T2.6: a NEW buyer message (bot_status NULL/pending) arriving in a
    pack that already has an `awaiting_human` anchor means that anchor is
    stale — re-open aggregation by superseding it, so the draft cycle picks
    the fresh anchor on this same tick instead of leaving two live anchors
    for the same pack."""
    with get_background_db() as db:
        reopened_subq = (
            db.query(MlBotMessage.pack_id, func.max(MlBotMessage.received_at).label("max_received_at"))
            .filter(or_(MlBotMessage.bot_status.is_(None), MlBotMessage.bot_status == "pending"))
            .group_by(MlBotMessage.pack_id)
            .subquery()
        )
        stale_rows = (
            db.query(MlBotMessage)
            .join(reopened_subq, MlBotMessage.pack_id == reopened_subq.c.pack_id)
            .filter(
                MlBotMessage.bot_status == "awaiting_human",
                MlBotMessage.received_at < reopened_subq.c.max_received_at,
            )
            .all()
        )
        for row in stale_rows:
            row.bot_status = "superseded"
        return len(stale_rows)


def _reclaim_stale_drafting(now: datetime) -> int:
    """Same convention as `ml_questions.drafting_service._reclaim_stale_drafting_claims`
    — a row stuck in `drafting` past `_DRAFTING_STALE_MINUTES` (SIGKILL/crash
    between claim and terminal write) is CAS-reverted to `pending` so a later
    tick retries it, instead of staying stuck forever."""
    threshold = now - timedelta(minutes=_DRAFTING_STALE_MINUTES)
    with get_background_db() as db:
        result = db.execute(
            update(MlBotMessage)
            .where(MlBotMessage.bot_status == "drafting", MlBotMessage.bot_updated_at < threshold)
            .values(bot_status="pending")
        )
        reclaimed = result.rowcount
    if reclaimed:
        logger.warning(
            "ml-bot messages drafting: reclaimed %d stale 'drafting' row(s) older than %d minutes",
            reclaimed,
            _DRAFTING_STALE_MINUTES,
        )
    return reclaimed


def _fetch_settled_anchor_ids(now: datetime) -> List[int]:
    """T2.1/T2.3: candidate anchors = per-pack latest still-unclaimed
    (`bot_status` NULL or `pending`) row, filtered to those whose settle
    window has elapsed."""
    with get_background_db() as db:
        settle_minutes = _resolve_settle_minutes(db)
        candidates_subq = (
            db.query(MlBotMessage.pack_id, func.max(MlBotMessage.received_at).label("max_received_at"))
            .filter(or_(MlBotMessage.bot_status.is_(None), MlBotMessage.bot_status == "pending"))
            .filter(MlBotMessage.pack_id.isnot(None))
            .group_by(MlBotMessage.pack_id)
            .subquery()
        )
        anchors = (
            db.query(MlBotMessage)
            .join(
                candidates_subq,
                (MlBotMessage.pack_id == candidates_subq.c.pack_id)
                & (MlBotMessage.received_at == candidates_subq.c.max_received_at),
            )
            .filter(or_(MlBotMessage.bot_status.is_(None), MlBotMessage.bot_status == "pending"))
            .order_by(MlBotMessage.received_at.asc())
            .limit(_BATCH_LIMIT)
            .all()
        )
        return [row.id for row in anchors if is_settled(now, row.received_at, settle_minutes)]


def _claim_for_drafting(anchor_id: int) -> bool:
    """CAS transition `(NULL|pending) -> drafting`. Returns True only if THIS
    call won the claim."""
    with get_background_db() as db:
        result = db.execute(
            update(MlBotMessage)
            .where(
                MlBotMessage.id == anchor_id,
                or_(MlBotMessage.bot_status.is_(None), MlBotMessage.bot_status == "pending"),
            )
            .values(bot_status="drafting")
        )
        return result.rowcount == 1


def _load_anchor(anchor_id: int) -> Optional[Dict[str, Any]]:
    with get_background_db() as db:
        row = db.query(MlBotMessage).filter(MlBotMessage.id == anchor_id).first()
        if row is None:
            return None
        return {
            "id": row.id,
            "pack_id": row.pack_id,
            "buyer_id": row.buyer_id,
            "seller_id": row.seller_id,
            "text": row.text,
            "received_at": row.received_at,
            "moderation_status": row.moderation_status,
        }


def _split_thread(thread: List[Dict[str, Any]], seller_id: int) -> tuple[List[str], List[Dict[str, Any]], bool]:
    """Split the live pack thread into (buyer_burst_texts, history_turns,
    seller_already_replied). `seller_already_replied` is True when the LAST
    message in the thread is seller-authored (a human already answered
    directly in ML — this pack must not be drafted)."""
    history_turns: List[Dict[str, Any]] = []
    for msg in thread:
        from_user = msg.get("from") or {}
        is_seller = from_user.get("user_id") == seller_id
        text = msg.get("text")
        if isinstance(text, dict):
            text = text.get("plain") or ""
        history_turns.append({"is_seller": is_seller, "text": text or ""})

    seller_already_replied = bool(history_turns) and history_turns[-1]["is_seller"]

    # Buyer burst = every buyer message AFTER the last seller message (or all
    # buyer messages if the seller never replied in this thread at all).
    last_seller_index = -1
    for index, turn in enumerate(history_turns):
        if turn["is_seller"]:
            last_seller_index = index
    burst_texts = [
        turn["text"] for turn in history_turns[last_seller_index + 1 :] if not turn["is_seller"] and turn["text"]
    ]
    return burst_texts, history_turns, seller_already_replied


def _mark_superseded(anchor_id: int) -> None:
    with get_background_db() as db:
        row = db.query(MlBotMessage).filter(MlBotMessage.id == anchor_id, MlBotMessage.bot_status == "drafting").first()
        if row is None:
            return
        row.bot_status = "superseded"


def _mark_blocked_claim(anchor_id: int) -> None:
    with get_background_db() as db:
        row = db.query(MlBotMessage).filter(MlBotMessage.id == anchor_id, MlBotMessage.bot_status == "drafting").first()
        if row is None:
            return
        row.bot_status = "blocked_claim"
        row.drafted_answer = None
        row.answer_source = None
        row.attempts = 0


def _mark_awaiting_human(
    anchor_id: int,
    *,
    answer: str,
    category: str,
    confidence: Optional[float],
    answer_source: str,
    provider_label: Optional[str],
) -> None:
    with get_background_db() as db:
        row = db.query(MlBotMessage).filter(MlBotMessage.id == anchor_id, MlBotMessage.bot_status == "drafting").first()
        if row is None:
            return
        row.bot_status = "awaiting_human"
        row.drafted_answer = answer
        row.intent_category = category
        row.confidence = confidence
        row.answer_source = answer_source
        row.llm_provider = provider_label
        row.drafted_at = datetime.now(timezone.utc)
        row.attempts = 0


def _mark_failed_or_retry(anchor_id: int, error_message: str) -> None:
    with get_background_db() as db:
        row = db.query(MlBotMessage).filter(MlBotMessage.id == anchor_id, MlBotMessage.bot_status == "drafting").first()
        if row is None:
            return
        new_attempts = (row.attempts or 0) + 1
        row.attempts = new_attempts
        row.last_error = error_message[:2000]
        row.bot_status = "failed" if new_attempts >= _MAX_ATTEMPTS else "pending"


async def _draft_one(anchor_id: int, provider: LlmProvider) -> str:
    """Orchestrate one claimed anchor through: fetch live thread -> guard
    against an already-human-answered pack -> manipulation check -> LLM
    classify+draft -> claim-category hard block -> denylist guardrail ->
    terminal write. Never raises — every failure routes to a terminal state
    or a bounded retry."""
    if not _claim_for_drafting(anchor_id):
        return "skipped_claimed_elsewhere"

    try:
        anchor = _load_anchor(anchor_id)
        if anchor is None:
            return "skipped_claimed_elsewhere"

        thread = await ml_client.get_pack_thread(anchor["pack_id"], anchor["seller_id"])
        if thread is None:
            _mark_failed_or_retry(anchor_id, "get_pack_thread returned no data")
            return "failed"

        messages = thread.get("messages") or []
        conversation_status = thread.get("conversation_status")

        burst_texts, history_turns, seller_already_replied = _split_thread(messages, anchor["seller_id"])
        if seller_already_replied:
            # A human already answered this pack directly in ML — never
            # draft over a live human reply.
            _mark_superseded(anchor_id)
            return "seller_already_replied"

        if conversation_status is not None and conversation_status.get("claim_ids"):
            # PR2: `claim_ids` non-empty is the PRIMARY, most reliable claim
            # signal (design "Claim detection via claim_ids") — hard-block
            # BEFORE any LLM call, no draft written. Checked before the
            # moderation_status/classifier fallbacks below.
            _mark_blocked_claim(anchor_id)
            return "blocked_claim"

        buyer_turn_text = context_builder.aggregate_buyer_turn(burst_texts or [anchor["text"]])

        if policy.detect_manipulation_signal(buyer_turn_text):
            # R-503-equivalent: manipulation signal -> flagged for human,
            # WITHOUT any LLM call (never auto-drafts on injection attempts).
            _mark_awaiting_human(
                anchor_id,
                answer="",
                category="other_unknown",
                confidence=0.0,
                answer_source="none",
                provider_label=None,
            )
            return "injection_flagged"

        moderation_status = anchor.get("moderation_status")
        if moderation_status and moderation_status != "clean":
            # Corroborating claim signal (design "Claim detection"): a
            # non-clean moderation status hard-blocks drafting regardless of
            # what the LLM would have classified.
            _mark_blocked_claim(anchor_id)
            return "blocked_claim"

        with get_background_db() as db:
            answer_max_chars = policy.get_config(
                db, "messages_answer_max_chars", cast=int, default=_DEFAULT_ANSWER_MAX_CHARS
            )
            few_shot_examples = context_builder.load_few_shot_examples(db)

        context = context_builder.build_scoped_context(
            buyer_turn_text=buyer_turn_text,
            conversation_history=history_turns,
            order_payload=None,
            few_shot_examples=few_shot_examples,
        )
        system_prompt, user_payload = context_builder.build_prompt(context, answer_max_chars)

        try:
            raw = await provider.complete(system_prompt, user_payload)
            parsed = parse_llm_output(raw, max_chars=answer_max_chars)
        except LlmProviderError as exc:
            logger.warning("ml-bot messages drafting: provider/parse failure for anchor %s: %s", anchor_id, exc)
            _mark_failed_or_retry(anchor_id, str(exc))
            return "failed"

        if parsed.category in _CLAIM_CATEGORIES:
            _mark_blocked_claim(anchor_id)
            return "blocked_claim"

        if not parsed.can_answer:
            _mark_awaiting_human(
                anchor_id,
                answer="",
                category=parsed.category,
                confidence=parsed.confidence,
                answer_source="none",
                provider_label=_resolve_provider_label(provider),
            )
            return "drafted_no_answer"

        if policy.violates_denylist(parsed.answer):
            _mark_awaiting_human(
                anchor_id,
                answer=_SAFE_FALLBACK_TEXT,
                category=parsed.category,
                confidence=parsed.confidence,
                answer_source="fallback",
                provider_label=_resolve_provider_label(provider),
            )
            return "fallback_denylist"

        _mark_awaiting_human(
            anchor_id,
            answer=parsed.answer,
            category=parsed.category,
            confidence=parsed.confidence,
            answer_source="bot",
            provider_label=_resolve_provider_label(provider),
        )
        return "drafted"

    except Exception as exc:  # noqa: BLE001 — must never crash the loop.
        logger.error("ml-bot messages drafting: unexpected error drafting anchor %s: %s", anchor_id, exc, exc_info=True)
        _mark_failed_or_retry(anchor_id, str(exc))
        return "failed"


async def run_ml_messages_draft_cycle(provider: Optional[LlmProvider] = None) -> Dict[str, Any]:
    """One drafting tick: reclaim stale claims -> supersede stale anchors ->
    settle+aggregate -> claim+draft each eligible anchor. Never raises."""
    stats: Dict[str, Any] = {
        "drafted": 0,
        "drafted_no_answer": 0,
        "fallback_denylist": 0,
        "injection_flagged": 0,
        "blocked_claim": 0,
        "seller_already_replied": 0,
        "failed": 0,
        "skipped_claimed_elsewhere": 0,
    }

    now = datetime.now(timezone.utc)
    _reclaim_stale_drafting(now)
    _supersede_stale_awaiting_human()

    anchor_ids = _fetch_settled_anchor_ids(now)
    if not anchor_ids:
        return stats

    active_provider = provider or _build_default_provider()

    for anchor_id in anchor_ids:
        try:
            outcome = await _draft_one(anchor_id, active_provider)
        except Exception as exc:  # noqa: BLE001 — one bad pack must not abort the batch.
            logger.error(
                "ml-bot messages drafting: unexpected error in tick for anchor %s: %s", anchor_id, exc, exc_info=True
            )
            outcome = "failed"
        stats[outcome] = stats.get(outcome, 0) + 1

    return stats
