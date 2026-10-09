"""Poison-row engine of the general billing `/details` sweep (BS-7).

ML intermittently answers a page with a bare 400 and, when a row is the cause,
every page containing it. Halting the period on it would starve the rest, so
the engine narrows the 400 down to the row, records a gap and steps over it.

`from_id` is exclusive and `detail_id` is numeric and ascending, so for a read
at `from_id=X, limit=1` that still fails the poison row is the next one after
`X`, and a probe at `from_id=X+s` finds how far it is:

1. retry the request once (the 400s are intermittent);
2. halve `limit` at the same `X` down to 1; a success is a good page;
3. probe `from_id=X+s, limit=1` for s = 1, 2, 4, ...; the first success at
   `s_hi` brackets the poison id in `(X+s_lo, X+s_hi]`; a binary search finds the
   smallest successful `s*`; every probe is retried once on a bare 400, so one
   spurious 400 cannot move the bracket past good rows;
4. record the gap at `X+s*` and resume at `from_id=X+s*`.

The window recorded is `(X, X+s*]`, not just the last id. The probe only proves
that the row at `X+s*` is poison; when there are several poison rows, a sparse
probe can jump over good rows between them, so the window is the honest
statement of what was stepped over. For the same reason a gap closes only when
a page that STARTS at or before the window start returns the position: such a
page is contiguous and ascending, so it holds the whole window.

Only a BARE 400 is narrowed down. A 429, a 5xx, a timeout or a 400 that names a
cause stops the read without a gap: the caller retries it later. The probe stops
at `POISON_PROBE_BOUND`; reaching it with only 400s records the whole window
`(X, X+bound]` and resumes there, so a 400 that is not about a row never loops.
That gap's position is a bound, not a row, so it never closes by itself: it
stays open for a person to look at.

`fetch(from_id, limit) -> BillingFetch` is injected, so the pacing between
requests (15 s per call) belongs to the caller and tests never sleep. The
engine writes only through the gaps store; the caller commits.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Callable, Iterable, Optional

from sqlalchemy.orm import Session

from app.services.ml_billing.poison_probe import POISON_PROBE_BOUND, NARROW, Step, advance, new_probe, next_request
from app.services.ml_billing.sweep_gaps import open_gaps, record_gap, resolve_gap
from app.services.ml_webhook_client import BillingFetch

_PAGING = "from_id"
_SOURCE = "general"

Fetch = Callable[[int, int], BillingFetch]


@dataclass(frozen=True)
class PageRead:
    """What one read produced. Exactly one of three shapes:

    - `page` set: the page read at `from_id` (a good page, or the one right
      after a skipped poison row). An empty `results` ends the pass.
    - `failure` set: a failure that is not a poison row; stop and retry later.
    - neither: the window up to `from_id` was recorded as a gap; resume there.
    """

    from_id: int
    page: Optional[dict] = None
    failure: Optional[BillingFetch] = None
    gaps: tuple[int, ...] = ()


def narrow_bare_400(fetch: Fetch, position: int, limit: int) -> BillingFetch:
    """Reads at `position` retrying a bare 400 once, then halving `limit` down to
    1 (each verdict retried once, so a spurious 400 never becomes a phantom gap).
    Shared with the offset engine. A result that is still a bare 400 means the
    row at `position` itself is the one ML refuses."""
    result = fetch(position, limit)
    if result.is_bare_400:
        result = fetch(position, limit)
    size = limit
    while result.is_bare_400 and size > 1:
        size //= 2
        result = fetch(position, size)
        if size == 1 and result.is_bare_400:  # a phantom gap needs this last verdict to be real
            result = fetch(position, size)
    return result


def record_probe_gap(
    db: Session,
    step: Step,
    *,
    period_key: str,
    document_type: str,
    now: datetime,
    lap_id: Optional[str] = None,
) -> None:
    """Records the gap a `gap` step isolated. Shared by the synchronous reader and
    the billing lap. The caller commits."""
    error = step.error or {}
    record_gap(
        db,
        period_key=period_key,
        document_type=document_type,
        billing_source=_SOURCE,
        paging=_PAGING,
        position=str(step.position),
        window=step.window,
        http_status=error.get("status"),
        error=json.dumps(error.get("body")),
        now=now,
        lap_id=lap_id,
    )


def read_page_skipping_poison(
    db: Session,
    *,
    fetch: Fetch,
    period_key: str,
    document_type: str,
    from_id: int,
    limit: int,
    now: datetime,
    lap_id: Optional[str] = None,
    probe_bound: int = POISON_PROBE_BOUND,
) -> PageRead:
    """The whole probe in one call (the billing lap drives the same machine one
    request per tick)."""
    probe, hi_body = new_probe(from_id, limit, probe_bound), None
    while True:
        result = fetch(*next_request(probe))
        searching = probe["phase"] != NARROW
        step = advance(probe, result)
        if result.ok and searching:
            hi_body = result.body  # the last good probe is the one right after the poison row
        if step.kind == "next":
            continue
        if step.kind == "page":
            return PageRead(from_id=from_id, page=step.page)
        if step.kind == "failure":
            return PageRead(from_id=from_id, failure=step.failure)
        record_probe_gap(db, step, period_key=period_key, document_type=document_type, now=now, lap_id=lap_id)
        bounded = step.position - from_id >= probe_bound
        return PageRead(from_id=step.position, page=None if bounded else hi_body, gaps=(step.position,))


def _window_start(window: Optional[str]) -> Optional[int]:
    """`(a, b]` -> a; None for a window this engine did not write."""
    try:
        return int(window.strip("(]").split(",")[0])
    except (AttributeError, ValueError):
        return None


def resolve_recovered_gaps(
    db: Session,
    *,
    period_key: str,
    document_type: str,
    detail_ids: Iterable[int | str],
    read_from_id: int,
    now: datetime,
) -> int:
    """Resolves the open gaps whose position is among the rows a page returned
    and whose whole window that page covered (`read_from_id` <= window start).

    Returns how many were resolved. The caller commits."""
    returned = {str(detail_id) for detail_id in detail_ids}
    resolved = 0
    # Open gaps per period are few; each resolve is one targeted write.
    for gap in open_gaps(db, period_key, document_type):
        if gap.paging != _PAGING or gap.billing_source != _SOURCE or gap.position not in returned:
            continue
        start = _window_start(gap.window)
        if start is None or read_from_id > start:
            continue
        resolved += resolve_gap(
            db,
            period_key=period_key,
            document_type=document_type,
            billing_source=_SOURCE,
            paging=_PAGING,
            position=gap.position,
            now=now,
        )
    return resolved
