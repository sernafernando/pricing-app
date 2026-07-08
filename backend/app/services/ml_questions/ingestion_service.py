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
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.core.database import get_background_db, get_mlwebhook_engine
from app.core.sse import sse_publish
from app.models.ml_bot_config import MlBotConfig
from app.models.ml_bot_question import MlBotQuestion
from app.services.ml_api_client import QuestionNotFoundError, ml_client
from app.services.ml_questions import policy

logger = logging.getLogger(__name__)

_CURSOR_KEY = "ingest_cursor_ts"
_STUCK_CURSOR_KEY = "ingest_stuck_cursor"
_STUCK_ATTEMPTS_KEY = "ingest_stuck_attempts"
_DEFAULT_BATCH_LIMIT = 100
_UNANSWERED_STATUS = "UNANSWERED"
_MAX_STUCK_ATTEMPTS = 10
# `get_config` treats an empty-string `valor` as "unset" (ADR-4/policy
# convention) and falls back to `default` — so a real "no cursor yet" state
# (empty/None cursor) can't be stored as "" for the stuck-cursor tracking
# key, since it would round-trip back as unset instead of matching. Use a
# non-empty marker instead.
_UNSET_CURSOR_MARKER = "__unset__"

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


def _parse_cursor(raw: Optional[str]) -> tuple[Optional[str], str]:
    """Parse the persisted `ingest_cursor_ts` value into `(since_ts,
    since_id)`. The cursor is stored as a composite "ISO_TS|webhook_id"
    string (WARNING fix: `webhook_id` is a tie-breaker for same-timestamp
    rows straddling a batch boundary). `webhook_id`'s column type varies by
    deployment (UUID in production's `webhooks` table, TEXT in
    `webhook_latest`) — we always compare it as text via an explicit
    `::text` cast, so it is parsed/carried as `str`, never coerced to `int`.
    Lexicographic order is fine for a tie-breaker. Backward-compat: a
    legacy scalar cursor (no "|" separator, from before this fix) is
    treated as `(ts, "")` so it keeps working across the upgrade without a
    migration. None/empty = no cursor yet -> `(None, "")`.

    Partitioning uses `str.partition` from the LEFT: the timestamp segment
    is always `datetime.isoformat()`, which never contains "|", so the
    first "|" found is guaranteed to be the ts/id separator. This assumes
    ML's webhook ids never contain "|" themselves (true for all observed
    ML id formats)."""
    if not raw:
        return None, ""
    if "|" in raw:
        ts_part, _, id_part = raw.partition("|")
        return (ts_part or None), id_part
    return raw, ""


def _format_cursor(received_at: datetime, webhook_id: str) -> str:
    """Serialize a composite cursor for persistence in `ml_bot_config`."""
    return f"{received_at.isoformat()}|{webhook_id}"


