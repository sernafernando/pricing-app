"""Read-set guard (ventas-ml-rediseno PR4.T10/T11, design D3 "Structural
guard"). Instruments a SQLAlchemy engine's `before_cursor_execute` event
while `compute_order_metrics` runs and fails if it reads a table that has
no matching enqueue trigger yet -- the exact silent-staleness hazard the
design calls out: widening the read set without a trigger means stored
metrics go stale with nothing to detect it.

SQLite-safe: this is a regex over captured SQL text, not a Postgres
feature, so it runs in normal (non-`@pytest.mark.postgres`) CI against the
`db` fixture."""

from __future__ import annotations

import re
from contextlib import contextmanager
from typing import Iterator, Set

from sqlalchemy import event
from sqlalchemy.engine import Engine

from app.services.order_metrics.triggers import TRIGGERED_TABLES

# Every table that could plausibly feed the metrics formula, across every
# PR of this change -- PR4 ships per-order triggers on the first six (see
# `TRIGGERED_TABLES`); PR5 adds the statement-level config ones. A table
# entering `compute_order_metrics`'s read set with no matching entry here
# is a typo in THIS set, not a real gap -- extend it alongside the new
# trigger, never silently.
KNOWN_INPUT_TABLES = frozenset(
    TRIGGERED_TABLES
    | {
        "etiquetas_envio",
        "varios_venta_pct",
        "logistica_costo_cordon",
        "codigos_postales",
        "configuracion",
        "transportes",
    }
)

_TABLE_REF_RE = re.compile(r"\b(?:FROM|JOIN)\s+\"?(\w+)\"?", re.IGNORECASE)


class UntriggeredReadError(AssertionError):
    """`compute_order_metrics` read a table with no enqueue trigger covering
    it yet (design D3 "Structural guard")."""


@contextmanager
def assert_read_set_is_triggered(engine: Engine) -> Iterator[Set[str]]:
    """Wrap the `compute_order_metrics` call under test in this context
    manager. Raises `UntriggeredReadError` on exit if any captured table
    read is a known metrics input (`KNOWN_INPUT_TABLES`) but missing from
    `TRIGGERED_TABLES`."""
    seen: Set[str] = set()

    def _before_cursor_execute(conn, cursor, statement, parameters, context, executemany) -> None:
        for match in _TABLE_REF_RE.finditer(statement):
            seen.add(match.group(1).lower())

    event.listen(engine, "before_cursor_execute", _before_cursor_execute)
    try:
        yield seen
    finally:
        event.remove(engine, "before_cursor_execute", _before_cursor_execute)
        untriggered = (seen & KNOWN_INPUT_TABLES) - TRIGGERED_TABLES
        if untriggered:
            raise UntriggeredReadError(
                f"compute_order_metrics read {sorted(untriggered)} but no enqueue trigger "
                "covers it yet -- add it to TRIGGERED_TABLES (and ship its trigger) before "
                "widening the read set, or stored metrics for orders depending on it can go "
                "stale with nothing to detect it (design D3)."
            )
