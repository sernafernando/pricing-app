"""The honest-state block of every list response (spec HON-1, UI-7), built from `status.build_status`.

The list never invents a number: when a flag is off or a resource is not collected, the columns that depend on
it are null, and this block tells the screen WHY (which flag, which resource, what it affects) so it can show a
banner instead of a silent "—".

`build_status` is the operator report: it scans every state table (percentiles, completeness, link coverage),
far too heavy for each page of a list that must answer in 500 ms. `ReportCache` therefore builds it at most once
per `REPORT_TTL_SECONDS` per process, in a session of its own (the report puts its transaction in READ ONLY
mode, which must not leak into the request's session), and a failed build is cached briefly so a broken report
neither takes the list down nor is retried on every request.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any, Callable, Mapping, Optional

from app.core import database
from app.core.config import settings
from app.services.ml_publications import status

logger = logging.getLogger(__name__)

REPORT_TTL_SECONDS = 60.0
FAILURE_TTL_SECONDS = 10.0
DAY_SECONDS = 86400

# flag -> the response fields (or filters) that read null or empty while it is off
FLAG_EFFECTS: dict[str, list[str]] = {
    "events": ["last_event", "evento"],
    "links": ["link"],
    "refresh": ["all"],
}
# resource -> the same, for a resource that the store does not collect (not in `bundle_resources`)
RESOURCE_EFFECTS: dict[str, list[str]] = {
    "sale_price": ["price"],
    "stock": ["stock.full", "stock.own"],
}

_UNAVAILABLE: dict[str, Any] = {
    "available": False,
    "reason": "status_unavailable",
    "degraded": True,
    "degradations": [],
    "sections_failed": [],
    "store_empty": None,
    "kill_switch": None,
    "generated_at": None,
}


def _flag_degradations(report: Mapping[str, Any]) -> list[dict[str, Any]]:
    flags = report.get("flags") or {}
    return [
        {"code": "flag_disabled", "flag": flag, "affects": list(affects)}
        for flag, affects in FLAG_EFFECTS.items()
        if flags.get(flag) is False
    ]


def _resource_degradations(report: Mapping[str, Any]) -> list[dict[str, Any]]:
    completeness = report.get("completeness") or {}
    return [
        {"code": "resource_not_collected", "resource": resource, "affects": list(affects)}
        for resource, affects in RESOURCE_EFFECTS.items()
        if (completeness.get(resource) or {}).get("expected") is False
    ]


def _stale(report: Mapping[str, Any]) -> list[dict[str, Any]]:
    age = ((report.get("freshness") or {}).get("items") or {}).get("p95_age_seconds")
    limit = settings.ML_PUB_STALE_DAYS * DAY_SECONDS
    if age is None or age <= limit:
        return []
    return [{"code": "stale_data", "resource": "items", "p95_age_seconds": age, "affects": ["all"]}]


def build_block(report: Mapping[str, Any]) -> dict[str, Any]:
    """The block for one `build_status` report (pure)."""
    degradations = _flag_degradations(report)
    if report.get("kill_switch"):
        degradations.insert(0, {"code": "kill_switch", "affects": ["all"]})
    degradations += _resource_degradations(report) + _stale(report)
    failed = list(report.get("sections_failed") or [])
    items = report.get("items")
    return {
        "available": True,
        "generated_at": report.get("generated_at"),
        "store_empty": None if items is None else items.get("total") == 0,
        "kill_switch": bool(report.get("kill_switch")),
        "degraded": bool(degradations or failed),
        "degradations": degradations,
        "sections_failed": failed,
    }


class ReportCache:
    """Process-wide, time-boxed copy of the block; `build` returns a `build_status` report."""

    def __init__(
        self,
        build: Callable[[], Mapping[str, Any]],
        ttl: float = REPORT_TTL_SECONDS,
        failure_ttl: float = FAILURE_TTL_SECONDS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._build = build
        self._ttl = ttl
        self._failure_ttl = failure_ttl
        self._clock = clock
        self._lock = threading.Lock()
        self._block: Optional[dict[str, Any]] = None
        self._expires = 0.0

    def get(self) -> dict[str, Any]:
        with self._lock:  # one builder at a time: the others wait for its result instead of repeating it
            now = self._clock()
            if self._block is not None and now < self._expires:
                return self._block
            try:
                self._block, ttl = build_block(self._build()), self._ttl
            except Exception:  # noqa: BLE001 -- the report must never take the list down
                logger.exception("ml publications view: the status report could not be built")
                self._block, ttl = dict(_UNAVAILABLE), self._failure_ttl
            self._expires = now + ttl
            return self._block

    def reset(self) -> None:
        with self._lock:
            self._block, self._expires = None, 0.0


def _build_report() -> Mapping[str, Any]:
    with database.get_background_db() as session:
        try:
            return status.build_status(session)
        finally:
            session.rollback()  # ends the read-only transaction; nothing was written


REPORT = ReportCache(_build_report)
