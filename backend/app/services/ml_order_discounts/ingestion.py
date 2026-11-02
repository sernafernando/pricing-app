"""One run of the per-sale discounts ingestion: `GET /orders/{order_id}/discounts` for the pending orders.

Stop rules, in the order they are checked:
- a persisted back-off still running (`ml_order_discounts_state.backoff_until`): no call at all;
- a 429 (the HTTP one or the body's own): the run stops and the back-off grows (60 s doubling per consecutive 429 run, capped at 1 h, never
  shorter than `Retry-After`), so a run of 429s spaces the runs out instead of retrying every interval;
- 401 / no token / not configured: the run stops as `blocked`, nothing is counted against the order;
- no HTTP answer (transport error) or the deadline: the run stops, nothing is counted against the order.
Any other answer is written: `ok`, `none` (ML's 404 "Discount not found") or `error`, which is asked again on
later runs until `store.MAX_ATTEMPTS`. The first answered call clears the back-off.

The ML call is made with no DB session open; each answer is written in its own short transaction.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Dict, Optional

from app.services.ml_ads.ingestion import BLOCKED, RATE_LIMITED, SessionFactory, blocking_outcome
from app.services.ml_order_discounts import mapper, store
from app.services.ml_publications.ml_http import MlHttpClient
from app.services.ml_publications.pacing import DEADLINE

FAMILY = "order_discounts"
BACKOFF = "backoff"
TRANSPORT = "transport"


@dataclass
class RunResult:
    calls: int = 0
    counts: Dict[str, int] = field(default_factory=lambda: {mapper.OK: 0, mapper.NONE: 0, mapper.ERROR: 0})
    stopped: Optional[str] = None
    backoff_until: Optional[datetime] = None
    pending_left: Optional[int] = None

    def as_detail(self) -> Dict[str, Any]:
        return {
            "calls": self.calls,
            "fetched": self.counts[mapper.OK],
            "none": self.counts[mapper.NONE],
            "errors": self.counts[mapper.ERROR],
            "stopped": self.stopped,
            "backoff_until": self.backoff_until and self.backoff_until.isoformat(),
            "pending_left": self.pending_left,
        }


def _retry_after(headers: Any) -> Optional[float]:
    try:
        return float(headers.get("retry-after"))
    except (AttributeError, TypeError, ValueError):
        return None  # absent, or an HTTP date: the doubling alone decides


def run(
    session_factory: SessionFactory,
    client: MlHttpClient,
    *,
    now: Callable[[], datetime],
    deadline: datetime,
    max_calls: int,
) -> RunResult:
    result = RunResult()
    with session_factory() as db:
        until = store.backoff_until(db)
        if until is not None and until > now():
            result.stopped, result.backoff_until = BACKOFF, until
            result.pending_left = store.pending_count(db)
            return result
        orders = store.pending_orders(db, max_calls)
    for order_id in orders:
        response = client.get(FAMILY, f"/orders/{order_id}/discounts", deadline=deadline)
        if response.error == DEADLINE:
            result.stopped = DEADLINE
            break
        result.calls += 1
        own_status = mapper.body_status(response.status, response.body)
        blocking = blocking_outcome(response)
        if blocking == RATE_LIMITED or own_status == 429:
            with session_factory() as db:
                _, result.backoff_until = store.record_429(db, now(), _retry_after(response.headers))
            result.stopped = RATE_LIMITED
            break
        if blocking == BLOCKED or own_status == 401:
            result.stopped = BLOCKED
            break
        if response.status == 0:
            result.stopped = TRANSPORT
            break
        status = mapper.classify(response.status, response.body)
        with session_factory() as db:
            if result.calls == 1:
                store.clear_backoff(db)
            store.write_fetch(db, order_id, status, own_status, response.body, now())
        result.counts[status] += 1
    with session_factory() as db:
        result.pending_left = store.pending_count(db)
    return result
