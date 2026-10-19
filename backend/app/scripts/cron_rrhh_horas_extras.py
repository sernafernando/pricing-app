"""
Manual run of the daily overtime (HE) detection.

The scheduled run lives in the worker: handler `rrhh.horas_extras` in the main `REGISTRY`
(`pricing-worker.service`), daily at 03:30 Argentina time. This script is only a thin wrapper over the
same shared run (`app.services.rrhh_horas_extras_diario.run_daily_detection`), useful to re-run one
day by hand.

Cron entry: NONE. Do NOT add this script to any crontab; the worker already runs it every day, and a
crontab entry would only duplicate it.

What a run does:
  - Checks `RRHHHorasExtrasConfig.cron_activo` (also the worker's switch); when off, exits 3 without
    touching anything.
  - Detects HE for the day (default: yesterday in `ART_TZ`, from `rrhh_hikvision_client`) and commits.
    Idempotent: editable blocks are recomputed, frozen blocks are kept.
  - Purges old read alerts (`dias_retencion_alertas`). A purge failure does not change the exit code:
    the detection is already committed.
  - The detection runs under the shared HE detection lock, a Postgres advisory lock taken in the same
    transaction as the writes (`rrhh_horas_extras_diario.try_detection_lock`), also taken by the worker
    and `/recalcular`, so no two runs overlap. A manual run never moves the worker's day cursor.

Exit codes:
  0 -- OK (detection and purge done, or detection done with a failed purge)
  1 -- lock held (another run in progress: worker, script or /recalcular)
  2 -- detection failed (rolled back), or the lock could not be taken (database error)
  3 -- disabled by config (cron_activo=false)

Usage:
    cd /var/www/html/pricing-app/backend
    python -m app.scripts.cron_rrhh_horas_extras                     # yesterday
    python -m app.scripts.cron_rrhh_horas_extras --fecha 2026-05-05  # one given day
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

if __name__ == "__main__":
    backend_path = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    if backend_path not in sys.path:
        sys.path.insert(0, backend_path)

    from dotenv import load_dotenv

    env_path = Path(backend_path) / ".env"
    load_dotenv(dotenv_path=env_path)


import argparse  # noqa: E402
from datetime import UTC, date, datetime  # noqa: E402

from app.core.logging import get_logger  # noqa: E402
from app.services.rrhh_horas_extras_diario import (  # noqa: E402
    STATUS_DETECTION_FAILED,
    STATUS_DISABLED,
    STATUS_LOCK_UNAVAILABLE,
    STATUS_LOCKED,
    previous_local_day,
    run_daily_detection,
)

logger = get_logger("scripts.cron_rrhh_horas_extras")


_EXIT_CODES = {STATUS_LOCKED: 1, STATUS_DETECTION_FAILED: 2, STATUS_LOCK_UNAVAILABLE: 2, STATUS_DISABLED: 3}


def main(argv: list[str] | None = None) -> int:
    """Entry point. Returns the exit code (0=OK, 1=lock, 2=detection failed, 3=disabled)."""
    parser = argparse.ArgumentParser(description="Manual run of the daily HE detection")
    parser.add_argument("--fecha", type=date.fromisoformat, help="day to process (YYYY-MM-DD); default: yesterday")
    args = parser.parse_args(argv)
    day = args.fecha or previous_local_day(datetime.now(UTC))

    outcome = run_daily_detection([day])
    if outcome.status == STATUS_DISABLED:
        logger.warning("HE detection disabled by config (cron_activo=false); nothing done")
    elif outcome.status == STATUS_LOCKED:
        logger.warning("Another HE detection run holds the lock; nothing done")
    elif outcome.status == STATUS_LOCK_UNAVAILABLE:
        logger.error("HE detection not run: %s", outcome.error)
    return _EXIT_CODES.get(outcome.status, 0)


if __name__ == "__main__":
    sys.exit(main())
