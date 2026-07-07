"""
Wait-window publisher for the ML questions bot (Slice E).

Implements design §8's publish loop: rows sitting in `waiting` past their
`wait_until` deadline get their `drafted_answer` posted to MercadoLibre and
move to `published`. This module never drafts anything (Slice D) and never
handles panel takeover/config endpoints (Slice F) — it only moves a row from
`waiting` to a terminal outcome, or bounces it back for a bounded retry.

Pipeline per row (design §8):
1. Batch select: `status='waiting' AND wait_until <= now`, oldest first. A
   row that a human has already taken over (`taken_over`) or held
   (`pending_morning`) is excluded by this predicate alone — human takeover
   always wins the race (no extra check needed downstream).
2. Claim: CAS UPDATE `waiting -> publishing` (transient marker, same shape
   as drafting's `received -> drafting` claim). Guards concurrent publish
   ticks and lets the ML POST happen without holding the row lock.
3. ML POST happens with NO DB session open (ADR-5, the exact discipline
   that fixed the QueuePool incident) — the row was already released after
   step 2's short `get_background_db()` block committed.
4. Terminal write (second short `get_background_db()` block):
   - Success -> `published`, `published_at` set.
   - ML "already answered" (`QuestionAlreadyAnsweredError`) -> treated as
     success-equivalent -> `published` (idempotency: a retried publish
     after a crash between the POST and the terminal write must not fail).
   - Other failure -> bounded retry: `attempts` (read FRESH from the DB in
     the same short session as the write, per the D2 Judgment Day fix —
     never trust a caller-captured value) incremented; back to `waiting`
     under `_MAX_ATTEMPTS`, else `failed` with `last_error`.
5. Stale-claim reclaim: any row still `publishing` past
   `_PUBLISHING_STALE_MINUTES` (measured off `updated_at`) is CAS-reverted
   to `waiting` at the start of every cycle — covers the SIGKILL-between-
   claim-and-terminal-write case, same pattern as drafting's
   `_reclaim_stale_drafting_claims`.

Adjudicated invariant (carried over from the D2 Judgment Day round-2 note):
this reclaim, and the claim/terminal-write CAS transitions in general, are
safe ONLY because the publish cycle runs strictly sequentially in a single
worker (the `fcntl` lock in `main.py`) — a stalled ML call blocks the whole
loop, so a row still `publishing` past the staleness window can only belong
to a dead/crashed process, never a concurrently-running one. If the cycle is
ever invoked concurrently (an admin "publish now" endpoint sharing this same
claim, or multiple workers), the terminal writes would need an
ownership/lease token to avoid two processes racing on the same claimed row.

Double-publish defense stack (design §8, risk #3, same class as the pool
incident): single-worker lock + status CAS transitions + short
`get_background_db()` sessions + never holding a session across the ML
call. `FOR UPDATE SKIP LOCKED` is intentionally NOT used here (belt-and-
suspenders for a hypothetical future multi-worker setup, per design §8) —
the plain SELECT + per-row CAS UPDATE is the same pattern already
established (and Judgment-Day-hardened) by `drafting_service`'s claim, and
it is portable to the project's SQLite test suite.

Session discipline (ADR-5, QueuePool-incident regression guard): every DB
read/write here is its own short `get_background_db()` block.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import func, update

from app.core.database import get_background_db
from app.models.ml_bot_question import MlBotQuestion
from app.services.ml_api_client import (
    AnswerPostPermanentError,
    QuestionAlreadyAnsweredError,
    QuestionNotFoundError,
    ml_client,
)

logger = logging.getLogger(__name__)

_BATCH_LIMIT = 20
_MAX_ATTEMPTS = 3

# Same rationale as drafting_service._DRAFTING_STALE_MINUTES: a row still
# `publishing` this long after its last update can only belong to a dead
# process (single-worker sequential loop) and must be retried, not left
# stuck forever.
_PUBLISHING_STALE_MINUTES = 15


def _reclaim_stale_publishing_claims(now: datetime) -> int:
    """CAS-revert any row still `publishing` past `_PUBLISHING_STALE_MINUTES`
    back to `waiting` so it gets retried on a later tick."""
    threshold = now - timedelta(minutes=_PUBLISHING_STALE_MINUTES)
    with get_background_db() as db:
        result = db.execute(
            update(MlBotQuestion)
            .where(MlBotQuestion.status == "publishing", MlBotQuestion.updated_at < threshold)
            .values(status="waiting")
        )
        reclaimed = result.rowcount

    if reclaimed:
        logger.warning(
            "ml-bot publisher: reclaimed %d stale 'publishing' row(s) older than %d minutes",
            reclaimed,
            _PUBLISHING_STALE_MINUTES,
        )
    return reclaimed


def _fetch_due_ids(now: datetime) -> List[int]:
    """Rows due for publication: `waiting` and past `wait_until`. Excludes
    `taken_over`/`pending_morning`/anything else by construction — human
    takeover always wins the race (design §8 point 2)."""
    with get_background_db() as db:
        return [
            row.id
            for row in db.query(MlBotQuestion)
            .filter(MlBotQuestion.status == "waiting", MlBotQuestion.wait_until <= now)
            .order_by(MlBotQuestion.wait_until.asc())
            .limit(_BATCH_LIMIT)
            .all()
        ]


def _claim_for_publishing(question_id: int) -> bool:
    """CAS transition `waiting -> publishing`. Returns True only if THIS
    call won the claim (guards concurrent publish-cycle ticks)."""
    with get_background_db() as db:
        result = db.execute(
            update(MlBotQuestion)
            .where(MlBotQuestion.id == question_id, MlBotQuestion.status == "waiting")
            .values(status="publishing", updated_at=func.now())
        )
        return result.rowcount == 1


def _load_question(question_id: int) -> Optional[Dict[str, Any]]:
    """Read the claimed row's plain data (short session) — nothing
    ORM-bound is held across the ML POST downstream (ADR-5)."""
    with get_background_db() as db:
        row = db.query(MlBotQuestion).filter(MlBotQuestion.id == question_id).first()
        if row is None:
            return None
        return {
            "id": row.id,
            "ml_question_id": row.ml_question_id,
            "drafted_answer": row.drafted_answer,
            "attempts": row.attempts,
        }


def _mark_published(question_id: int) -> None:
    """Success (or ML "already answered" success-equivalent) -> `published`."""
    with get_background_db() as db:
        row = (
            db.query(MlBotQuestion)
            .filter(MlBotQuestion.id == question_id, MlBotQuestion.status == "publishing")
            .first()
        )
        if row is None:
            return
        row.status = "published"
        row.published_at = datetime.now(timezone.utc)


def _revert_to_waiting_without_penalty(question_id: int) -> None:
    """CAS-revert a claimed row back to `waiting` WITHOUT touching
    `attempts`/`last_error` — used when a retry-verification `get_question`
    call fails transiently (Judgment Day fix 1b): no POST was attempted, so
    this is not a failed publish attempt and must not burn the bounded
    retry budget."""
    with get_background_db() as db:
        db.execute(
            update(MlBotQuestion)
            .where(MlBotQuestion.id == question_id, MlBotQuestion.status == "publishing")
            .values(status="waiting")
        )


def _mark_failed_permanent(question_id: int, error_message: str) -> str:
    """PERMANENT failure (Judgment Day fix 2) — a non-already-answered 4xx
    from `post_answer` (401/403/404/422/etc). Marks the row `failed`
    immediately WITHOUT incrementing `attempts`: retrying a request ML has
    permanently rejected would never succeed, so the bounded retry budget
    must not be burned on it."""
    with get_background_db() as db:
        row = (
            db.query(MlBotQuestion)
            .filter(MlBotQuestion.id == question_id, MlBotQuestion.status == "publishing")
            .first()
        )
        if row is None:
            return "skipped_claimed_elsewhere"
        row.last_error = error_message[:2000]
        row.status = "failed"
    return "failed"


def _is_ml_question_answered(question: Dict[str, Any]) -> bool:
    """True if ML's `get_question` payload indicates the question already
    has an answer (used by the retry-verification check, Judgment Day fix
    1b)."""
    status = str(question.get("status") or "").upper()
    if status == "ANSWERED":
        return True
    return bool(question.get("answer"))


def _mark_failed_or_retry(question_id: int, error_message: str) -> str:
    """Transient failure -> bounded retry via `attempts`; past
    `_MAX_ATTEMPTS` the row becomes `failed` (panel-retryable, per design §2
    `failed -> {waiting|published}`).

    Reads the row's CURRENT `attempts` from the DB itself (same short
    session as the write), same discipline as drafting_service's D2
    Judgment Day fix — never trust a caller-captured value.

    Returns "retry" or "failed" for the caller's stats dict.
    """
    with get_background_db() as db:
        row = (
            db.query(MlBotQuestion)
            .filter(MlBotQuestion.id == question_id, MlBotQuestion.status == "publishing")
            .first()
        )
        if row is None:
            return "skipped_claimed_elsewhere"
        new_attempts = row.attempts + 1
        row.attempts = new_attempts
        row.last_error = error_message[:2000]
        if new_attempts >= _MAX_ATTEMPTS:
            row.status = "failed"
            return "failed"
        row.status = "waiting"
        return "retry"


async def _publish_one(question_id: int) -> str:
    """Orchestrate a single claimed row's publish attempt. Returns an
    outcome key for the caller's stats dict.

    Every failure path (claimed elsewhere, load failure, POST failure,
    unexpected error) is routed to a terminal or retry write so a row is
    never left stuck in `publishing` (mirrors drafting_service's per-row
    error handling contract)."""
    if not _claim_for_publishing(question_id):
        return "skipped_claimed_elsewhere"

    try:
        question = _load_question(question_id)
        if question is None:
            return "skipped_claimed_elsewhere"

        # Judgment Day fix 1b: a RETRY (attempts > 0) may already have
        # posted successfully to ML before a crash prevented the terminal
        # DB write. Verify independently via `get_question` BEFORE
        # re-posting — never post blind on a retry.
        if question["attempts"] > 0:
            try:
                verification = await ml_client.get_question(question["ml_question_id"])
            except QuestionNotFoundError:
                # Terminal-but-ambiguous: play it safe, do not post blind.
                verification = None

            if verification is None:
                # Transient GET failure — do not post, leave for next
                # retry WITHOUT burning the attempts budget.
                _revert_to_waiting_without_penalty(question_id)
                return "retry"

            if _is_ml_question_answered(verification):
                logger.info(
                    "ml-bot publisher: question %s already answered on ML, marking published without re-posting",
                    question_id,
                )
                _mark_published(question_id)
                return "published"

        try:
            # ML POST happens here — no DB session is open at this point.
            result = await ml_client.post_answer(question["ml_question_id"], question["drafted_answer"])
        except QuestionAlreadyAnsweredError:
            logger.info(
                "ml-bot publisher: question %s was already answered in ML — treating as published",
                question_id,
            )
            _mark_published(question_id)
            return "published"
        except AnswerPostPermanentError as exc:
            logger.warning(
                "ml-bot publisher: question %s permanently rejected by ML (HTTP %s) — marking failed without retry: %s",
                question_id,
                exc.status_code,
                exc.message,
            )
            return _mark_failed_permanent(
                question_id, f"ML post_answer permanent error (HTTP {exc.status_code}): {exc.message}"
            )

        if result is None:
            # `post_answer`'s own contract: None means a transient failure
            # (network/timeout/5xx) already logged there.
            return _mark_failed_or_retry(question_id, "ML post_answer failed (see logs for details)")

        _mark_published(question_id)
        return "published"

    except Exception as exc:  # noqa: BLE001 — must never crash the loop.
        logger.error("ml-bot publisher: unexpected error publishing question %s: %s", question_id, exc, exc_info=True)
        return _mark_failed_or_retry(question_id, str(exc))


async def run_ml_questions_publish_cycle() -> Dict[str, Any]:
    """One publish tick: reclaim stale claims -> select due rows -> claim
    and publish each.

    Never raises — every per-row failure is caught and routed to a
    retry/failed terminal write inside `_publish_one`; this function only
    aggregates stats for the caller's background-task loop (mirrors
    `run_ml_questions_draft_cycle`'s resilience contract).

    ml_client.post_answer itself never raises for transient failures (it
    returns None per its own contract) — the try/except here exists for
    QuestionAlreadyAnsweredError and any genuinely unexpected error (e.g. a
    bug in this module), not for ordinary network failures.
    """
    stats: Dict[str, Any] = {
        "published": 0,
        "retry": 0,
        "failed": 0,
        "skipped_claimed_elsewhere": 0,
    }

    now = datetime.now(timezone.utc)
    _reclaim_stale_publishing_claims(now)

    due_ids = _fetch_due_ids(now)

    for question_id in due_ids:
        try:
            outcome = await _publish_one(question_id)
        except Exception as exc:  # noqa: BLE001 — one bad row must not abort the batch.
            logger.error(
                "ml-bot publisher: unexpected error in tick for question %s: %s",
                question_id,
                exc,
                exc_info=True,
            )
            outcome = "failed"
        stats[outcome] = stats.get(outcome, 0) + 1

    return stats
