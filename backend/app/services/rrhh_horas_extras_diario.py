"""The daily overtime (HE) run: detect one day for every active employee, then purge old read alerts.

Shared by the worker handler `rrhh.horas_extras` (the scheduled path, 03:30 Argentina time) and the
manual script `app.scripts.cron_rrhh_horas_extras` (to re-run a day by hand). Gated by
`RRHHHorasExtrasConfig.cron_activo`. Each step uses its own short session, so a failed purge never
rolls back a detection that was already committed.

`detection_lock()` is the one HE detection lock: a non-blocking `flock` that the worker run, the manual
script and `POST /rrhh/horas-extras/recalcular` all take, so none of them overlaps another (concurrent
recomputes of the same day would race on `uq_rrhh_he_emp_fecha_tipo`). Only a HELD lock counts: the
lockfile stays on disk after every run, and its existence alone means nothing.
"""

from __future__ import annotations

import fcntl
import os
from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager, contextmanager
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path

from sqlalchemy.orm import Session

from app.core import database
from app.core.logging import get_logger
from app.models.rrhh_horas_extras import RRHHHorasExtrasConfig
from app.services.rrhh_hikvision_client import ART_TZ
from app.services.rrhh_horas_extras_service import HorasExtrasService

logger = get_logger("services.rrhh_horas_extras_diario")

SessionFactory = Callable[[], AbstractContextManager[Session]]

STATUS_DISABLED = "disabled"
STATUS_OK = "ok"
STATUS_DETECTION_FAILED = "detection_failed"
STATUS_LOCKED = "locked"
STATUS_LOCK_UNAVAILABLE = "lock_unavailable"

# Same paths the script has always used, tried in order: the first one whose directory can be created
# and whose file can be opened wins. Every caller runs as the same user on the same host, so they all
# land on the same file. Read at call time, so tests can point it elsewhere.
LOCK_PATHS: tuple[Path, ...] = (
    Path(os.environ.get("RRHH_HE_CRON_LOCK_PRIMARY", "/var/run/pricing-app/rrhh_he_cron.lock")),
    Path(os.environ.get("RRHH_HE_CRON_LOCK_FALLBACK", "/tmp/rrhh_he_cron.lock")),
)


class DetectionLockUnavailable(RuntimeError):
    """No lock path could be opened: running without the lock could overlap another run, so callers fail."""


def _open_lock_file() -> int:
    problems: list[str] = []
    for path in LOCK_PATHS:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            return os.open(path, os.O_CREAT | os.O_RDWR, 0o644)
        except OSError as exc:
            problems.append(f"{path}: {exc.strerror or exc}")
    raise DetectionLockUnavailable("cannot open the HE detection lock (" + "; ".join(problems) + ")")


@contextmanager
def detection_lock() -> Iterator[bool]:
    """Take the HE detection lock without waiting. Yields True when acquired (released on exit), False
    when another run holds it. Raises `DetectionLockUnavailable` when no lock path can be opened."""
    fd = _open_lock_file()
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            yield False
            return
        try:
            yield True
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        os.close(fd)


@dataclass(frozen=True)
class DailyRunResult:
    day: date
    status: str
    detection: dict[str, int] | None = None
    purge: dict[str, int] | None = None
    purge_error: str | None = None
    error: str | None = None


def previous_local_day(now: datetime) -> date:
    """The day before `now` in Argentina time (explicit zone, independent of the server's)."""
    return now.astimezone(ART_TZ).date() - timedelta(days=1)


def _describe(exc: Exception) -> str:
    return f"{type(exc).__name__}: {exc}"[:300]


def _cron_activo(db: Session) -> bool:
    cfg = db.query(RRHHHorasExtrasConfig).filter(RRHHHorasExtrasConfig.id == 1).one_or_none()
    return cfg is not None and bool(cfg.cron_activo)


def run_daily_detection(day: date, *, session_factory: SessionFactory | None = None) -> DailyRunResult:
    """Detect HE for `day` (idempotent: editable blocks are recomputed, frozen ones kept), then purge.

    Returns `disabled` without touching anything when `cron_activo` is off or the config row is missing.
    Detection and purge run under `detection_lock()`: `locked` when another run holds it,
    `lock_unavailable` (with the error) when it cannot be opened. A detection failure is returned as
    `detection_failed` and skips the purge; a purge failure is reported in `purge_error` and keeps the
    detection.
    """
    sessions = session_factory or database.get_background_db

    with sessions() as db:
        if not _cron_activo(db):
            # debug only: the worker re-checks this on every pass while the switch is off
            logger.debug("HE detection disabled by config (cron_activo=false)")
            return DailyRunResult(day=day, status=STATUS_DISABLED)

    try:
        with detection_lock() as acquired:
            if not acquired:
                logger.info("HE detection for %s skipped: another run holds the lock", day)
                return DailyRunResult(day=day, status=STATUS_LOCKED)
            return _detect_and_purge(day, sessions)
    except DetectionLockUnavailable as exc:
        logger.error("HE detection for %s not run: %s", day, exc)
        return DailyRunResult(day=day, status=STATUS_LOCK_UNAVAILABLE, error=str(exc))


def _detect_and_purge(day: date, sessions: SessionFactory) -> DailyRunResult:
    logger.info("Starting HE detection for %s", day)
    try:
        with sessions() as db:
            detection = HorasExtrasService(db).detectar_he_periodo(day, day)
            db.commit()
    except Exception as exc:  # noqa: BLE001 -- reported to the caller, which decides the retry
        logger.exception("HE detection failed for %s", day)
        return DailyRunResult(day=day, status=STATUS_DETECTION_FAILED, error=_describe(exc))
    logger.info("HE detection done for %s: %s", day, detection)

    try:
        with sessions() as db:
            purge = HorasExtrasService(db).purgar_alertas_viejas()
    except Exception as exc:  # noqa: BLE001 -- the detection is already committed and stays
        logger.exception("HE alert purge failed (the detection for %s is kept)", day)
        return DailyRunResult(day=day, status=STATUS_OK, detection=detection, purge_error=_describe(exc))
    logger.info("HE alert purge: %s", purge)
    return DailyRunResult(day=day, status=STATUS_OK, detection=detection, purge=purge)
