"""Entrypoint: `python -m app.workers.run` (design D4). Run under systemd
unit `pricing-worker.service` (`deploy/systemd/pricing-worker.service`),
NEVER cron. PR2 ships the registry empty -- this process idles, LISTENing
(or safety-polling) harmlessly until PR3+ register real handlers.

With no arguments this is exactly the original worker: default registry, worker name
`worker`. The ML publications store runs as a SECOND process of the same code
(`pricing-worker-ml.service`): `--registry ml_publications --worker-name worker-ml`,
so its paced ML calls never delay the sales drain.
"""

from __future__ import annotations

import argparse
import logging
import signal
import sys
from types import FrameType
from typing import List, Optional, Sequence

from app.core.config import settings
from app.workers import registry as registry_module
from app.workers.runtime import WorkerRuntime

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
)
logger = logging.getLogger(__name__)


DEFAULT_REGISTRY = "default"
ML_PUBLICATIONS_REGISTRY = "ml_publications"
DEFAULT_WORKER_NAME = "worker"
ML_PUBLICATIONS_WORKER_NAME = "worker-ml"


def _worker_name(value: str) -> str:
    if not value.strip():
        raise argparse.ArgumentTypeError("worker name must not be blank")
    return value.strip()


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="python -m app.workers.run", description="Pricing App job worker")
    parser.add_argument(
        "--registry",
        choices=[DEFAULT_REGISTRY, ML_PUBLICATIONS_REGISTRY],
        default=DEFAULT_REGISTRY,
        help="handler list to run (default: the original worker registry)",
    )
    parser.add_argument(
        "--worker-name",
        type=_worker_name,
        default=None,
        help="heartbeat row name (default: 'worker', or 'worker-ml' for the ml_publications registry)",
    )
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> None:
    args = parse_args(argv)
    handlers: Optional[List] = None  # None -> the runtime's own default (REGISTRY), unchanged
    default_name = DEFAULT_WORKER_NAME
    if args.registry == ML_PUBLICATIONS_REGISTRY:
        handlers = registry_module.ML_PUBLICATIONS_REGISTRY
        default_name = ML_PUBLICATIONS_WORKER_NAME
    worker_name = args.worker_name or default_name
    runtime = WorkerRuntime(
        registry=handlers,
        worker_name=worker_name,
        safety_poll_interval=settings.WORKER_SAFETY_POLL_INTERVAL_SECONDS,
        heartbeat_interval=settings.WORKER_HEARTBEAT_INTERVAL_SECONDS,
    )

    def _handle_signal(signum: int, _frame: Optional[FrameType]) -> None:
        logger.info("received signal %s -- stopping worker loop", signum)
        runtime.stop()

    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    logger.info("starting %s (registry=%s, listener_mode=%s)", worker_name, args.registry, runtime.listener_mode)
    runtime.run_forever()
    logger.info("%s stopped cleanly", worker_name)


if __name__ == "__main__":  # pragma: no cover -- exercised as a subprocess in ops, not unit tests
    main()
    sys.exit(0)
