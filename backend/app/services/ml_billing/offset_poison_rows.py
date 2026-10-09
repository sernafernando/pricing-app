"""Poison-offset engine of the flex billing `/details` sweep (BS-7, PR 4a-iv).

Flex details page by `offset` (limit 500) and ML answers an intermittent bare
400. Unlike `from_id`, a read at `offset=O, limit=1` returns exactly row O, so no
probing is needed: the poison offset is the one where a retried `limit=1` read
still fails (`poison_rows.narrow_bare_400` halves the limit at the same offset).

- a bare 400 is retried once, then the limit is halved at the same offset; a
  success is a good page (the prefix before the poison row) and the caller
  continues right after it;
- a `limit=1` read that still fails (retried) means the row at that offset is
  poison: the gap is recorded at exactly that offset, with the window `[O, O]`,
  and the read resumes at `O + 1`. Consecutive poison rows are found one by one,
  each with its own exact gap, because every verdict is a single-row read;
- only a BARE 400 is narrowed. A 429, a 5xx, a timeout or a 400 that names a
  cause stops the read without a gap.

A gap closes only when a page that covers its offset (`read_offset <= O <
read_offset + n_results`) returns clean: pages are contiguous, so such a page
holds the row. `total` drifts while a sweep runs (3324 -> 3325 in the capture),
so an offset names a position, not a row identity; the missing row keeps its
document incomplete through the completeness query, as for `from_id`.

`fetch(offset, limit) -> BillingFetch` is injected (pacing belongs to the caller).
The engine writes only through the gaps store; the caller commits. It is NOT
wired into any sweep yet (PR 5).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session

from app.services.ml_billing.poison_rows import Fetch, narrow_bare_400
from app.services.ml_billing.sweep_gaps import open_gaps, record_gap, resolve_gap
from app.services.ml_webhook_client import BillingFetch

_PAGING = "offset"
_SOURCE = "flex"


@dataclass(frozen=True)
class OffsetRead:
    """What one read produced. Exactly one of three shapes:

    - `page` set: the page read at `offset` (advance by `len(page["results"])`;
      an empty `results` ends the pass).
    - `failure` set: a failure that is not a poison row; stop and retry later.
    - neither: the poison offset was recorded; resume at `offset` (= poison + 1).
    """

    offset: int
    page: Optional[dict] = None
    failure: Optional[BillingFetch] = None
    gaps: tuple[int, ...] = ()


def read_offset_page_skipping_poison(
    db: Session,
    *,
    fetch: Fetch,
    period_key: str,
    document_type: str,
    offset: int,
    limit: int,
    now: datetime,
    lap_id: Optional[str] = None,
) -> OffsetRead:
    result = narrow_bare_400(fetch, offset, limit)
    if result.ok:
        return OffsetRead(offset=offset, page=result.body)
    if not result.is_bare_400:
        return OffsetRead(offset=offset, failure=result)
    record_gap(
        db,
        period_key=period_key,
        document_type=document_type,
        billing_source=_SOURCE,
        paging=_PAGING,
        position=str(offset),
        window=f"[{offset}, {offset}]",
        http_status=result.status,
        error=json.dumps(result.body),
        now=now,
        lap_id=lap_id,
    )
    return OffsetRead(offset=offset + 1, gaps=(offset,))


def resolve_recovered_offset_gaps(
    db: Session,
    *,
    period_key: str,
    document_type: str,
    read_offset: int,
    n_results: int,
    now: datetime,
) -> int:
    """Resolves the open flex offset gaps covered by a clean page. Returns how
    many were resolved. The caller commits."""
    resolved = 0
    for gap in open_gaps(db, period_key, document_type):
        if gap.paging != _PAGING or gap.billing_source != _SOURCE or not gap.position.isdigit():
            continue
        if read_offset <= int(gap.position) < read_offset + n_results:
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
