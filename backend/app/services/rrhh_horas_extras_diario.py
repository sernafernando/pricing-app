"""The daily overtime (HE) run: detect one day for every active employee, then purge old read alerts.

Shared by the worker handler `rrhh.horas_extras` (the scheduled path, 03:30 Argentina time) and the
manual script `app.scripts.cron_rrhh_horas_extras` (to re-run a day by hand). Gated by
`RRHHHorasExtrasConfig.cron_activo`. Each step uses its own short session, so a failed purge never
rolls back a detection that was already committed.
"""

from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import date, datetime, timedelta

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
    A detection failure is returned as `detection_failed` and skips the purge; a purge failure is
    reported in `purge_error` and keeps the detection.
    """
    sessions = session_factory or database.get_background_db

    with sessions() as db:
        if not _cron_activo(db):
            # debug only: the worker re-checks this on every pass while the switch is off
            logger.debug("HE detection disabled by config (cron_activo=false)")
            return DailyRunResult(day=day, status=STATUS_DISABLED)

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