def fetch_new_webhook_rows(since: Optional[str], limit: int = _DEFAULT_BATCH_LIMIT) -> List[Dict[str, Any]]:
    """Read new `questions`-topic rows from mlwebhook's `webhooks` table.

    Args:
        since: persisted composite cursor string (`ingest_cursor_ts`,
            "ISO_TS|webhook_id" — see `_parse_cursor`). Rows with
            `received_at > since_ts`, OR `received_at == since_ts AND
            webhook_id > since_id`, are returned (WARNING fix: `webhook_id`
            tie-breaker prevents stranding same-timestamp rows at the batch
            boundary). None/empty = read from the beginning (first run /
            cursor never advanced).
        limit: batch size cap.

    Returns:
        List of dicts with keys: resource, topic, webhook_id, received_at —
        ordered by `received_at` ascending, `webhook_id` ascending.

    Raises:
        RuntimeError: if `ML_WEBHOOK_DB_URL` isn't configured — propagated to
        the caller, which treats it as a transient failure (log + skip tick).
    """
    engine = get_mlwebhook_engine()
    since_ts, since_id = _parse_cursor(since)

    # `webhook_id`'s column type varies by deployment (UUID in production's
    # `webhooks` table, TEXT in `webhook_latest`). `COALESCE(webhook_id::text,
    # '')` in both the WHERE tie-breaker and the ORDER BY casts to text first
    # (a bare COALESCE with a uuid column fails to cast against '') and gives
    # NULL rows a deterministic position (treated as the empty string) —
    # keyset pagination requires the WHERE comparison and the ORDER BY to
    # agree on the same total order, not on numeric monotonicity (TEXT
    # lexicographic order is fine here).
    if since_ts:
        where_clause = (
            "WHERE topic = 'questions' AND (received_at > :since_ts "
            "OR (received_at = :since_ts AND COALESCE(webhook_id::text, '') > :since_id))"
        )
        params: Dict[str, Any] = {"since_ts": since_ts, "since_id": since_id, "limit": limit}
    else:
        where_clause = "WHERE topic = 'questions'"
        params = {"limit": limit}

    with engine.connect() as conn:
        rows = conn.execute(
            text(f"""
                SELECT resource, topic, webhook_id, received_at
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
            "topic": row[1],
            "webhook_id": row[2],
            "received_at": row[3],
        }
        for row in rows
    ]


def _parse_question_date(raw: Optional[str]) -> datetime:
    """Parse ML's ISO8601 `date_created` (offset-aware) into a datetime.
    Falls back to `now(UTC)` if missing/unparseable — never raises, since a
    bad date on one question must not abort the whole ingest batch."""
    if raw:
        try:
            parsed = datetime.fromisoformat(raw)
        except ValueError:
            logger.warning("ml-bot ingestion: malformed date_created=%r; using now(UTC)", raw)
        else:
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed
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

    with get_background_db() as db:
        cursor = policy.get_config(db, _CURSOR_KEY, cast=str, default=None)
        stuck_cursor = policy.get_config(db, _STUCK_CURSOR_KEY, cast=str, default=_UNSET_CURSOR_MARKER)
        stuck_attempts = policy.get_config(db, _STUCK_ATTEMPTS_KEY, cast=int, default=0) or 0

    # Item #6 (PR de pulido): when NO cursor has ever been persisted
    # (fresh install / cursor never advanced), default the query window to
    # the last 48h instead of the beginning of mlwebhook's `webhooks` table
    # — a full-history backfill on first boot would flood the drafting
    # pipeline with stale questions. This is a QUERY-window default only;
    # the persisted `ingest_cursor_ts` itself is only ever written from an
    # actually-processed row's `received_at` below, same as before.
    effective_since = (
        cursor if cursor is not None else _format_cursor(datetime.now(timezone.utc) - timedelta(hours=48), "")
    )

    try:
        webhook_rows = fetch_new_webhook_rows(since=effective_since)
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
    max_webhook_id = ""

    # Bounded-retry state for a row stuck at the current cursor position
    # (e.g. a permanently-transient condition like an expired token, which
    # would otherwise stall ingestion forever). `stuck_cursor`/`stuck_attempts`
    # are persisted in `ml_bot_config` and only relevant while the cursor
    # hasn't moved since the last tick that hit this position.
    #
    # CRITICAL fix: the stuck/attempts machinery applies ONLY to the FIRST
    # row of the tick (index 0) — i.e. the row sitting immediately AFTER the
    # persisted cursor position (never AT it — the cursor marks the last
    # resolved row, not an unresolved one). Rows are fetched in `received_at ASC,
    # webhook_id ASC` order, so index 0 is always the oldest unprocessed
    # row (documented choice — cleaner than tracking row identity). Any
    # OTHER row failing transiently in the same tick keeps today's
    # behavior: stop the tick (break) without advancing past it, so it
    # becomes the stuck candidate NEXT tick, starting fresh from attempt 1
    # — it must never inherit an already-poisoned counter from a different
    # row that gave up earlier in this same tick.
    normalized_cursor = cursor if cursor else _UNSET_CURSOR_MARKER
    attempts_at_cursor = stuck_attempts if stuck_cursor == normalized_cursor else 0

    for index, row in enumerate(webhook_rows):
        received_at = row["received_at"]
        webhook_id = str(row["webhook_id"]) if row["webhook_id"] is not None else ""

        question_id = _extract_question_id(row["resource"])
        if question_id is None:
            logger.warning("ml-bot ingestion: could not parse question id from resource=%r", row["resource"])
            max_received_at = received_at
            max_webhook_id = webhook_id
            continue

        try:
            ml_question = await ml_client.get_question(question_id)
        except QuestionNotFoundError:
            # Terminal outcome: ML confirms the question no longer exists.
            # Skip the row (terminally resolved) and advance the cursor past
            # it — retrying a deleted question would stall ingestion forever.
            # Item #7 (PR de pulido): an ML question disappearing (deleted /
            # buyer removed it) is an EXPECTED, terminal, non-actionable
            # outcome for a poller — not an operational error. Downgraded
            # from ERROR to WARNING so alerting on ERROR-level ingestion
            # logs doesn't page on-call for routine ML-side deletions.
            logger.warning(
                "ml-bot ingestion: question %s not found in ML (404) — skipping row, cursor advances",
                question_id,
            )
            max_received_at = received_at
            max_webhook_id = webhook_id
            continue
        except Exception as e:
            logger.error("ml-bot ingestion: error fetching question %s: %s", question_id, e, exc_info=True)
            stats["error"] = True
            break

        if not ml_question:
            # Transient failure (network/timeout/5xx/auth) — `get_question`
            # returns None. Fail safe: stop advancing the cursor so this row
            # gets retried, UNLESS it's the first row of the tick AND it has
            # already failed `_MAX_STUCK_ATTEMPTS` times at this same cursor
            # position, in which case a permanently-transient condition
            # (e.g. an expired token) must not be allowed to stall ingestion
            # forever — give up and skip the row.
            if index == 0:
                attempts_at_cursor += 1
                if attempts_at_cursor >= _MAX_STUCK_ATTEMPTS:
                    logger.error(
                        "ml-bot ingestion: giving up after %d attempts fetching question %s — skipping row, cursor advances",
                        attempts_at_cursor,
                        question_id,
                    )
                    max_received_at = received_at
                    max_webhook_id = webhook_id
                    stats["error"] = True
                    # BREAK (not continue): the poisoned attempts counter
                    # must not carry over to any later row in this tick —
                    # they get resumed cleanly next tick with a fresh count.
                    break

            logger.warning("ml-bot ingestion: get_question(%s) returned no data — will retry next tick", question_id)
            stats["error"] = True
            break

        max_received_at = received_at
        max_webhook_id = webhook_id

        if ml_question.get("status") != _UNANSWERED_STATUS:
            stats["skipped_answered"] += 1
            continue

        buyer = ml_question.get("from") or {}
        item_id = ml_question.get("item_id") or ""

        # Item enrichment (panel-v2 requirement #2, ADR-5): best-effort only
        # — a failure here (network/404/etc.) must never block ingestion of
        # the question itself. No DB session is open across this call.
        item_title: Optional[str] = None
        item_permalink: Optional[str] = None
        if item_id:
            try:
                item_payload = await ml_client.get_item(item_id)
            except Exception as e:  # noqa: BLE001 — enrichment is non-fatal.
                logger.warning("ml-bot ingestion: enrichment failed for item %s: %s", item_id, e)
                item_payload = None
            if item_payload:
                # Defensive truncation to the column widths (String(200) /
                # String(500)) — ML titles are normally far shorter, but a
                # DataError here (unlike IntegrityError) would NOT be caught
                # below and would break the "enrichment never blocks
                # ingestion" invariant.
                raw_title = item_payload.get("title")
                raw_permalink = item_payload.get("permalink")
                item_title = raw_title[:200] if raw_title else None
                # Scheme validation: ML always serves item permalinks over
                # https — anything else (javascript:, data:, http:, etc.)
                # is rejected and never stored, since this value is later
                # rendered as an href in the frontend without further checks.
                if raw_permalink and raw_permalink.startswith("https://"):
                    item_permalink = raw_permalink[:500]
                else:
                    if raw_permalink:
                        logger.warning(
                            "ml-bot ingestion: rejected item permalink with invalid scheme for item %s: %s",
                            item_id,
                            raw_permalink[:100],
                        )
                    item_permalink = None

        new_row = MlBotQuestion(
            ml_question_id=question_id,
            item_id=item_id,
            item_title=item_title,
            item_permalink=item_permalink,
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
            await sse_publish("ml_bot:questions", {"hint": "reload"})
        except IntegrityError:
            stats["duplicates"] += 1

    def _upsert_config(db: Any, clave: str, valor: str) -> None:
        row = db.query(MlBotConfig).filter_by(clave=clave).first()
        if row is None:
            db.add(MlBotConfig(clave=clave, valor=valor, tipo="string"))
        else:
            row.valor = valor

    if max_received_at is not None:
        # Item #8 (PR de pulido): before writing the end-of-tick cursor,
        # re-read the CURRENT persisted value IN THE SAME short session —
        # if it changed from what this tick started with (an admin manually
        # UPDATE'd `ingest_cursor_ts` mid-tick, e.g. to skip a poison-pill
        # row or rewind), do NOT overwrite it with this tick's stale
        # computation. Log and skip the write; the next tick picks up the
        # manual value and re-reads from there. Single `get_background_db()`
        # block (ADR-5) — the read-then-conditionally-write is atomic within
        # one short session, same as every other write in this module.
        with get_background_db() as db:
            current = policy.get_config(db, _CURSOR_KEY, cast=str, default=None)
            if current != cursor:
                logger.warning(
                    "ml-bot ingestion: cursor changed manually mid-tick (started=%r, now=%r) — "
                    "skipping this tick's cursor write to respect the manual adjustment",
                    cursor,
                    current,
                )
            else:
                # Cursor unchanged this tick — safe to advance it, and reset
                # the stuck-row counter (it no longer applies to the new
                # position).
                _upsert_config(db, _CURSOR_KEY, _format_cursor(max_received_at, max_webhook_id))
                _upsert_config(db, _STUCK_CURSOR_KEY, _UNSET_CURSOR_MARKER)
                _upsert_config(db, _STUCK_ATTEMPTS_KEY, "0")
    elif attempts_at_cursor > 0:
        # Still stuck at the same cursor position — persist the updated
        # attempts counter so it survives across ticks.
        with get_background_db() as db:
            _upsert_config(db, _STUCK_CURSOR_KEY, normalized_cursor)
            _upsert_config(db, _STUCK_ATTEMPTS_KEY, str(attempts_at_cursor))

    return stats
