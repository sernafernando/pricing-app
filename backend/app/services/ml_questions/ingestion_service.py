"""
Cross-DB ingestion bridge for the ML questions bot (Slice C).

Reads mlwebhook's `webhooks` table (READ-ONLY, via `get_mlwebhook_engine()`),
filtered to `topic='questions'`, dedupes against the `ingest_cursor_ts` scalar
cursor stored in `ml_bot_config` (ADR-7), fetches the full question via
`ml_client.get_question()`, and inserts idempotent `ml_bot_questions` rows in
state `received` (design §4, spec R-101/R-102/R-103).

This slice does NOT draft or publish anything — that's Slice D/E. It only
brings new buyer questions into `ml_bot_questions`.

Session discipline (ADR-5, regression guard for the prior QueuePool-exhaustion
incident): the cross-DB read (`fetch_new_webhook_rows`) and the ML API call
(`ml_client.get_question`) never happen while a pricing-app DB session is
open. Every DB write is its own short `get_background_db()` block — mirrors
`free_shipping_auto_fix.py`'s "open -> act without DB -> open" discipline.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.core.database import get_background_db, get_mlwebhook_engine
from app.models.ml_bot_config import MlBotConfig
from app.models.ml_bot_question import MlBotQuestion
from app.services.ml_api_client import ml_client
from app.services.ml_questions import policy

logger = logging.getLogger(__name__)

_CURSOR_KEY = "ingest_cursor_ts"
_DEFAULT_BATCH_LIMIT = 100
_UNANSWERED_STATUS = "UNANSWERED"

_QUESTION_ID_RE = re.compile(r"/questions/(\d+)\s*$")


def _extract_question_id(resource: str) -> Optional[int]:
    """Parse the trailing numeric question id out of a webhook `resource`
    path (e.g. "/questions/123456789" -> 123456789). Returns None for any
    resource that doesn't match the expected `questions` shape."""
    if not resource:
        return None
    match = _QUESTION_ID_RE.search(resource)
    if not match:
        return None
    return int(match.group(1))


def fetch_new_webhook_rows(since: Optional[str], limit: int = _DEFAULT_BATCH_LIMIT) -> List[Dict[str, Any]]:
    """Read new `questions`-topic rows from mlwebhook's `webhooks` table.

    Args:
        since: ISO cursor string (`ingest_cursor_ts`); rows with
            `received_at > since` are returned. None/empty = read from the
            beginning (first run / cursor never advanced).
        limit: batch size cap.

    Returns:
        List of dicts with keys: resource, topic, webhook_id, received_at,
        payload — ordered by `received_at` ascending.

    Raises:
        RuntimeError: if `ML_WEBHOOK_DB_URL` isn't configured — propagated to
        the caller, which treats it as a transient failure (log + skip tick).
    """
    engine = get_mlwebhook_engine()

    where_clause = "WHERE topic = 'questions' AND received_at > :since" if since else "WHERE topic = 'questions'"

    with engine.connect() as conn:
        rows = conn.execute(
            text(f"""
                SELECT resource, topic, webhook_id, received_at, payload
                FROM webhooks
                {where_clause}
                ORDER BY received_at ASC
                LIMIT :limit
            """),
            {"since": since, "limit": limit} if since else {"limit": limit},
        ).fetchall()

    return [
        {
            "resource": row[0],
            "topic": row[1],
            "webhook_id": row[2],
            "received_at": row[3],
            "payload": row[4],
        }
        for row in rows
    ]


def _parse_question_date(raw: Optional[str]) -> datetime:
    """Parse ML's ISO8601 `date_created` (offset-aware) into a datetime.
    Falls back to `now(UTC)` if missing/unparseable — never raises, since a
    bad date on one question must not abort the whole ingest batch."""
    if raw:
        try:
            return datetime.fromisoformat(raw)
        except ValueError:
            logger.warning("ml-bot ingestion: malformed date_created=%r; using now(UTC)", raw)
    return datetime.now(timezone.utc)


