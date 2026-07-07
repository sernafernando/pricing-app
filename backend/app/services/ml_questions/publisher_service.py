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
   - Other failure -> bounded retry: back to `waiting` under
     `_MAX_ATTEMPTS` claims, else `failed` with `last_error`.
5. Stale-claim reclaim: any row still `publishing` past
   `_PUBLISHING_STALE_MINUTES` (measured off `updated_at`) is CAS-reverted
   to `waiting` at the start of every cycle — covers the SIGKILL-between-
   claim-and-terminal-write case, same pattern as drafting's
   `_reclaim_stale_drafting_claims`.

Counter semantics (Judgment Day round 2, fix 1 — REDESIGNED): `attempts`
counts CLAIMS, not POST failures. It is incremented atomically INSIDE the
`_claim_for_publishing` CAS UPDATE itself (`attempts = attempts + 1` in the
same `values()` as the `waiting -> publishing` transition), so every single
time a row is claimed for a publish attempt — whether or not a POST ever
happens — the counter advances. This closes two holes in the previous
"increment only on POST failure" design:
- First-attempt-crash double-post: previously, a crash after a successful
  POST but before the terminal write left `attempts == 0`, so the next
  cycle's "first attempt" branch skipped verification and posted again
  blind. Now the very act of claiming bumps `attempts` to 1 on the first
  claim; a reclaimed row that gets claimed AGAIN is already at `attempts
  >= 2`, so the verification-before-repost gate (`attempts > 1`) fires
  correctly and detects the already-answered question via `get_question`
  before ever re-posting.
- Unbounded verify-revert livelock: previously, a transient `get_question`
  verification failure reverted the row to `waiting` WITHOUT touching
  `attempts`, so a persistently-unreachable ML API could loop forever
  reverting the same row. Now the claim counter itself bounds the loop —
  after `_MAX_ATTEMPTS` claims (regardless of what happened inside each
  claim), a row claimed at the limit is not claimed again: `_fetch_due_ids`
  routes it to `failed` ("publish attempts exhausted") instead.
`_mark_failed_or_retry` no longer increments `attempts` (the claim already
did) — it only reads the current value to decide retry vs `failed`.

`attempts` is a PER-STAGE counter (Judgment Day round 3 fix): drafting
counts drafting retries; this module counts publish claims, always starting
from 0 — `drafting_service.py`'s `_resolve_success`/`_resolve_fallback`
reset `attempts = 0` on every transition INTO `waiting`, so a row's publish
claim count here is never inflated by leftover drafting retries.

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

SSE emission scope (Judgment Day adjudication): intermediate retry/revert
transitions where `status` stays `waiting` (`_revert_to_waiting`, the
retry branch of `_mark_failed_or_retry`) intentionally do NOT emit the
`ml_bot:questions` reload hint — they are internal pipeline retries, not a
panel-visible state change. Emission is TERMINAL-STATES-ONLY
(`published`, `failed`) plus panel mutations in `routers/ml_bot.py`.
`drafting_service.py` follows the same rule for its own retry-to-`received`
branch in `_mark_failed_or_retry`.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import func, update

from app.core.database import get_background_db
from app.core.sse import sse_publish_bg
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


def _fetch_due_ids(now: datetime) -> tuple[List[int], int]:
    """Rows due for publication: `waiting` and past `wait_until`. Excludes
    `taken_over`/`pending_morning`/anything else by construction — human
    takeover always wins the race (design §8 point 2).

    A row already at `attempts >= _MAX_ATTEMPTS` (claim counter, Judgment Day
    round 2 fix 1) is NOT returned for claiming — it is transitioned straight
    to `failed` here instead, so the claim-counter bound on the retry loop
    is enforced even if nothing ever calls `_claim_for_publishing` on it
    again.

    Returns `(due_ids, exhausted_count)` so the caller can fold the
    exhausted rows into its stats even though they never go through
    `_publish_one`.
    """
    with get_background_db() as db:
        rows = (
            db.query(MlBotQuestion)
            .filter(MlBotQuestion.status == "waiting", MlBotQuestion.wait_until <= now)
            .order_by(MlBotQuestion.wait_until.asc())
            .limit(_BATCH_LIMIT)
            .all()
        )
        due_ids: List[int] = []
        exhausted_count = 0
        for row in rows:
            if row.attempts >= _MAX_ATTEMPTS:
                row.status = "failed"
                row.last_error = "publish attempts exhausted"
                exhausted_count += 1
            else:
                due_ids.append(row.id)
        return due_ids, exhausted_count


