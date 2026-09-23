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

# Tables `compute_order_metrics` legitimately reads that are NOT metrics
# inputs -- reading them cannot change any stored metric, so they need no
# enqueue trigger. Every entry here must be justified by pointing at the
# actual query and why it cannot affect the formula; this is NOT a place to
# silence the guard.
#
# - "logisticas" (`Logistica.nombre`): read via `EtiquetaEnvio.logistica`
#   (`lazy="joined"`, `breakdown_service._resolve_flex_cost_by_shipping_id`)
#   ONLY to format the Flex `concepto` label shown alongside the cost. The
#   cost itself resolves off `logistica_id` against `logistica_costo_cordon`
#   -- renaming a logistics company changes no stored metric.
NON_INPUT_READ_TABLES = frozenset({"logisticas"})

# Every table `compute_order_metrics` may read without the guard raising:
# real trigger inputs, plus the justified non-input reads above. This is
# DELIBERATELY NOT the same object as `TRIGGERED_TABLES` -- see
# `assert_read_set_is_triggered`'s docstring for why aliasing the two here
# once made this guard a silent no-op (a real regression, PR5 review G1).
KNOWN_INPUT_TABLES = TRIGGERED_TABLES | NON_INPUT_READ_TABLES

_TABLE_REF_RE = re.compile(r"\b(?:FROM|JOIN)\s+\"?(\w+)\"?", re.IGNORECASE)


class UntriggeredReadError(AssertionError):
    """`compute_order_metrics` read a table with no enqueue trigger covering
    it yet (design D3 "Structural guard")."""


@contextmanager
def assert_read_set_is_triggered(engine: Engine) -> Iterator[Set[str]]:
    """Wrap the `compute_order_metrics` call under test in this context
    manager. Raises `UntriggeredReadError` on exit if any captured table
    read is NOT explained by either `TRIGGERED_TABLES` (a real metrics
    input, covered by an enqueue trigger) or `NON_INPUT_READ_TABLES` (a
    justified read that cannot affect the formula).

    This FAILS CLOSED on purpose: a table read that is in NEITHER set is
    always a bug report, never a silent pass -- either it is a new metrics
    input that needs a trigger (extend `TRIGGERED_TABLES`, and ship the
    trigger), or a new non-input read that needs its justification written
    down (extend `NON_INPUT_READ_TABLES`). `KNOWN_INPUT_TABLES` must never
    be made identical to `TRIGGERED_TABLES` again: that aliasing is exactly
    what made this guard a no-op in production (PR5 review G1) -- an
    untriggered table would also be absent from `KNOWN_INPUT_TABLES`, so
    `seen & KNOWN_INPUT_TABLES` could never see it."""
    seen: Set[str] = set()

    def _before_cursor_execute(conn, cursor, statement, parameters, context, executemany) -> None:
        for match in _TABLE_REF_RE.finditer(statement):
            seen.add(match.group(1).lower())

    event.listen(engine, "before_cursor_execute", _before_cursor_execute)
    try:
        yield seen
    finally:
        event.remove(engine, "before_cursor_execute", _before_cursor_execute)
        # FAIL on any read table that is in NEITHER set -- an unrecognised
        # table can be a widened read set (a real gap) OR a typo/missing
        # entry in `NON_INPUT_READ_TABLES`; either way it must be looked at
        # and explicitly classified, never silently allowed through.
        unexplained = seen - (TRIGGERED_TABLES | NON_INPUT_READ_TABLES)
        if unexplained:
            raise UntriggeredReadError(
                f"compute_order_metrics read {sorted(unexplained)} but no enqueue trigger "
                "covers it and it is not in NON_INPUT_READ_TABLES -- add it to TRIGGERED_TABLES "
                "(and ship its trigger) if it is a real metrics input, or to "
                "NON_INPUT_READ_TABLES with a written justification if it is not, before "
                "widening the read set, or stored metrics for orders depending on it can go "
                "stale with nothing to detect it (design D3)."
            )
