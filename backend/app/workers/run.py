"""Entrypoint: `python -m app.workers.run` (design D4). Run under systemd
unit `pricing-worker.service` (`deploy/systemd/pricing-worker.service`),
NEVER cron. PR2 ships the registry empty -- this process idles, LISTENing
(or safety-polling) harmlessly until PR3+ register real handlers.
"""

from __future__ import annotations

import logging
import signal
import sys
from types import FrameType
from typing import Optional

from app.core.config import settings
from app.workers.runtime import WorkerRuntime

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
)
logger = logging.getLogger(__name__)


def main() -> None:
    runtime = WorkerRuntime(
        worker_name="worker",
        safety_poll_interval=settings.WORKER_SAFETY_POLL_INTERVAL_SECONDS,
        heartbeat_interval=settings.WORKER_HEARTBEAT_INTERVAL_SECONDS,
    )

    def _handle_signal(signum: int, _frame: Optional[FrameType]) -> None:
        logger.info("received signal %s -- stopping worker loop", signum)
        runtime.stop()

    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    logger.info("starting pricing-worker (listener_mode=%s)", runtime.listener_mode)
    runtime.run_forever()
    logger.info("pricing-worker stopped cleanly")


if __name__ == "__main__":  # pragma: no cover -- exercised as a subprocess in ops, not unit tests
    main()
    sys.exit(0)
