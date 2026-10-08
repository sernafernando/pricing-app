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

from app.services.ml_billing.sweep_gaps import open_gaps, record_gap, resolve_gap
from app.services.ml_webhook_client import BillingFetch

POISON_PROBE_BOUND = 2**40
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
    result = fetch(from_id, limit)
    if result.is_bare_400:
        result = fetch(from_id, limit)
    size = limit
    while result.is_bare_400 and size > 1:
        size //= 2
        result = fetch(from_id, size)
    if result.ok:
        return PageRead(from_id=from_id, page=result.body)
    if not result.is_bare_400:
        return PageRead(from_id=from_id, failure=result)

    def record(position: int, window: str, error: BillingFetch) -> None:
        record_gap(
            db,
            period_key=period_key,
            document_type=document_type,
            billing_source=_SOURCE,
            paging=_PAGING,
            position=str(position),
            window=window,
            http_status=error.status,
            error=json.dumps(error.body),
            now=now,
            lap_id=lap_id,
        )

    def probe_at(step: int) -> BillingFetch:
        probe = fetch(from_id + step, 1)
        return fetch(from_id + step, 1) if probe.is_bare_400 else probe

    # Step over: the next row after `from_id` is the poison row.
    last_400, lo, hi, hi_body = result, 0, None, None
    step = 1
    while hi is None:
        if step > probe_bound:
            end = from_id + probe_bound
            record(end, f"({from_id}, {end}]", last_400)
            return PageRead(from_id=end, gaps=(end,))
        probe = probe_at(step)
        if probe.ok:
            hi, hi_body = step, probe.body
        elif probe.is_bare_400:
            last_400, lo, step = probe, step, step * 2
        else:
            return PageRead(from_id=from_id, failure=probe)
    while hi - lo > 1:
        mid = (lo + hi) // 2
        probe = probe_at(mid)
        if probe.ok:
            hi, hi_body = mid, probe.body
        elif probe.is_bare_400:
            last_400, lo = probe, mid
        else:
            return PageRead(from_id=from_id, failure=probe)
    poison = from_id + hi
    record(poison, f"({from_id}, {poison}]", last_400)
    return PageRead(from_id=poison, page=hi_body, gaps=(poison,))


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
