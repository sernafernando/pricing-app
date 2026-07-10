"""
Cross-DB ingestion bridge for the ML postventa messages MVP (read-only,
sdd/ml-bot-postventa-messages-mvp, PR1).

Reads mlwebhook's `webhooks` table (READ-ONLY, via `get_mlwebhook_engine()`),
filtered to `topic='messages'`, dedupes against the `ingest_cursor_ts_messages`
composite cursor stored in `ml_bot_config` (ADR-7, mirrors
`ml_questions/ingestion_service.py`), fetches the full message via
`ml_client.get_message()`, and either:

  - `actions[0] == 'created'` -> idempotent INSERT into `ml_bot_messages`
    (filtering outgoing seller messages), or
  - `actions[0] == 'read'` -> SELECT-then-UPDATE `read_at` on the existing
    row (log-skip on miss — never creates a phantom row).

Session discipline (ADR-5): the cross-DB read and the ML API call never
happen while a pricing-app DB session is open. Every DB write is its own
short `get_background_db()` block.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.core.database import get_background_db, get_mlwebhook_engine
from app.core.sse import sse_publish
from app.models.ml_bot_config import MlBotConfig
from app.models.ml_bot_message import MlBotMessage
from app.services.ml_api_client import MessageNotFoundError, ml_client
from app.services.ml_questions import policy

logger = logging.getLogger(__name__)

_CURSOR_KEY = "ingest_cursor_ts_messages"
_STUCK_CURSOR_KEY = "ingest_stuck_cursor_messages"
_STUCK_ATTEMPTS_KEY = "ingest_stuck_attempts_messages"
_DEFAULT_BATCH_LIMIT = 100
_MAX_STUCK_ATTEMPTS = 10
_UNSET_CURSOR_MARKER = "__unset__"

# Our seller (Gauss) — outgoing messages `from.user_id == _SELLER_ID` are
# filtered at ingest and never persisted (design decision #5).
_SELLER_ID = 413658225


def _parse_cursor(raw: Optional[str]) -> tuple[Optional[str], str]:
    """Parse the persisted `ingest_cursor_ts_messages` value into
    `(since_ts, since_id)` — same composite-cursor shape as
    `ml_questions.ingestion_service._parse_cursor` (ADR-7 + tie-breaker)."""
    if not raw:
        return None, ""
    if "|" in raw:
        ts_part, _, id_part = raw.partition("|")
        return (ts_part or None), id_part
    return raw, ""


def _format_cursor(received_at: datetime, webhook_id: str) -> str:
    return f"{received_at.isoformat()}|{webhook_id}"


def fetch_new_webhook_rows(since: Optional[str], limit: int = _DEFAULT_BATCH_LIMIT) -> List[Dict[str, Any]]:
    """Read new `messages`-topic rows from mlwebhook's `webhooks` table.

    Returns a list of dicts with keys: resource (used verbatim as the ML
    message id — design §Interfaces), actions (list, e.g. `['created']` or
    `['read']`), webhook_id, received_at — ordered by `received_at` ASC,
    `webhook_id` ASC.
    """
    engine = get_mlwebhook_engine()
    since_ts, since_id = _parse_cursor(since)

    if since_ts:
        where_clause = (
            "WHERE topic = 'messages' AND (received_at > :since_ts "
            "OR (received_at = :since_ts AND COALESCE(webhook_id::text, '') > :since_id))"
        )
        params: Dict[str, Any] = {"since_ts": since_ts, "since_id": since_id, "limit": limit}
    else:
        where_clause = "WHERE topic = 'messages'"
        params = {"limit": limit}

    with engine.connect() as conn:
        rows = conn.execute(
            text(f"""
                SELECT resource, actions, webhook_id, received_at
                FROM webhooks
                {where_clause}
                ORDER BY received_at ASC, COALESCE(webhook_id::text, '') ASC
                LIMIT :limit
            """),
            params,
        ).fetchall()

    return [
        {
            "resource": row[0],
            "actions": row[1] or [],
            "webhook_id": row[2],
            "received_at": row[3],
        }
        for row in rows
    ]


def _parse_message_date(raw: Optional[str]) -> datetime:
    """Parse ML's ISO8601 `date_created` (offset-aware). Falls back to
    `now(UTC)` if missing/unparseable — never raises."""
    if raw:
        try:
            parsed = datetime.fromisoformat(raw)
        except ValueError:
            logger.warning("ml-bot messages ingestion: malformed date_created=%r; using now(UTC)", raw)
        else:
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed
    return datetime.now(timezone.utc)


def _extract_pack_id(message_resources: Optional[List[Dict[str, Any]]]) -> Optional[str]:
    """Extract `pack_id` from `message_resources` (a list of `{name, id}`
    entries) — looks for the entry named `packs`. Missing entry degrades
    gracefully to None (design §Schema, spec "Missing pack entry degrades
    gracefully")."""
    for entry in message_resources or []:
        if entry.get("name") == "packs":
            return entry.get("id")
    return None


async def run_ml_messages_ingest_cycle() -> Dict[str, Any]:
    """One ingestion tick: read cursor -> fetch new webhook rows -> fetch full
    message per row -> branch on actions[0] -> advance cursor.

    Returns a stats dict for logging by the caller background-task loop.
    Never raises — external failures degrade to a no-op tick.
    """
    stats: Dict[str, Any] = {
        "created": 0,
        "read_updated": 0,
        "read_skipped": 0,
        "outgoing_skipped": 0,
        "duplicates": 0,
        "error": False,
    }

    with get_background_db() as db:
        cursor = policy.get_config(db, _CURSOR_KEY, cast=str, default=None)
        stuck_cursor = policy.get_config(db, _STUCK_CURSOR_KEY, cast=str, default=_UNSET_CURSOR_MARKER)
        stuck_attempts = policy.get_config(db, _STUCK_ATTEMPTS_KEY, cast=int, default=0) or 0

    # No cursor ever persisted -> default the query window to the last 48h
    # (same as ml_questions), never a full-history backfill on first boot.
    effective_since = (
        cursor if cursor is not None else _format_cursor(datetime.now(timezone.utc) - timedelta(hours=48), "")
    )

    try:
        webhook_rows = fetch_new_webhook_rows(since=effective_since)
    except RuntimeError as e:
        logger.warning("ml-bot messages ingestion: mlwebhook unreachable (%s) — skipping tick", e)
        stats["error"] = True
        return stats
    except Exception as e:
        logger.error("ml-bot messages ingestion: error reading webhooks: %s", e, exc_info=True)
        stats["error"] = True
        return stats

    if not webhook_rows:
        return stats

    max_received_at = None
    max_webhook_id = ""

    normalized_cursor = cursor if cursor else _UNSET_CURSOR_MARKER
    attempts_at_cursor = stuck_attempts if stuck_cursor == normalized_cursor else 0

    for index, row in enumerate(webhook_rows):
        received_at = row["received_at"]
        webhook_id = str(row["webhook_id"]) if row["webhook_id"] is not None else ""
        message_id = row["resource"]
        actions = row["actions"] or []
        action = actions[0] if actions else None

        if not message_id or action not in ("created", "read"):
            logger.warning("ml-bot messages ingestion: skipping row with resource=%r actions=%r", message_id, actions)
            max_received_at = received_at
            max_webhook_id = webhook_id
            continue

        try:
            ml_message = await ml_client.get_message(message_id)
        except MessageNotFoundError:
            # Terminal outcome — message deleted in ML. Skip, advance cursor,
            # do not crash (spec "Deleted message returns 404").
            logger.warning(
                "ml-bot messages ingestion: message %s not found in ML (404) — skipping row, cursor advances",
                message_id,
            )
            max_received_at = received_at
            max_webhook_id = webhook_id
            continue
        except Exception as e:
            logger.error("ml-bot messages ingestion: error fetching message %s: %s", message_id, e, exc_info=True)
            stats["error"] = True
            break

        if not ml_message:
            # Transient failure — get_message returned None. Fail safe:
            # stop advancing the cursor so this row gets retried, unless the
            # bounded-retry cap is hit at the current cursor position.
            if index == 0:
                attempts_at_cursor += 1
                if attempts_at_cursor >= _MAX_STUCK_ATTEMPTS:
                    logger.error(
                        "ml-bot messages ingestion: giving up after %d attempts fetching message %s — "
                        "skipping row, cursor advances",
                        attempts_at_cursor,
                        message_id,
                    )
                    max_received_at = received_at
                    max_webhook_id = webhook_id
                    stats["error"] = True
                    break

            logger.warning(
                "ml-bot messages ingestion: get_message(%s) returned no data — will retry next tick", message_id
            )
            stats["error"] = True
            break

        max_received_at = received_at
        max_webhook_id = webhook_id

        if action == "created":
            await _handle_created(ml_message, message_id, stats)
        else:
            await _handle_read(ml_message, message_id, stats)

    _persist_cursor(cursor, max_received_at, max_webhook_id, attempts_at_cursor)

    return stats


async def _handle_created(ml_message: Dict[str, Any], message_id: str, stats: Dict[str, Any]) -> None:
    from_user = ml_message.get("from") or {}

    if from_user.get("user_id") == _SELLER_ID:
        stats["outgoing_skipped"] += 1
        logger.info("ml-bot messages ingestion: outgoing message %s skipped (seller-authored)", message_id)
        return

    moderation_status = (ml_message.get("message_moderation") or {}).get("status")
    buyer_nickname = from_user.get("nickname") or from_user.get("user_name")
    pack_id = _extract_pack_id(ml_message.get("message_resources"))

    new_row = MlBotMessage(
        ml_message_id=message_id,
        pack_id=pack_id,
        buyer_id=from_user.get("user_id"),
        buyer_nickname=buyer_nickname,
        seller_id=_SELLER_ID,
        subject=ml_message.get("subject"),
        text=ml_message.get("text") or "",
        status=ml_message.get("status") or "available",
        moderation_status=moderation_status,
        is_first_message=bool(ml_message.get("first_message", False)),
        attachments=ml_message.get("attachments") or None,
        received_at=_parse_message_date(ml_message.get("date_created")),
    )

    try:
        with get_background_db() as db:
            db.add(new_row)
            db.flush()
        stats["created"] += 1
        await sse_publish("ml_bot:messages", {"type": "message_created", "id": message_id})
    except IntegrityError:
        stats["duplicates"] += 1


async def _handle_read(ml_message: Dict[str, Any], message_id: str, stats: Dict[str, Any]) -> None:
    with get_background_db() as db:
        row = db.query(MlBotMessage).filter_by(ml_message_id=message_id).first()
        if row is None:
            stats["read_skipped"] += 1
            logger.warning(
                "ml-bot messages ingestion: read event for message %s with no matching row — skipping", message_id
            )
            return
        row.read_at = _parse_message_date(ml_message.get("date_read") or ml_message.get("date_created"))
        db.flush()
        stats["read_updated"] += 1

    await sse_publish("ml_bot:messages", {"type": "message_read", "id": message_id})


def _persist_cursor(
    started_cursor: Optional[str],
    max_received_at: Optional[datetime],
    max_webhook_id: str,
    attempts_at_cursor: int,
) -> None:
    def _upsert_config(db: Any, clave: str, valor: str) -> None:
        row = db.query(MlBotConfig).filter_by(clave=clave).first()
        if row is None:
            db.add(MlBotConfig(clave=clave, valor=valor, tipo="string"))
        else:
            row.valor = valor

    if max_received_at is not None:
        # CAS re-read (ADR-7): if the persisted cursor changed mid-tick
        # (manual admin edit), skip this tick's write to respect it.
        with get_background_db() as db:
            current = policy.get_config(db, _CURSOR_KEY, cast=str, default=None)
            if current != started_cursor:
                logger.warning(
                    "ml-bot messages ingestion: cursor changed manually mid-tick (started=%r, now=%r) — "
                    "skipping this tick's cursor write to respect the manual adjustment",
                    started_cursor,
                    current,
                )
            else:
                _upsert_config(db, _CURSOR_KEY, _format_cursor(max_received_at, max_webhook_id))
                _upsert_config(db, _STUCK_CURSOR_KEY, _UNSET_CURSOR_MARKER)
                _upsert_config(db, _STUCK_ATTEMPTS_KEY, "0")
    elif attempts_at_cursor > 0:
        normalized_cursor = started_cursor if started_cursor else _UNSET_CURSOR_MARKER
        with get_background_db() as db:
            _upsert_config(db, _STUCK_CURSOR_KEY, normalized_cursor)
            _upsert_config(db, _STUCK_ATTEMPTS_KEY, str(attempts_at_cursor))