async def run_ml_questions_ingest_cycle() -> Dict[str, Any]:
    """One ingestion tick: read cursor -> fetch new webhook rows -> fetch full
    question per row -> idempotent insert -> advance cursor.

    Returns a stats dict (ingested/skipped_answered/duplicates/error) for
    logging by the caller background-task loop. Never raises — external
    failures (mlwebhook unreachable, ML API errors) are logged and degrade to
    a no-op tick, mirroring `free_shipping_auto_fix`'s resilience pattern.
    """
    stats: Dict[str, Any] = {
        "ingested": 0,
        "skipped_answered": 0,
        "duplicates": 0,
        "error": False,
    }

    now = datetime.now(timezone.utc)

    with get_background_db() as db:
        cursor = policy.get_config(db, _CURSOR_KEY, cast=str, default=None)
        # Forward-looking eligibility hint (logged only — this slice never
        # drafts). MUST pass an aware datetime: policy treats naive as local
        # wall-clock (integration gotcha).
        try:
            policy.is_eligible_for_bot(db, now)
        except Exception as e:  # pragma: no cover - defensive, policy is pure
            logger.warning("ml-bot ingestion: eligibility check failed: %s", e)

    try:
        webhook_rows = fetch_new_webhook_rows(since=cursor)
    except RuntimeError as e:
        logger.warning("ml-bot ingestion: mlwebhook unreachable (%s) — skipping tick", e)
        stats["error"] = True
        return stats
    except Exception as e:
        logger.error("ml-bot ingestion: error reading webhooks: %s", e, exc_info=True)
        stats["error"] = True
        return stats

    if not webhook_rows:
        return stats

    # `max_received_at` only ever advances past rows that were PERMANENTLY
    # resolved this tick (ingested, duplicate, skipped-answered, or an
    # unparseable resource). A row whose `ml_client.get_question()` fetch
    # failed (network error, expired token, etc.) is a TRANSIENT failure —
    # advancing the cursor past it would silently drop that buyer question
    # forever, since the poller never re-reads rows before the cursor. On the
    # first transient failure we stop advancing (and stop processing further
    # rows this tick, since they're newer and would otherwise let the cursor
    # skip over the still-unresolved row on the next tick's `received_at >
    # cursor` filter).
    max_received_at = None

    for row in webhook_rows:
        received_at = row["received_at"]

        question_id = _extract_question_id(row["resource"])
        if question_id is None:
            logger.warning("ml-bot ingestion: could not parse question id from resource=%r", row["resource"])
            if max_received_at is None or received_at > max_received_at:
                max_received_at = received_at
            continue

        try:
            ml_question = await ml_client.get_question(question_id)
        except Exception as e:
            logger.error("ml-bot ingestion: error fetching question %s: %s", question_id, e, exc_info=True)
            stats["error"] = True
            break

        if not ml_question:
            # `ml_client.get_question` swallows its own exceptions and
            # returns None for both a permanent 404 and a transient error —
            # it can't be distinguished here. Fail safe: treat as transient
            # and stop advancing the cursor, so this row gets retried.
            logger.warning("ml-bot ingestion: get_question(%s) returned no data — will retry next tick", question_id)
            stats["error"] = True
            break

        if max_received_at is None or received_at > max_received_at:
            max_received_at = received_at

        if ml_question.get("status") != _UNANSWERED_STATUS:
            stats["skipped_answered"] += 1
            continue

        buyer = ml_question.get("from") or {}
        new_row = MlBotQuestion(
            ml_question_id=question_id,
            item_id=ml_question.get("item_id") or "",
            buyer_id=buyer.get("id"),
            buyer_nickname=buyer.get("nickname"),
            question_text=ml_question.get("text") or "",
            question_date=_parse_question_date(ml_question.get("date_created")),
            status="received",
        )

        try:
            with get_background_db() as db:
                db.add(new_row)
                db.flush()
            stats["ingested"] += 1
        except IntegrityError:
            stats["duplicates"] += 1

    if max_received_at is not None:
        with get_background_db() as db:
            cursor_row = db.query(MlBotConfig).filter_by(clave=_CURSOR_KEY).first()
            new_value = max_received_at.isoformat()
            if cursor_row is None:
                db.add(MlBotConfig(clave=_CURSOR_KEY, valor=new_value, tipo="string"))
            else:
                cursor_row.valor = new_value

    return stats