def _claim_for_publishing(question_id: int) -> bool:
    """CAS transition `waiting -> publishing`, incrementing `attempts`
    ATOMICALLY in the same UPDATE (Judgment Day round 2 fix 1: `attempts`
    counts CLAIMS, not POST failures). Returns True only if THIS call won
    the claim (guards concurrent publish-cycle ticks)."""
    with get_background_db() as db:
        result = db.execute(
            update(MlBotQuestion)
            .where(MlBotQuestion.id == question_id, MlBotQuestion.status == "waiting")
            .values(status="publishing", updated_at=func.now(), attempts=MlBotQuestion.attempts + 1)
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
    sse_publish_bg("ml_bot:questions", {"hint": "reload"})


def _revert_to_waiting(question_id: int) -> None:
    """CAS-revert a claimed row back to `waiting` — used when a
    retry-verification `get_question` call fails transiently (Judgment Day
    round 1 fix 1b). `attempts` is intentionally left untouched here: under
    the redesigned claim-counted semantics (Judgment Day round 2 fix 1) the
    penalty for this attempt was ALREADY applied atomically by
    `_claim_for_publishing`'s CAS increment — the claim counter itself is
    what bounds the retry loop, not this revert."""
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
    sse_publish_bg("ml_bot:questions", {"hint": "reload"})
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

    Judgment Day round 2 fix 1: `attempts` is no longer incremented HERE —
    `_claim_for_publishing`'s CAS UPDATE already counted this attempt when
    the row was claimed. This function only reads the row's CURRENT
    `attempts` (fresh from the DB, same short session as the write) to
    decide retry vs `failed`.

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
        row.last_error = error_message[:2000]
        if row.attempts >= _MAX_ATTEMPTS:
            row.status = "failed"
            is_failed = True
        else:
            row.status = "waiting"
            is_failed = False
    if is_failed:
        sse_publish_bg("ml_bot:questions", {"hint": "reload"})
        return "failed"
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

        # Judgment Day round 2 fix 1: `attempts` now counts CLAIMS (bumped
        # atomically by `_claim_for_publishing`), so `attempts == 1` means
        # THIS is the first-ever claim on this row — safe to POST directly,
        # no wasted GET. `attempts > 1` means this row has been claimed
        # before (a prior claim may have posted successfully to ML before a
        # crash prevented the terminal DB write) — verify independently via
        # `get_question` BEFORE re-posting, never post blind.
        if question["attempts"] > 1:
            try:
                verification = await ml_client.get_question(question["ml_question_id"])
            except QuestionNotFoundError:
                # ML confirms the question no longer exists — terminal,
                # not retryable. Fail immediately rather than looping.
                logger.warning(
                    "ml-bot publisher: question %s not found in ML during retry verification — marking failed",
                    question_id,
                )
                return _mark_failed_permanent(
                    question_id, "ML question not found during retry verification (404) — treating as terminal"
                )

            if verification is None:
                # Transient GET failure — do not post, leave for next
                # retry. The claim counter (already incremented on THIS
                # claim) is what bounds the loop, not this revert.
                _revert_to_waiting(question_id)
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


async def publish_question_now(question_id: int) -> str:
    """Public wrapper around `_publish_one` (Slice F, design §9: "Publish-now
    endpoint reuses `publisher_service.publish_one()` so the wait-loop and
    manual path share identical ML-post + idempotency code").

    The router is responsible for CAS-transitioning the row into `waiting`
    (with `wait_until` set to now) BEFORE calling this function; the
    `attempts` reset is source-state-dependent, not unconditionally 0: a
    fresh source (`waiting`/`taken_over`/`pending_morning`) resets to 0
    (fresh publish budget), while a `failed` source resets to 1 so the next
    claim's bump lands on 2 and forces `_publish_one`'s verify-before-repost
    gate (blind-repost prevention) — see `routers/ml_bot.py`'s module
    docstring for the full rationale. This function only performs the
    claim + POST + terminal-write pipeline exactly as the background
    publish cycle does.
    """
    return await _publish_one(question_id)


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

    due_ids, exhausted_count = _fetch_due_ids(now)
    stats["failed"] += exhausted_count

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
