"""The daily overtime (HE) run: detect days for every active employee, then purge old read alerts.

Shared by the worker handler `rrhh.horas_extras` (the scheduled path, 03:30 Argentina time) and the
manual script `app.scripts.cron_rrhh_horas_extras` (to re-run a day by hand). Gated by
`RRHHHorasExtrasConfig.cron_activo`. Each day uses its own short session, and the purge another, so a
failed purge never rolls back a detection that was already committed.

`try_detection_lock(db)` is the one HE detection lock: a Postgres transaction-scoped advisory lock that
the worker run, the manual script and `POST /rrhh/horas-extras/recalcular` all take in the same
transaction that writes the detection, so none of them overlaps another (concurrent recomputes of the
same day would race on `uq_rrhh_he_emp_fecha_tipo`). It lives in the database, so every process sees it
whatever its OS user or `/tmp`, and it is released exactly when those writes commit or roll back.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from contextlib import AbstractContextManager
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core import database
from app.core.logging import get_logger
from app.models.rrhh_horas_extras import RRHHHorasExtrasConfig
from app.services.rrhh_hikvision_client import ART_TZ
from app.services.rrhh_horas_extras_service import HorasExtrasService

logger = get_logger("services.rrhh_horas_extras_diario")

SessionFactory = Callable[[], AbstractContextManager[Session]]
DayDoneHook = Callable[[Session, date], None]

STATUS_DISABLED = "disabled"
STATUS_OK = "ok"
STATUS_DETECTION_FAILED = "detection_failed"
STATUS_LOCKED = "locked"
STATUS_LOCK_UNAVAILABLE = "lock_unavailable"

# Fixed advisory-lock key for HE detection ("RRHH HE" in ASCII); no other code in the app uses it.
DETECTION_LOCK_KEY = 0x5252_4848_2048_45


class DetectionLockUnavailable(RuntimeError):
    """The lock could not be taken (database error): running unlocked could overlap another run."""


def try_detection_lock(db: Session) -> bool:
    """Take the HE detection lock in `db`'s current transaction without waiting.

    True when acquired: it stays held until that transaction commits or rolls back. False when another
    session holds it. A database error raises `DetectionLockUnavailable`.

    On a non-Postgres dialect (the SQLite unit tests) there is no cross-process lock: it is a no-op that
    returns True.
    """
    if db.get_bind().dialect.name != "postgresql":
        return True
    try:
        acquired = db.execute(text("SELECT pg_try_advisory_xact_lock(:key)"), {"key": DETECTION_LOCK_KEY}).scalar()
    except SQLAlchemyError as exc:
        raise DetectionLockUnavailable(f"cannot take the HE detection lock: {_describe(exc)}") from exc
    return bool(acquired)


@dataclass(frozen=True)
class DailyRunResult:
    status: str
    days_done: tuple[date, ...] = ()
    detections: dict[str, dict[str, int]] = field(default_factory=dict)
    failed_day: date | None = None
    purge: dict[str, int] | None = None
    purge_error: str | None = None
    error: str | None = None


def previous_local_day(now: datetime) -> date:
    """The day before `now` in Argentina time (explicit zone, independent of the server's)."""
    return now.astimezone(ART_TZ).date() - timedelta(days=1)


def _describe(exc: Exception) -> str:
    return f"{type(exc).__name__}: {exc}"[:300]


def cron_activo(db: Session) -> bool:
    """The on/off switch `RRHHHorasExtrasConfig.cron_activo`; a missing config row counts as off."""
    cfg = db.query(RRHHHorasExtrasConfig).filter(RRHHHorasExtrasConfig.id == 1).one_or_none()
    return cfg is not None and bool(cfg.cron_activo)


class _Locked(Exception):
    pass


def run_daily_detection(
    days: Sequence[date],
    *,
    session_factory: SessionFactory | None = None,
    on_day_done: DayDoneHook | None = None,
) -> DailyRunResult:
    """Detect HE for each of `days` in order (idempotent: editable blocks are recomputed, frozen ones
    kept), then purge old read alerts.

    Returns `disabled` without touching anything when `cron_activo` is off or the config row is missing.
    Each day runs in one transaction: take the lock, detect, call `on_day_done(db, day)` (the worker
    advances its cursor there), commit. The run stops at the first day that cannot finish: `locked` when
    another run holds the lock, `lock_unavailable` when the lock cannot be taken, `detection_failed` when
    the detection raises; that day's transaction is rolled back and the days before it stay committed.
    The purge runs only after every day finished; its failure is reported in `purge_error` and keeps the
    detections.
    """
    sessions = session_factory or database.get_background_db

    with sessions() as db:
        if not cron_activo(db):
            # debug only: the worker re-checks this on every pass while the switch is off
            logger.debug("HE detection disabled by config (cron_activo=false)")
            return DailyRunResult(status=STATUS_DISABLED)

    done: list[date] = []
    detections: dict[str, dict[str, int]] = {}
    for day in days:
        try:
            with sessions() as db:
                if not try_detection_lock(db):
                    raise _Locked
                logger.info("Starting HE detection for %s", day)
                detection = HorasExtrasService(db).detectar_he_periodo(day, day, commit=False)
                if on_day_done is not None:
                    on_day_done(db, day)
                db.commit()  # the writes and the cursor commit together, and the lock is released here
        except _Locked:
            logger.info("HE detection for %s skipped: another run holds the lock", day)
            return DailyRunResult(status=STATUS_LOCKED, days_done=tuple(done), detections=detections)
        except DetectionLockUnavailable as exc:
            logger.error("HE detection for %s not run: %s", day, exc)
            return DailyRunResult(
                status=STATUS_LOCK_UNAVAILABLE, days_done=tuple(done), detections=detections, error=str(exc)
            )
        except Exception as exc:  # noqa: BLE001 -- reported to the caller, which decides the retry
            logger.exception("HE detection failed for %s", day)
            return DailyRunResult(
                status=STATUS_DETECTION_FAILED,
                days_done=tuple(done),
                detections=detections,
                failed_day=day,
                error=_describe(exc),
            )
        logger.info("HE detection done for %s: %s", day, detection)
        done.append(day)
        detections[day.isoformat()] = detection

    if not done:
        return DailyRunResult(status=STATUS_OK)
    try:
        with sessions() as db:
            purge = HorasExtrasService(db).purgar_alertas_viejas()
    except Exception as exc:  # noqa: BLE001 -- the detections are already committed and stay
        logger.exception("HE alert purge failed (the detections are kept)")
        return DailyRunResult(
            status=STATUS_OK, days_done=tuple(done), detections=detections, purge_error=_describe(exc)
        )
    logger.info("HE alert purge: %s", purge)
    return DailyRunResult(status=STATUS_OK, days_done=tuple(done), detections=detections, purge=purge)
