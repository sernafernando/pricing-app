"""
Centralized logging configuration for the Pricing API.

Usage:
    from app.core.logging import get_logger

    logger = get_logger(__name__)
    logger.info("Something happened", extra={"order_id": 123})

All app loggers inherit from the root "app" logger, ensuring consistent
format and level across the entire backend.
"""

import logging
import sys

from app.core.config import settings

LOG_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
LOG_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

_configured = False


def setup_logging() -> None:
    """
    Configure root app logger once.

    - Development: DEBUG level, human-readable format to stdout.
    - Production:  INFO level, same format (swap to JSON handler later if needed).
    """
    global _configured
    if _configured:
        return

    level = logging.DEBUG if settings.ENVIRONMENT == "development" else logging.INFO

    formatter = logging.Formatter(fmt=LOG_FORMAT, datefmt=LOG_DATE_FORMAT)

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)

    root_logger = logging.getLogger("app")
    root_logger.setLevel(level)
    root_logger.addHandler(handler)
    # Prevent duplicate logs if uvicorn also propagates
    root_logger.propagate = False

    _configured = True


def get_logger(name: str) -> logging.Logger:
    """
    Return a child logger under the 'app' namespace.

    Guarantees setup_logging() has been called at least once.
    """
    setup_logging()
    return logging.getLogger(f"app.{name}")
