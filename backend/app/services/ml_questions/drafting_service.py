"""
Drafting orchestration service for the ML questions bot (Slice D2).

Implements design §6 (LLM pipeline stages 1-7) + §7's "success" hand-off
into `waiting`, wired against the policy/context_builder/llm_provider
modules built in Slices B/D1. This module does NOT publish anything to
ML — that is Slice E's `publisher_service.py`. It only takes a `received`
row all the way to `waiting` / `pending_morning` / `failed`.

Pipeline per question (design §6):
1. Claim: CAS UPDATE `received -> drafting` (guards concurrent draft ticks).
2. Eligibility gate (`policy.is_eligible_for_bot`) is checked BEFORE the
   claim, at the batch level — ineligible questions are left untouched in
   `received` for humans (no state transition at all, per R-201 scenario 1).
3. Manipulation-signal detector (R-503): a match skips the LLM call
   entirely and routes straight to fallback, with `injection_flag=True`.
4. Otherwise: build a `ScopedContext` (short DB session), assemble the
   prompt, call the provider OUTSIDE any DB session (ADR-5), parse the
   closed-schema output, then run the denylist validator (R-502) on the
   answer.
5. Decision: can_answer + confidence>=min_confidence + clean denylist ->
   success (`waiting`, answer_source=bot). Anything else (including a
   provider/parse failure) -> fallback.
6. Fallback routing (R-601/R-602): normally routes to the warm business-
   hours message, still queued through `waiting` so a human can intercept
   it; EXCEPT the repeat-buyer-after-midnight case, which goes to
   `pending_morning` with no auto-publish wait window.
7. Unexpected errors (bugs, DB errors, etc.) never leave a row stuck in
   `drafting` — they increment `attempts` and either put the row back in
   `received` for a retry or, past `_MAX_ATTEMPTS`, mark it `failed`. This is
   an addition to design §2's state table: `drafting -> received` (bounded
   retry, under `_MAX_ATTEMPTS`) alongside the documented
   `drafting -> {waiting | pending_morning | failed}`. A stale-claim reclaim
   (rows still `drafting` past `_DRAFTING_STALE_MINUTES`) also reverts to
   `received` at the start of every cycle, covering the SIGKILL-between-
   claim-and-terminal-write case.

Session discipline (ADR-5, QueuePool-incident regression guard): every DB
read/write is its own short `get_background_db()` block. The Groq HTTP call
in stage 4 NEVER happens while a DB session from this module is open.

`attempts` is a PER-STAGE counter (Judgment Day round 3 fix): in this module
it counts DRAFTING retries (`_mark_failed_or_retry`, bounded by
`_MAX_ATTEMPTS`). `publisher_service.py` reuses the SAME `attempts` column as
its own claim counter, so every write that transitions a row INTO `waiting`
(`_resolve_success`, `_resolve_fallback`) resets `attempts = 0` in the same
UPDATE — otherwise leftover drafting retries would silently shrink the
publisher's retry budget and misfire its `attempts > 1` re-post-verification
gate on a row's first-ever publish claim.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import update

from app.core.database import get_background_db
from app.core.sse import sse_publish_bg
from app.models.ml_bot_question import MlBotQuestion
from app.services.ml_api_client import ml_client
from app.services.ml_questions import answer_shaping, context_builder, policy
from app.services.ml_questions.llm_provider import LlmProvider, LlmProviderError, parse_llm_output
from app.services.ml_questions.provider_rotation import RotatingProvider

logger = logging.getLogger(__name__)

_BATCH_LIMIT = 20
_MAX_ATTEMPTS = 3

# Judgment Day fix: rows CAS-claimed into `drafting` (design §6 stage 1) that
# never reach a terminal write (SIGKILL between claim and terminal write, or a
# DB error immediately after the claim) would otherwise stay stuck forever —
# nothing else ever re-selects `drafting` rows. Any row still `drafting` after
# this many minutes (measured off `updated_at`, the only timestamp the model
# maintains) is CAS-reverted to `received` at the start of each cycle so a
# later tick retries it.
_DRAFTING_STALE_MINUTES = 15

# Statuses that count as "the buyer's prior question was already handled by
# the bot" for the R-602 repeat-buyer-after-midnight exception. Deliberately
# excludes `received`/`drafting`/`failed` (not yet resolved) and
# `pending_morning` (that one is explicitly NOT auto-answered).
_HANDLED_STATUSES = frozenset({"waiting", "published", "taken_over"})

_LLM_DEBUG_LOGGING_KEY = "llm_debug_logging"

_DEFAULT_MIN_CONFIDENCE = 0.6
_DEFAULT_TIMEZONE = "America/Argentina/Buenos_Aires"
_DEFAULT_BUSINESS_HOURS_START = "09:00"
_DEFAULT_BUSINESS_HOURS_END = "18:00"
_DEFAULT_FALLBACK_TEMPLATE = (
    "¡Hola! Gracias por tu consulta. Nuestro horario de atención es de "
    "{business_hours_start} a {business_hours_end}. Te respondemos apenas "
    "abramos. ¡Gracias por tu paciencia!"
)

# Placeholder resolved at fallback-render time (schedules-v2) from the
# `attention_hours_text` config key — kept separate from `.format()`'s
# {business_hours_start}/{business_hours_end} substitution below so an
# absent/empty config value can be cleanly removed instead of crashing or
# rendering the literal "{attention_hours}" text.
_ATTENTION_HOURS_PLACEHOLDER = "{attention_hours}"
# Strips whitespace on BOTH sides of the placeholder so removal never
# leaves a lone leading/trailing space behind, regardless of which side of
# the template it sits on (e.g. "es {attention_hours}." -> "es." and
# "Texto   {attention_hours}   fin" -> "Texto fin" after the space-run
# collapse below).
_ATTENTION_HOURS_PLACEHOLDER_RE = re.compile(r" *\{attention_hours\} *")
# Collapses runs of the space character (NOT newlines, so intentional
# line breaks in a panel-edited template survive cleanup).
_SPACE_RUN_RE = re.compile(r" {2,}")
# A leftover space directly before closing punctuation reads as a typo
# once the placeholder is gone (e.g. "Horario ." -> "Horario.").
_SPACE_BEFORE_PUNCT_RE = re.compile(r" ([.,;:!?)])")


def _resolve_provider_label(provider: LlmProvider) -> Optional[str]:
    """Item #2 (PR de pulido): "provider/model" label for the LLM that
    produced a draft, stored in `ml_bot_questions.llm_provider`.

    `RotatingProvider` (the real default) tracks the roster entry that
    actually answered on `last_used_provider`; any other `LlmProvider`
    implementation (tests, future single-provider callers) falls back to a
    plain `name` attribute if present, else `None` (column stays nullable)."""
    last_used = getattr(provider, "last_used_provider", None)
    if last_used:
        return last_used
    name = getattr(provider, "name", None)
    return str(name) if name else None


def _log_llm_debug(
    question_id: int,
    system_prompt: str,
    user_payload: str,
    provider: LlmProvider,
    *,
    raw: Optional[str],
    parsed: Any,
    error: Optional[str],
) -> None:
    """Item #1 (PR de pulido): opt-in, grepable full-prompt/response logging
    for debugging drafting quality. Gated by the `llm_debug_logging`
    `ml_bot_config` key (default off) — when off, this function is never
    called and zero new log lines are emitted. INFO level, prefixed
    "ml-bot llm-debug" so it's trivially greppable and separable from the
    normal WARNING/ERROR operational logs."""
    outcome = error if error is not None else (
        f"can_answer={parsed.can_answer} confidence={parsed.confidence} "
        f"category={parsed.category!r} denylist_hit={policy.violates_denylist(parsed.answer)}"
        if parsed is not None
        else "unknown"
    )
    logger.info(
        "ml-bot llm-debug question=%s provider=%s system_prompt=%r user_payload=%r raw_response=%r outcome=%s",
        question_id,
        _resolve_provider_label(provider),
        system_prompt,
        user_payload,
        raw,
        outcome,
    )


def _build_default_provider() -> LlmProvider:
    """Build the default `LlmProvider` for a cycle (ADR-6).

    Provider-rotation follow-up (sdd/ml-questions-ai/provider-rotation):
    returns a `RotatingProvider`, which resolves the panel-editable roster
    (`llm_providers`) + rotation cursor (`llm_rotation_cursor`) fresh on
    EVERY `.complete()` call — i.e. rotation/failover happens per question,
    not once per cycle, even though this factory itself is only called once
    per cycle by `run_ml_questions_draft_cycle`. When `llm_providers` is
    unset, the roster fails safe to a single Groq entry honoring the legacy
    `llm_model` config key, preserving the pre-rotation Slice D2 behavior.
    """
    return RotatingProvider()


def _build_fallback_message(db: Any) -> str:
    """R-601: the warm business-hours fallback message, templated from live
    `ml_bot_config` values (never hardcoded, so a panel edit applies on the
    next tick)."""
    template = policy.get_config(db, "warm_fallback_template", cast=str, default=_DEFAULT_FALLBACK_TEMPLATE)
    start = policy.get_config(db, "business_hours_start", cast=str, default=_DEFAULT_BUSINESS_HOURS_START)
    end = policy.get_config(db, "business_hours_end", cast=str, default=_DEFAULT_BUSINESS_HOURS_END)

    # schedules-v2: resolve the free-text {attention_hours} placeholder BEFORE
    # `.format()` (a plain string replace, not a format field) so an
    # absent/empty `attention_hours_text` config value is cleanly removed
    # rather than crashing `.format()` on an unsupplied kwarg or rendering
    # the literal placeholder text.
    attention_hours = policy.get_config(db, "attention_hours_text", cast=str, default="")
    if attention_hours:
        # Judgment Day fix: the substituted value is free admin-editable text
        # that flows into `.format()` right after — an unbalanced brace in it
        # (e.g. "de 9 a 18 {promo") would otherwise raise inside `.format()`
        # below, escaping the local except and sending the whole question to
        # `failed` instead of the graceful raw-template fallback path.
        escaped = attention_hours.replace("{", "{{").replace("}", "}}")
        template = template.replace(_ATTENTION_HOURS_PLACEHOLDER, escaped)
    else:
        # Judgment Day fix (round 2): strip the placeholder AND whitespace on
        # BOTH sides, reinsert a single space so words on either side don't
        # collide ("Texto {attention_hours} fin" -> "Texto fin", not
        # "Textofin"), then collapse any remaining space runs and fix
        # space-before-punctuation artifacts. Newlines are deliberately left
        # untouched (only the space character is collapsed) so intentional
        # line breaks in a panel-edited template survive cleanup. A
        # placeholder immediately abutting a colon (e.g. "Horario:
        # {attention_hours}.") can still leave a documented "Horario:."
        # artifact — admins are expected to write self-contained clauses
        # around the placeholder (see module docstring / runbook).
        template = _ATTENTION_HOURS_PLACEHOLDER_RE.sub(" ", template)
        template = _SPACE_RUN_RE.sub(" ", template)
        template = _SPACE_BEFORE_PUNCT_RE.sub(r"\1", template)
        template = template.strip()

    try:
        return template.format(business_hours_start=start, business_hours_end=end)
    except (KeyError, IndexError, ValueError):
        # A custom panel-edited template with unexpected placeholders (or
        # residual unbalanced braces from free text) must never crash the
        # pipeline — fall back to the raw template text.
        return template


def _is_repeat_buyer_after_midnight(
    db: Any, buyer_id: Optional[int], question_id: int, question_date: datetime
) -> bool:
    """R-602 exception check.

    Documented interpretation: "arrives after 00:00 local time" is read as
    the early-morning portion of the nightly off-hours window — local
    time-of-day in `[00:00, business_hours_start)` — which distinguishes a
    just-past-midnight follow-up from an evening (pre-midnight) question.
    Combined with: the same buyer already has at least one OTHER
    `ml_bot_questions` row that reached a handled state (`waiting`,
    `published`, `taken_over`) with an earlier `question_date` (R-602
    scenario 3: "handled", not only "fallback", counts).

    A missing `buyer_id` (anonymous/unavailable) never qualifies — fails
    toward the safer default (normal fallback, not `pending_morning`), same
    direction as `policy.is_within_business_hours`'s fail-safe convention.
    """
    if buyer_id is None:
        return False

    tz_name = policy.get_config(db, "timezone", cast=str, default=_DEFAULT_TIMEZONE)
    try:
        tz = ZoneInfo(tz_name)
    except ZoneInfoNotFoundError:
        return False

    localized = question_date.astimezone(tz) if question_date.tzinfo else question_date.replace(tzinfo=tz)

    # schedules-v2: today's opening time is sourced per-day (work_schedule if
    # valid, else the legacy business_days + business_hours_start/end keys).
    # A `question_date` landing on a day that isn't itself a working day has
    # no "before opening" concept to check against — fails toward the safer
    # normal-fallback default, same direction as a missing buyer_id above.
    today_times = policy.get_business_hours_for_day(db, localized.isoweekday())
    if today_times is None:
        return False
    start_hour, start_minute, _end_hour, _end_minute = today_times

    if not ((0, 0) <= (localized.hour, localized.minute) < (start_hour, start_minute)):
        return False

    # Judgment Day fix (R-602), generalized for per-day schedules
    # (schedules-v2): bound the prior-question lookup to the CURRENT
    # off-hours window instead of "ever" — an unbounded lookup makes ANY
    # historical handled question trigger `pending_morning` forever for that
    # buyer. The current off-hours window started at the END of the MOST
    # RECENT WORKING DAY before now (not simply "yesterday" — with a
    # per-day schedule, e.g. Mon-Fri 09-18 + Sat 09-13, the working-day end
    # before a Sunday/Monday early morning is Saturday 13:00). Anything
    # before that boundary belongs to a previous cycle.
    window_start = policy.resolve_last_working_day_end(db, question_date)
    if window_start is None:
        return False

    prior = (
        db.query(MlBotQuestion)
        .filter(
            MlBotQuestion.buyer_id == buyer_id,
            MlBotQuestion.id != question_id,
            MlBotQuestion.status.in_(_HANDLED_STATUSES),
            MlBotQuestion.question_date < question_date,
            MlBotQuestion.question_date >= window_start,
        )
        .first()
    )
    return prior is not None


def _emit_reload_hint() -> None:
    """Fire the `ml_bot:questions` reload-hint SSE event (ADR-8). `sse_publish_bg`
    is documented never-raise, but this defensive guard ensures a future
    refactor there can never take down a drafting-pipeline state transition
    that already committed its DB write."""
    try:
        sse_publish_bg("ml_bot:questions", {"hint": "reload"})
    except Exception:  # noqa: BLE001 — SSE is best-effort, must never break the pipeline.
        logger.warning("ml-bot drafting: sse_publish_bg raised while emitting reload hint", exc_info=True)


def _resolve_fallback(
    question_id: int,
    buyer_id: Optional[int],
    question_date: datetime,
    *,
    injection_flag: bool,
) -> None:
    """R-601/R-602: finalize a question that could not be (or must not be)
    answered by the LLM. Chooses between the warm auto-publish fallback and
    the repeat-buyer-after-midnight `pending_morning` hold."""
    with get_background_db() as db:
        row = (
            db.query(MlBotQuestion).filter(MlBotQuestion.id == question_id, MlBotQuestion.status == "drafting").first()
        )
        if row is None:
            return

        if _is_repeat_buyer_after_midnight(db, buyer_id, question_id, question_date):
            row.status = "pending_morning"
            row.injection_flag = row.injection_flag or injection_flag
            # Judgment Day fix: emit AFTER the `with` block closes (mirrors
            # every other call site in this module and
            # `publisher_service`'s is_failed-flag pattern) instead of while
            # the session is still open.
        else:
            wait_minutes = policy.resolve_wait_minutes(db, datetime.now(timezone.utc))
            row.status = "waiting"
            row.drafted_answer = _build_fallback_message(db)
            row.answer_source = "fallback"
            row.fallback_used = True
            row.injection_flag = row.injection_flag or injection_flag
            row.wait_until = datetime.now(timezone.utc) + timedelta(minutes=wait_minutes)
            # Judgment Day fix (round 3): `attempts` is a PER-STAGE counter —
            # drafting counts drafting retries (`_mark_failed_or_retry`), but
            # the publisher reuses the SAME column as its claim counter
            # (`_claim_for_publishing`). Without resetting here, a row that
            # burned 1-2 drafting retries would enter `waiting` with a
            # non-zero `attempts`, silently shrinking its publish retry
            # budget and tripping the publisher's `attempts > 1` re-post-
            # verification gate on what is actually its FIRST publish claim.
            # Reset on every transition INTO `waiting` so the publisher
            # always starts from 0.
            row.attempts = 0
    _emit_reload_hint()


def _resolve_success(
    question_id: int,
    answer: str,
    confidence: float,
    category: str,
    official_store_id: Optional[int],
    provider_label: Optional[str] = None,
) -> None:
    """Successful bot answer (design §6 stage 7 happy path) -> `waiting`.

    Answer-shaping (sdd/ml-questions-ai/answer-shaping): the closing
    greeting + company signature are appended HERE, deterministically, on
    top of the raw LLM answer — never inside the LLM call itself — and the
    FULL assembled text is what gets stored in `drafted_answer` (what the
    operator sees/approves in the panel is exactly what ships)."""
    with get_background_db() as db:
        row = (
            db.query(MlBotQuestion).filter(MlBotQuestion.id == question_id, MlBotQuestion.status == "drafting").first()
        )
        if row is None:
            return
        wait_minutes = policy.resolve_wait_minutes(db, datetime.now(timezone.utc))
        closing = answer_shaping.resolve_closing_text(db)
        signature = answer_shaping.resolve_signature(db, official_store_id)
        final_answer = answer_shaping.assemble_final_answer(answer, closing, signature)
        # Judgment Day fix (observability): `official_store_id` drives which
        # signature path is used, but it comes from ML's item payload — if
        # ML ever renames/drops the field, `extract_official_store_id` fails
        # safe to `None` SILENTLY (default-signature path). Log the resolved
        # id + path so a real-world field absence/rename is visible in logs
        # instead of a silent all-None degradation.
        signature_path = "none" if official_store_id is None else "per-store"
        logger.info(
            "ml-bot drafting: question %s official_store_id=%r signature_path=%s",
            question_id,
            official_store_id,
            signature_path,
        )
        row.status = "waiting"
        row.drafted_answer = final_answer
        row.confidence = confidence
        row.category = category
        row.answer_source = "bot"
        row.llm_provider = provider_label
        row.wait_until = datetime.now(timezone.utc) + timedelta(minutes=wait_minutes)
        # Judgment Day fix (round 3): see `_resolve_fallback` — reset the
        # per-stage `attempts` counter on every `drafting -> waiting`
        # transition so the publisher's claim-counter budget starts fresh.
        row.attempts = 0
    _emit_reload_hint()


def _mark_failed_or_retry(question_id: int, error_message: str) -> None:
    """Unexpected-error path: never leave a row stuck in `drafting`. Bounded
    retries via `attempts`; past `_MAX_ATTEMPTS` the row becomes `failed`
    (panel-retryable, per design §2 `failed -> {waiting|published}`).

    Judgment Day fix (round 2): reads the row's CURRENT `attempts` from the
    DB itself (same short session as the write) instead of trusting a
    caller-captured value. When `_load_question` raises before it can read
    `attempts`, the caller only ever has a stale `0` — writing `attempts=1`
    from that would silently reset a row already at e.g. 2, defeating the
    bounded retry during sustained DB flakiness.
    """
    with get_background_db() as db:
        row = (
            db.query(MlBotQuestion).filter(MlBotQuestion.id == question_id, MlBotQuestion.status == "drafting").first()
        )
        if row is None:
            return
        new_attempts = row.attempts + 1
        row.attempts = new_attempts
        row.last_error = error_message[:2000]
        is_failed = new_attempts >= _MAX_ATTEMPTS
        row.status = "failed" if is_failed else "received"
    if is_failed:
        # Judgment Day fix: only the terminal FAILED transition emits — the
        # bounded retry-to-`received` branch is an internal pipeline detail,
        # not a panel-visible state change, mirroring
        # `publisher_service._mark_failed_or_retry`'s is_failed-flag pattern
        # (emit-after-`with`-block, terminal-states-only).
        _emit_reload_hint()


def _claim_for_drafting(question_id: int) -> bool:
    """CAS transition `received -> drafting`. Returns True only if THIS call
    won the claim (guards concurrent draft-cycle ticks, design §6 stage 1)."""
    with get_background_db() as db:
        result = db.execute(
            update(MlBotQuestion)
            .where(MlBotQuestion.id == question_id, MlBotQuestion.status == "received")
            .values(status="drafting")
        )
        return result.rowcount == 1


def _load_question(question_id: int) -> Optional[Dict[str, Any]]:
    """Read the claimed row's plain data (short session) — nothing ORM-bound
    is held across the LLM call downstream (ADR-5)."""
    with get_background_db() as db:
        row = db.query(MlBotQuestion).filter(MlBotQuestion.id == question_id).first()
        if row is None:
            return None
        return {
            "id": row.id,
            "item_id": row.item_id,
            "buyer_id": row.buyer_id,
            "question_text": row.question_text,
            "question_date": row.question_date,
            "attempts": row.attempts,
        }


async def _draft_one(question_id: int, provider: LlmProvider) -> str:
    """Orchestrate a single claimed question through stages 2-7. Returns an
    outcome key for the caller's stats dict.

    Judgment Day fix: everything that happens AFTER a successful claim (the
    load included) is inside the same error handling that routes to
    `_mark_failed_or_retry` — a DB error while loading the just-claimed row
    must never leave it stuck in `drafting` any more than a provider error
    downstream would.
    """
    if not _claim_for_drafting(question_id):
        return "skipped_claimed_elsewhere"

    try:
        question = _load_question(question_id)
        if question is None:
            return "skipped_claimed_elsewhere"

        if policy.detect_manipulation_signal(question["question_text"]):
            # R-503: manipulation signal -> fallback WITHOUT any LLM call.
            _resolve_fallback(question_id, question["buyer_id"], question["question_date"], injection_flag=True)
            return "injection_flagged"

        item_payload = await ml_client.get_item(question["item_id"])
        # context-enrichment (sdd/ml-questions-ai/context-enrichment): the
        # item description is fetched here, OUTSIDE any DB session (ADR-5),
        # same as `get_item` above. `get_item_description` never raises —
        # a fetch failure (404, transient error, unexpected payload) yields
        # `None`, and the draft proceeds without a description.
        description = await ml_client.get_item_description(question["item_id"])

        with get_background_db() as db:
            context = context_builder.build_scoped_context(db, question["question_text"], item_payload, description)
            min_confidence = policy.get_config(db, "min_confidence", cast=float, default=_DEFAULT_MIN_CONFIDENCE)
            answer_max_chars = answer_shaping.get_answer_max_chars(db)
            debug_logging = policy.get_config(db, _LLM_DEBUG_LOGGING_KEY, cast=bool, default=False) or False

        system_prompt, user_payload = context_builder.build_prompt(context, answer_max_chars)

        try:
            # Groq call happens here — no DB session is open at this point.
            raw = await provider.complete(system_prompt, user_payload)
            parsed = parse_llm_output(raw, max_chars=answer_max_chars)
        except LlmProviderError as exc:
            if debug_logging:
                _log_llm_debug(
                    question_id, system_prompt, user_payload, provider, raw=None, parsed=None, error=str(exc)
                )
            logger.warning("ml-bot drafting: provider/parse failure for question %s: %s", question_id, exc)
            _resolve_fallback(question_id, question["buyer_id"], question["question_date"], injection_flag=False)
            return "fallback"

        if debug_logging:
            _log_llm_debug(question_id, system_prompt, user_payload, provider, raw=raw, parsed=parsed, error=None)

        if not parsed.can_answer or parsed.confidence < min_confidence or policy.violates_denylist(parsed.answer):
            denylist_hit = policy.violates_denylist(parsed.answer)
            _resolve_fallback(question_id, question["buyer_id"], question["question_date"], injection_flag=denylist_hit)
            return "fallback"

        _resolve_success(
            question_id,
            parsed.answer,
            parsed.confidence,
            parsed.category,
            context.official_store_id,
            provider_label=_resolve_provider_label(provider),
        )
        return "drafted"

    except Exception as exc:  # noqa: BLE001 — must never crash the loop.
        logger.error("ml-bot drafting: unexpected error drafting question %s: %s", question_id, exc, exc_info=True)
        _mark_failed_or_retry(question_id, str(exc))
        return "failed"


def _reclaim_stale_drafting_claims(now: datetime) -> int:
    """Judgment Day fix: CAS-revert any row still `drafting` past
    `_DRAFTING_STALE_MINUTES` back to `received` so it gets retried on a
    later tick, instead of staying stuck forever (see module docstring).

    Adjudicated invariant (round 2): this reclaim is safe ONLY because the
    draft cycle runs strictly sequentially in a single worker (the `fcntl`
    lock in `main.py`) — a stalled provider call blocks the whole loop, so a
    row that is still `drafting` past the staleness window can only belong
    to a dead/crashed process, never a concurrently-running one. If the
    cycle is ever invoked concurrently (e.g. an admin "run now" endpoint, or
    multiple workers), the terminal writes in this module (`_resolve_*`,
    `_mark_failed_or_retry`) would need an ownership/lease token to avoid
    two processes racing on the same claimed row.
    """
    threshold = now - timedelta(minutes=_DRAFTING_STALE_MINUTES)
    with get_background_db() as db:
        result = db.execute(
            update(MlBotQuestion)
            .where(MlBotQuestion.status == "drafting", MlBotQuestion.updated_at < threshold)
            .values(status="received")
        )
        reclaimed = result.rowcount

    if reclaimed:
        logger.warning(
            "ml-bot drafting: reclaimed %d stale 'drafting' row(s) older than %d minutes",
            reclaimed,
            _DRAFTING_STALE_MINUTES,
        )
    return reclaimed


def _fetch_pending_ids(now: datetime) -> Optional[List[int]]:
    """Batch-level eligibility gate (R-201): if the bot isn't eligible right
    now (disabled, or in-hours under `off_hours_only`), the whole tick is a
    no-op — `received` rows are left untouched for humans. Returns None when
    not eligible, else the list of candidate ids ordered oldest-first."""
    with get_background_db() as db:
        if not policy.is_eligible_for_bot(db, now):
            return None
        return [
            row.id
            for row in db.query(MlBotQuestion)
            .filter(MlBotQuestion.status == "received")
            .order_by(MlBotQuestion.question_date.asc())
            .limit(_BATCH_LIMIT)
            .all()
        ]


async def run_ml_questions_draft_cycle(provider: Optional[LlmProvider] = None) -> Dict[str, Any]:
    """One drafting tick: gate -> claim+draft each eligible `received` row.

    Never raises — every per-question failure is caught and routed to
    fallback/failed inside `_draft_one`; this function only aggregates
    stats for the caller's background-task loop (mirrors
    `run_ml_questions_ingest_cycle`'s resilience contract).
    """
    stats: Dict[str, Any] = {
        "drafted": 0,
        "fallback": 0,
        "injection_flagged": 0,
        "failed": 0,
        "skipped_claimed_elsewhere": 0,
        "not_eligible": False,
    }

    now = datetime.now(timezone.utc)
    _reclaim_stale_drafting_claims(now)

    pending_ids = _fetch_pending_ids(now)
    if pending_ids is None:
        stats["not_eligible"] = True
        return stats

    active_provider = provider or _build_default_provider()

    for question_id in pending_ids:
        try:
            outcome = await _draft_one(question_id, active_provider)
        except Exception as exc:  # noqa: BLE001 — one bad row must not abort the batch.
            logger.error(
                "ml-bot drafting: unexpected error in tick for question %s: %s",
                question_id,
                exc,
                exc_info=True,
            )
            outcome = "failed"
        stats[outcome] = stats.get(outcome, 0) + 1

    return stats
