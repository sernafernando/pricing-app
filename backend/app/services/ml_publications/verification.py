"""Verification jobs of the ML publications store (spec "Divergence spot-check", "Freshness and completeness metrics").

Two independent sub-jobs, each behind its own flag and each leaving one `ml_pub_job_runs` row:

- **Divergence spot-check** (`divergence`): samples stored items, covering every status, re-fetches them from
  `/items/bulk` and compares the typed columns against what the Store holds. The match rate is per ITEM (an item
  agrees when none of its typed columns differs), so 3 of 100 items with another `status` is 97%. A run below
  `TARGET_RATE` is flagged in its record, with the (item, path) pairs that differ.
- **Freshness snapshot** (`freshness`): stores the numbers `status.freshness_metrics` computes for the admin
  endpoint, so the history of the freshness and completeness is queryable without the live report.

The re-fetch is the ordinary paced path: the caller's client (shared pacer, family `items_bulk`) spends the
slots. It runs in the LOWEST lane (`LANE`): while any entry of a higher lane (manual, notification, reconcile,
backfill) waits to be claimed it yields, and it never writes to the Store or the queue.

A difference is not divergence when the Store moved since the sample was taken: the item was fetched again
(`fetched_at` changed) or has a refresh of its core pending (a parked entry, or one naming only performance or
visits, does not count). Those are listed apart (`changed_after_sampling`) and left out
of the rate. An item ML no longer answers (404, error element) cannot be compared: it is `unverified`.

An interrupted run (deadline, 429, flag turned off, yielding) leaves no record: it is retried by the handler.
Nothing here reads product or ERP data; the only inputs are the Store and ML.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Callable, Dict, List, Optional, Sequence

from sqlalchemy import text

from app.core import database
from app.models.ml_publications import MlPubJobRun
from app.services.ml_publications import queue, status
from app.services.ml_publications.mappers import map_item
from app.services.ml_publications.ml_http import MlHttpClient
from app.services.ml_publications.pacing import DEADLINE
from app.services.ml_publications.parsers.items_bulk import MalformedBulkResponse, parse_items_bulk
from app.services.ml_publications.resources import BUNDLE_RESOURCE, CORE_RESOURCE

logger = logging.getLogger(__name__)

JOB_DIVERGENCE = "divergence"
JOB_SNAPSHOT = "freshness"
LANE = queue.LANE_SWEEP
TARGET_RATE = 99.0  # percent of sampled items whose typed columns agree
FAMILY = "items_bulk"
STATEMENT_TIMEOUT = "20s"
MAX_LISTED = 200  # pairs kept in the run record

OUTCOME_SUCCESS = "success"
OUTCOME_BELOW_TARGET = "below_target"
OUTCOME_FAILED = "failed"
OUTCOME_YIELDED = "yielded"
OUTCOME_INTERRUPTED = "interrupted"

# Typed columns of an item, as the mapper derives them from a body. Fixed identifiers, never built from input.
TYPED_COLUMNS = tuple(column for column in map_item({}) if column != "item_id")
# Columns whose stored precision is narrower than the body's: the fresh value is rounded the way the column is.
_SCALE = {"price": 2, "base_price": 2, "original_price": 2, "health": 4}
_UNORDERED = ("tags", "sub_status")

_LIVE_WORK = text(
    "SELECT 1 FROM ml_pub_refresh_queue WHERE lane < :lane AND claimed_at IS NULL AND parked_at IS NULL "
    "AND not_before <= now() LIMIT 1"
)
_STATUSES = text(
    "SELECT DISTINCT status FROM ml_items WHERE status IS NOT NULL AND gone_at IS NULL "
    "AND never_existed IS NOT TRUE AND raw IS NOT NULL AND http_status = 200"
)
_SAMPLE = text(
    f"SELECT item_id, fetched_at, {', '.join(TYPED_COLUMNS)} FROM ml_items WHERE status = :status "
    "AND gone_at IS NULL AND never_existed IS NOT TRUE AND raw IS NOT NULL AND http_status = 200 "
    "ORDER BY random() LIMIT :n"
)
# A pending refresh of the item's core (alone or in the bundle) explains a difference in its typed columns. A
# parked entry does not (it keeps failing: the item is the one most likely to be wrong) and neither does an entry
# that only names performance or visits (the sweep's), which never touches them.
_MOVED = text(
    "SELECT i.item_id, i.fetched_at, EXISTS (SELECT 1 FROM ml_pub_refresh_queue q "
    "WHERE q.kind = 'item' AND q.entity_id = i.item_id AND q.parked_at IS NULL "
    "AND q.resources && CAST(:core AS text[])) AS queued FROM ml_items i WHERE i.item_id = ANY(:ids)"
)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class DivergenceResult:
    outcome: str = OUTCOME_SUCCESS
    error: Optional[str] = None
    interruption: Optional[str] = None
    sampled: int = 0
    calls: int = 0
    compared: int = 0
    agreed: int = 0
    by_status: Dict[str, int] = field(default_factory=dict)
    divergences: List[Dict[str, Any]] = field(default_factory=list)
    changed_after_sampling: List[Dict[str, Any]] = field(default_factory=list)
    unverified: List[Dict[str, Any]] = field(default_factory=list)

    @property
    def rate(self) -> Optional[float]:
        return round(100.0 * self.agreed / self.compared, 2) if self.compared else None

    @property
    def flagged(self) -> bool:
        return self.rate is not None and self.rate < TARGET_RATE

    def counts(self) -> Dict[str, Any]:
        return {
            "lane": LANE,
            "target": TARGET_RATE,
            "rate": self.rate,
            "below_target": self.flagged,
            "sampled": self.sampled,
            "compared": self.compared,
            "agreed": self.agreed,
            "calls": self.calls,
            "by_status": self.by_status,
            "divergences": self.divergences[:MAX_LISTED],
            "divergence_pairs": len(self.divergences),
            "changed_after_sampling": self.changed_after_sampling[:MAX_LISTED],
            "changed_after_sampling_items": len({pair["item_id"] for pair in self.changed_after_sampling}),
            "unverified": self.unverified[:MAX_LISTED],
        }

    def as_detail(self) -> Dict[str, Any]:
        counts = self.counts()
        for listed in ("divergences", "changed_after_sampling", "unverified"):
            counts.pop(listed)  # the run record holds the lists; the worker state keeps the numbers
        detail: Dict[str, Any] = {"outcome": self.outcome, **counts}
        if self.error:
            detail["error"] = self.error
        if self.interruption:
            detail["interruption"] = self.interruption
        return detail


def _jsonable(value: Any) -> Any:
    if isinstance(value, (Decimal, datetime)):
        return str(value)
    return value


def _comparable(column: str, value: Any) -> Any:
    if value is None:
        return None
    if column in _UNORDERED and isinstance(value, list):
        return sorted(str(v) for v in value)
    if column in _SCALE and isinstance(value, Decimal):
        return value.quantize(Decimal(1).scaleb(-_SCALE[column]))
    return value


def differences(stored: Dict[str, Any], fresh: Dict[str, Any]) -> List[Dict[str, Any]]:
    """The typed columns that differ between the stored row and the mapped fresh body, as `{path, stored, fresh}`."""
    found = []
    for column in TYPED_COLUMNS:
        if _comparable(column, stored.get(column)) != _comparable(column, fresh.get(column)):
            found.append(
                {"path": column, "stored": _jsonable(stored.get(column)), "fresh": _jsonable(fresh.get(column))}
            )
    return found


def sample(size: int) -> List[Dict[str, Any]]:
    """Up to `size` stored items, taken in turn from every status (random within it), so no status is left out."""
    with database.get_background_db() as db:
        db.execute(text(f"SET LOCAL statement_timeout = '{STATEMENT_TIMEOUT}'"))
        per_status = [
            [dict(row) for row in db.execute(_SAMPLE, {"status": name, "n": size}).mappings()]
            for name in sorted(db.execute(_STATUSES).scalars())
        ]
    chosen: List[Dict[str, Any]] = []
    rounds = 0
    while len(chosen) < size and any(rounds < len(rows) for rows in per_status):
        for rows in per_status:
            if rounds < len(rows) and len(chosen) < size:
                chosen.append(rows[rounds])
        rounds += 1
    return chosen


def _live_work_waits() -> bool:
    with database.get_background_db() as db:
        return db.execute(_LIVE_WORK, {"lane": LANE}).first() is not None


def _moved_since(sampled: Sequence[Dict[str, Any]]) -> set:
    """Items the Store fetched again since they were sampled, or has a refresh pending for (spec: "an event already
    queued or fetched after sampling time")."""
    by_id = {row["item_id"]: row["fetched_at"] for row in sampled}
    with database.get_background_db() as db:
        rows = db.execute(_MOVED, {"ids": list(by_id), "core": [CORE_RESOURCE, BUNDLE_RESOURCE]}).mappings().all()
    return {row["item_id"] for row in rows if row["queued"] or row["fetched_at"] != by_id[row["item_id"]]}


def _fetch(client: MlHttpClient, ids: List[str], deadline: datetime, result: DivergenceResult):
    """One paced `/items/bulk` call. Returns the parsed elements, or None after setting the run's end."""
    response = client.get(FAMILY, f"/items/bulk?ids={','.join(ids)}", deadline=deadline)
    result.calls += 1
    if response.error == DEADLINE:
        result.outcome, result.interruption = OUTCOME_INTERRUPTED, "deadline"
    elif response.status == 429:
        result.outcome, result.interruption = OUTCOME_INTERRUPTED, "rate_limited"
    elif response.error or not 200 <= response.status < 300:
        result.outcome, result.error = OUTCOME_FAILED, response.error or f"HTTP {response.status}"
    else:
        try:
            return parse_items_bulk(ids, response.body, filtered=False)
        except MalformedBulkResponse as exc:
            result.outcome, result.error = OUTCOME_FAILED, f"malformed_bulk_response: {exc}"[:300]
    return None


def _compare(rows: List[Dict[str, Any]], elements, result: DivergenceResult) -> None:
    moved = _moved_since(rows)
    for row, element in zip(rows, elements):
        if element.status != 200 or element.body is None:
            result.unverified.append({"item_id": row["item_id"], "http_status": element.status})
            continue
        found = differences(row, map_item(element.body))
        if not found:
            result.compared += 1
            result.agreed += 1
        elif row["item_id"] in moved:
            result.changed_after_sampling += [{"item_id": row["item_id"], **pair} for pair in found]
        else:
            result.compared += 1
            result.divergences += [{"item_id": row["item_id"], **pair} for pair in found]


def _record(
    job: str, scope: Optional[str], outcome: str, counts: Dict[str, Any], error: Optional[str], started, finished
):
    with database.get_background_db() as db:
        db.add(
            MlPubJobRun(
                job=job,
                scope=scope,
                started_at=started,
                finished_at=finished,
                outcome=outcome,
                counts=counts,
                last_error=error[:1000] if error else None,
            )
        )


def run_divergence(
    client: MlHttpClient,
    *,
    sample_size: int,
    bulk_max_ids: int,
    deadline: datetime,
    keep_going: Callable[[], bool],
    now: Callable[[], datetime] = _utcnow,
) -> DivergenceResult:
    """One spot-check. Never raises: a failure is in `result.error` and in the run record."""
    result = DivergenceResult()
    started = now()
    try:
        if _live_work_waits():
            result.outcome = OUTCOME_YIELDED
            return result
        rows = sample(sample_size)
        result.sampled = len(rows)
        for row in rows:
            result.by_status[row["status"] or "unknown"] = result.by_status.get(row["status"] or "unknown", 0) + 1
        for start in range(0, len(rows), bulk_max_ids):
            if not keep_going():
                result.outcome, result.interruption = OUTCOME_INTERRUPTED, "flag_off"
                break
            if start and _live_work_waits():
                result.outcome = OUTCOME_YIELDED
                break
            batch = rows[start : start + bulk_max_ids]
            elements = _fetch(client, [row["item_id"] for row in batch], deadline, result)
            if elements is None:
                break
            _compare(batch, elements, result)
        if result.outcome == OUTCOME_SUCCESS and result.flagged:
            result.outcome = OUTCOME_BELOW_TARGET
    except Exception as exc:  # noqa: BLE001 -- the handler keeps running; the failure is recorded
        logger.exception("divergence spot-check failed")
        result.outcome, result.error = OUTCOME_FAILED, f"internal_error: {type(exc).__name__}: {exc}"[:300]
    if result.outcome in (OUTCOME_SUCCESS, OUTCOME_BELOW_TARGET, OUTCOME_FAILED):
        try:
            _record(JOB_DIVERGENCE, str(sample_size), result.outcome, result.counts(), result.error, started, now())
        except Exception:  # noqa: BLE001 -- observability must never fail the job
            logger.exception("could not record the divergence run")
    return result


@dataclass
class SnapshotResult:
    outcome: str = OUTCOME_SUCCESS
    error: Optional[str] = None
    counts: Dict[str, Any] = field(default_factory=dict)

    def as_detail(self) -> Dict[str, Any]:
        detail: Dict[str, Any] = {"outcome": self.outcome, "items": (self.counts.get("items") or {}).get("total")}
        if self.error:
            detail["error"] = self.error
        return detail


def run_snapshot(*, bundle_resources: Sequence[str], now: Callable[[], datetime] = _utcnow) -> SnapshotResult:
    """One freshness and completeness snapshot. Reads only; never raises."""
    result = SnapshotResult()
    started = now()
    try:
        with database.get_background_db() as db:
            db.execute(text(f"SET LOCAL statement_timeout = '{STATEMENT_TIMEOUT}'"))
            result.counts = status.freshness_metrics(db, list(bundle_resources))
    except Exception as exc:  # noqa: BLE001 -- the next daily run retries
        logger.exception("freshness snapshot failed")
        result.outcome, result.error = OUTCOME_FAILED, f"internal_error: {type(exc).__name__}: {exc}"[:300]
    try:
        _record(JOB_SNAPSHOT, None, result.outcome, result.counts, result.error, started, now())
    except Exception:  # noqa: BLE001
        logger.exception("could not record the freshness snapshot")
    return result
