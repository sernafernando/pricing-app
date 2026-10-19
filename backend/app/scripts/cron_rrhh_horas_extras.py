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
  - Takes a non-blocking flock (`/var/run/pricing-app/rrhh_he_cron.lock`, fallback
    `/tmp/rrhh_he_cron.lock`) so two manual runs never overlap. The worker does not need it: it runs
    its handlers one at a time.

Exit codes:
  0 -- OK (detection and purge done, or detection done with a failed purge)
  1 -- lock held (another manual run in progress)
  2 -- detection failed (rolled back)
  3 -- disabled by config (cron_activo=false)

Usage:
    cd /var/www/html/pricing-app/backend
    python -m app.scripts.cron_rrhh_horas_extras                     # yesterday
    python -m app.scripts.cron_rrhh_horas_extras --fecha 2026-05-05  # one given day
"""

from __future__ import annotations

import os
import sys
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

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
    previous_local_day,
    run_daily_detection,
)

logger = get_logger("scripts.cron_rrhh_horas_extras")


LOCK_PATH_PRIMARY = Path(os.environ.get("RRHH_HE_CRON_LOCK_PRIMARY", "/var/run/pricing-app/rrhh_he_cron.lock"))
LOCK_PATH_FALLBACK = Path(os.environ.get("RRHH_HE_CRON_LOCK_FALLBACK", "/tmp/rrhh_he_cron.lock"))


@contextmanager
def _file_lock() -> Iterator[Path]:
    """Lockfile flock no-bloqueante.

    Intenta `LOCK_PATH_PRIMARY`; si su parent no existe ni se puede crear,
    cae a `LOCK_PATH_FALLBACK`. Si otro proceso ya tiene el lock, levanta
    `SystemExit(1)` SIN encolar.

    Yields:
        Path al lockfile efectivamente adquirido (para logging).
    """
    import fcntl

    # Elegir path: primario si su parent existe (o se puede crear), fallback si no.
    path = LOCK_PATH_PRIMARY
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
    except (OSError, PermissionError):
        path = LOCK_PATH_FALLBACK
        path.parent.mkdir(parents=True, exist_ok=True)

    fd = os.open(str(path), os.O_CREAT | os.O_RDWR, 0o644)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        os.close(fd)
        logger.warning("⚠️ Otra corrida del cron HE está activa (lockfile=%s). Aborta.", path)
        raise SystemExit(1)

    # Escribir PID para diagnóstico operacional.
    try:
        os.ftruncate(fd, 0)
        os.write(fd, f"{os.getpid()}\n".encode("utf-8"))
    except OSError:
        # Falla al escribir PID no es crítica — seguimos con el lock adquirido.
        pass

    try:
        yield path
    finally:
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
        except OSError:
            pass
        try:
            os.close(fd)
        except OSError:
            pass


_EXIT_CODES = {STATUS_DISABLED: 3, STATUS_DETECTION_FAILED: 2}


def main(argv: list[str] | None = None) -> int:
    """Entry point. Returns the exit code (0=OK, 1=lock, 2=detection failed, 3=disabled)."""
    parser = argparse.ArgumentParser(description="Manual run of the daily HE detection")
    parser.add_argument("--fecha", type=date.fromisoformat, help="day to process (YYYY-MM-DD); default: yesterday")
    args = parser.parse_args(argv)
    day = args.fecha or previous_local_day(datetime.now(UTC))

    try:
        with _file_lock() as lock_path:
            logger.info("Lock acquired at %s (pid=%s)", lock_path, os.getpid())
            outcome = run_daily_detection(day)
    except SystemExit as exc:
        # `_file_lock` raises SystemExit(1) when the lock is held.
        return exc.code if isinstance(exc.code, int) else 1

    if outcome.status == STATUS_DISABLED:
        logger.warning("HE detection disabled by config (cron_activo=false); nothing done")
    return _EXIT_CODES.get(outcome.status, 0)


if __name__ == "__main__":
    sys.exit(main())
