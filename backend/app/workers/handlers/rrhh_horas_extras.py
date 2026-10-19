"""`rrhh.horas_extras`: the daily overtime (HE) detection, scheduled by the worker. No cron.

Daily slot at 03:30 Argentina time (`scheduling.ARGENTINA_TZ`): between the 02:00 and 04:00 cycles of
the Hikvision punch sync and before the working day starts. `RRHHHorasExtrasConfig.cron_activo` stays
the on/off switch.

Days to process come from a cursor, `worker_job_state.detail.last_day_done` (merged into that JSONB,
never replacing it): every Argentina day from the cursor + 1 through yesterday, oldest first, at most
`MAX_DAYS_PER_RUN` per run. The first run ever (no cursor yet, switch on) seeds the cursor at the day
before yesterday in its own short transaction, so only yesterday runs: history before the first run is
never backfilled, yet a failed first day is still retried after midnight. Days missed later are caught
up from the cursor: turning `cron_activo` back on after some days off reprocesses those days, up to
`MAX_DAYS_PER_RUN` per run (idempotent; frozen blocks are kept). The cursor advances in
the same transaction as each day's detection, so a day that fails stays pending and is retried on the
next run, even when that run lands after midnight. Then old read alerts are purged
(`services.rrhh_horas_extras_diario`).

The worker runs its handlers one at a time, so two scheduled runs never overlap; each day still takes
the shared HE detection advisory lock (`rrhh_horas_extras_diario.try_detection_lock`) so it never
overlaps a manual script run or a `POST /rrhh/horas-extras/recalcular` either.

Outcomes, read by `scheduling.is_due` through `success`:
  - disabled: `success=False` with `{"disabled": True}`, so the job stays due and turning the switch
    on runs it on the next pass instead of tomorrow (same shape as the ML handlers' `disabled_outcome`);
  - another run holds the lock: `success=False` with `{"skipped": "locked"}`;
  - the lock cannot be taken (database error): `success=False` with the error;
  - a day's detection failed: `success=False` with the failed day and the error;
  - after any of those three the job stays due, and this handler waits `RETRY_DELAY` before trying
    again instead of re-running on every pass;
  - otherwise `success=True` with the days done, their detection counts and the purge result (or its
    error).
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from datetime import UTC, date, datetime, time, timedelta

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core import database
from app.models.worker_job_state import WorkerJobState
from app.services import rrhh_horas_extras_diario as diario
from app.workers.context import JobResult, WorkerContext

logger = logging.getLogger(__name__)

HANDLER_NAME = "rrhh.horas_extras"
CURSOR_KEY = "last_day_done"
MAX_DAYS_PER_RUN = 7
RETRY_DELAY = timedelta(minutes=15)


def _read_cursor(db: Session) -> date | None:
    row = db.get(WorkerJobState, HANDLER_NAME)
    value = (row.detail or {}).get(CURSOR_KEY) if row is not None else None
    return date.fromisoformat(value) if value else None


def _write_cursor(db: Session, day: date) -> None:
    """Merge `last_day_done` into `worker_job_state.detail`, keeping every other key."""
    if db.get_bind().dialect.name == "postgresql":
        db.execute(
            text(
                "INSERT INTO worker_job_state (name, detail) VALUES (:name, CAST(:detail AS jsonb)) "
                "ON CONFLICT (name) DO UPDATE SET "
                "detail = COALESCE(worker_job_state.detail, '{}'::jsonb) || EXCLUDED.detail"
            ),
            {"name": HANDLER_NAME, "detail": json.dumps({CURSOR_KEY: day.isoformat()})},
        )
        return
    # SQLite unit tests: no JSONB operators, a read-modify-write is enough there
    row = db.get(WorkerJobState, HANDLER_NAME)
    if row is None:
        db.add(WorkerJobState(name=HANDLER_NAME, detail={CURSOR_KEY: day.isoformat()}))
    else:
        row.detail = {**(row.detail or {}), CURSOR_KEY: day.isoformat()}
    db.flush()


def pending_days(cursor: date, yesterday: date) -> list[date]:
    """Days after `cursor` through `yesterday`, oldest first, at most `MAX_DAYS_PER_RUN`."""
    days: list[date] = []
    day = cursor + timedelta(days=1)
    while day <= yesterday and len(days) < MAX_DAYS_PER_RUN:
        days.append(day)
        day += timedelta(days=1)
    return days


class RRHHHorasExtrasHandler:
    """`JobHandler` for `rrhh.horas_extras`."""

    name = HANDLER_NAME
    channels: tuple[str, ...] = ()
    interval: timedelta | None = None
    run_at_local: time | None = time(3, 30)

    def __init__(
        self,
        *,
        session_factory: diario.SessionFactory | None = None,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._sessions = session_factory or database.get_background_db
        self._now = now or (lambda: datetime.now(UTC))
        self._retry_at: datetime | None = None
        self._last_error: str | None = None

    def run(self, ctx: WorkerContext) -> JobResult:
        now = self._now()
        if self._retry_at is not None and now < self._retry_at:
            return JobResult(success=False, detail={"retry_at": self._retry_at.isoformat()}, error=self._last_error)

        yesterday = diario.previous_local_day(now)
        try:
            with self._sessions() as db:
                if not diario.cron_activo(db):
                    return JobResult(success=False, detail={"disabled": True})
                cursor = _read_cursor(db)
            if cursor is None:
                # First run ever: pin the starting point, so a retry after midnight still finds this day.
                cursor = yesterday - timedelta(days=1)
                with self._sessions() as db:
                    _write_cursor(db, cursor)
                    db.commit()
        except Exception as exc:  # noqa: BLE001 -- same retry path as a failed detection
            logger.exception("rrhh.horas_extras: could not read or seed the cursor")
            return self._failed(now, {"days": []}, f"{type(exc).__name__}: {exc}"[:300])

        days = pending_days(cursor, yesterday)
        if not days:
            return JobResult(success=True, detail={"days": []})

        outcome = diario.run_daily_detection(days, session_factory=self._sessions, on_day_done=_write_cursor)
        done = [day.isoformat() for day in outcome.days_done]

        if outcome.status == diario.STATUS_DISABLED:
            return JobResult(success=False, detail={"disabled": True})
        if outcome.status == diario.STATUS_LOCKED:
            return self._failed(now, {"skipped": "locked", "days": done}, None)
        if outcome.status != diario.STATUS_OK:
            detail = {"days": done, "error": outcome.error}
            if outcome.failed_day is not None:
                detail = {"days": done, "failed_day": outcome.failed_day.isoformat(), "error": outcome.error}
            return self._failed(now, detail, outcome.error)

        self._retry_at = None
        self._last_error = None
        detail = {"days": done, "detections": outcome.detections}
        if outcome.purge_error is not None:
            detail["purge_error"] = outcome.purge_error
        elif done:
            detail["purge"] = outcome.purge
        logger.info("rrhh.horas_extras: %s", detail)
        return JobResult(success=True, detail=detail)

    def _failed(self, now: datetime, detail: dict[str, object], error: str | None) -> JobResult:
        """Not done: stay due, but wait `RETRY_DELAY` before the next try instead of every pass."""
        self._retry_at = now + RETRY_DELAY
        self._last_error = error
        return JobResult(success=False, detail=detail, error=error)


horas_extras = RRHHHorasExtrasHandler()
