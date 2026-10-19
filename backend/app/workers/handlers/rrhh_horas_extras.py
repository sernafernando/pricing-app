"""`rrhh.horas_extras`: the daily overtime (HE) detection, scheduled by the worker. No cron.

Daily slot at 03:30 Argentina time (`scheduling.ARGENTINA_TZ`): between the 02:00 and 04:00 cycles of
the Hikvision punch sync and before the working day starts. A run processes the previous Argentina day
and then purges old read alerts (`services.rrhh_horas_extras_diario`); `RRHHHorasExtrasConfig.cron_activo`
stays the on/off switch.

The worker runs its handlers one at a time, so two scheduled runs never overlap; the run still takes
the shared HE detection flock (`rrhh_horas_extras_diario.detection_lock`) so it never overlaps a manual
script run or a `POST /rrhh/horas-extras/recalcular` either.

Outcomes, read by `scheduling.is_due` through `success`:
  - disabled: `success=False` with `{"disabled": True}`, so the job stays due and turning the switch
    on runs it on the next pass instead of tomorrow (same shape as the ML handlers' `disabled_outcome`);
  - another run holds the lock: `success=False` with `{"skipped": "locked"}`;
  - the lock cannot be opened (e.g. its directory is not writable): `success=False` with the error;
  - detection failed: `success=False` with the error;
  - after any of those three the job stays due, and this handler waits `RETRY_DELAY` before trying
    again instead of re-running on every pass;
  - otherwise `success=True` with the day, the detection counts and the purge result (or its error).
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import UTC, datetime, time, timedelta

from app.services import rrhh_horas_extras_diario as diario
from app.workers.context import JobResult, WorkerContext

logger = logging.getLogger(__name__)

RETRY_DELAY = timedelta(minutes=15)


class RRHHHorasExtrasHandler:
    """`JobHandler` for `rrhh.horas_extras`."""

    name = "rrhh.horas_extras"
    channels: tuple[str, ...] = ()
    interval: timedelta | None = None
    run_at_local: time | None = time(3, 30)

    def __init__(
        self,
        *,
        session_factory: diario.SessionFactory | None = None,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._now = now or (lambda: datetime.now(UTC))
        self._retry_at: datetime | None = None
        self._last_error: str | None = None

    def run(self, ctx: WorkerContext) -> JobResult:
        now = self._now()
        if self._retry_at is not None and now < self._retry_at:
            return JobResult(success=False, detail={"retry_at": self._retry_at.isoformat()}, error=self._last_error)

        day = diario.previous_local_day(now)
        outcome = diario.run_daily_detection(day, session_factory=self._session_factory)

        if outcome.status == diario.STATUS_DISABLED:
            return JobResult(success=False, detail={"disabled": True})
        if outcome.status != diario.STATUS_OK:
            self._retry_at = now + RETRY_DELAY
            self._last_error = outcome.error
            if outcome.status == diario.STATUS_LOCKED:
                return JobResult(success=False, detail={"skipped": "locked"})
            return JobResult(
                success=False, detail={"day": day.isoformat(), "error": outcome.error}, error=outcome.error
            )

        self._retry_at = None
        self._last_error = None
        detail = {"day": day.isoformat(), "detection": outcome.detection}
        if outcome.purge_error is not None:
            detail["purge_error"] = outcome.purge_error
        else:
            detail["purge"] = outcome.purge
        logger.info("rrhh.horas_extras: %s", detail)
        return JobResult(success=True, detail=detail)


horas_extras = RRHHHorasExtrasHandler()
