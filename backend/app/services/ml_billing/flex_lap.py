"""Flex details inside the billing lap (ml-billing-balance PR 5-iii).

Flex `/details` page by `offset` (limit 500, `captured_flex_offset_pages.json`), so a flex unit keeps
`offset` where a general one keeps `from_id`. One call of `step` makes ONE request, like the general
unit, and reports what the lap must do with it. A bare 400 starts the resumable `offset_poison_probe`
(kept in `unit["probe"]`, one request per tick); a poison offset is recorded as a gap (paging `offset`,
source `flex`) and stepped over, and a clean page closes the gaps it covers.

Flex documents are NOT listed by `/documents` for group ML or MP (captured 2026-10-09; no group answers
422), so a flex unit is never settled through documents: the unit says `documents: "document_unknown"`,
it has no documents unit, and the period is swept again on every lap.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session

from app.core.config import settings
from app.services.ml_billing.billing_sweep_service import (
    BILLING_GROUP,
    DOCUMENT_TYPES,
    _page_cap,
    persist_details_page,
)
from app.services.ml_billing.offset_poison_probe import advance, new_probe, next_request
from app.services.ml_billing.offset_poison_rows import resolve_recovered_offset_gaps
from app.services.ml_billing.sweep_gaps import record_gap
from app.services.ml_webhook_client import BillingFetch, ml_webhook_client
from app.utils.async_bridge import resolve_maybe_async

logger = logging.getLogger(__name__)

FLEX_PAGE_LIMIT = 500
SOURCE = "flex"
DOCUMENT_UNKNOWN = "document_unknown"


@dataclass(frozen=True)
class FlexResult:
    """`continue`: the unit goes on. `done`/`failed`: the unit ends. `failure`: `fetch` is not a page."""

    kind: str
    fetch: Optional[BillingFetch] = None


def enabled() -> bool:
    return bool(settings.ML_BILLING_ENABLED and settings.ML_BILLING_FLEX_ENABLED)


def units(period_key: str) -> list[dict]:
    return [
        {
            "period_key": period_key,
            "document_type": document_type,
            "kind": "details",
            "source": SOURCE,
            "state": "pending",
            "offset": 0,
            "total": None,
            "pages": 0,
            "verify": False,
            "documents": DOCUMENT_UNKNOWN,
        }
        for document_type in DOCUMENT_TYPES
    ]


def step(db: Session, unit: dict, lap_id: str, now: datetime) -> FlexResult:
    period, document_type = unit["period_key"], unit["document_type"]
    probe = unit.get("probe")
    offset, limit = next_request(probe) if probe else (unit["offset"], FLEX_PAGE_LIMIT)
    fetch = resolve_maybe_async(
        ml_webhook_client.fetch_billing_flex_details(period, BILLING_GROUP, document_type, limit, offset)
    )
    if probe is None and fetch.is_bare_400:
        probe = new_probe(unit["offset"], FLEX_PAGE_LIMIT)  # the bare 400 is the probe's first answer
    if probe is None:
        return _page(db, unit, fetch.body, now, counts=True) if fetch.ok else FlexResult("failure", fetch)
    verdict = advance(probe, fetch)
    if verdict.kind == "failure":
        unit["probe"] = probe
        return FlexResult("failure", verdict.failure)
    if verdict.kind == "next":
        unit["probe"] = probe
        return FlexResult("continue")
    unit.pop("probe", None)
    if verdict.kind == "page":  # a narrowed prefix: advance by what it holds
        return _page(db, unit, verdict.page, now, counts=False)
    record_gap(
        db,
        period_key=period,
        document_type=document_type,
        billing_source=SOURCE,
        paging="offset",
        position=str(verdict.position),
        window=verdict.window,
        http_status=verdict.error["status"],
        error=json.dumps(verdict.error["body"]),
        now=now,
        lap_id=lap_id,
    )
    logger.warning("ml_billing lap: poison offset %s %s %s", period, document_type, verdict.window)
    unit["offset"] = verdict.position + 1
    return FlexResult("continue")


def _page(db: Session, unit: dict, page: dict, now: datetime, counts: bool) -> FlexResult:
    period, document_type = unit["period_key"], unit["document_type"]
    if unit["total"] is None and isinstance(page.get("total"), int):
        unit["total"] = page["total"]
    rows = list(page.get("results") or [])
    if not rows:
        return FlexResult("done")
    persist_details_page(db, rows, period, document_type, billing_source=SOURCE)
    resolve_recovered_offset_gaps(
        db, period_key=period, document_type=document_type, read_offset=unit["offset"], n_results=len(rows), now=now
    )
    unit["offset"] += len(rows)
    unit["pages"] += 1 if counts else 0  # pages narrowed by a probe are small by design
    # `total` drifts while a sweep runs (3324 -> 3325), so the cap keeps the same margin as the general one.
    if unit["total"] is not None and unit["pages"] >= _page_cap(unit["total"], FLEX_PAGE_LIMIT):
        logger.warning("ml_billing lap: flex %s %s exceeded the expected pages", period, document_type)
        return FlexResult("failed")
    return FlexResult("continue")
