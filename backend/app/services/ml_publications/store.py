"""Transactional upsert of one fetched resource (design D8).

`apply_fetch` is the only writer of the item state, its change log and its
variation projection. One call is one transaction on one entity: the row is
locked, the response is compared against the COMMITTED state, and everything
(state, change-log row) commits together or not at all. No application code in
this module deletes a store row.

Postgres only (`SET LOCAL`, row locks, `ON CONFLICT`).
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal, Mapping, Optional

from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.core import database
from app.models.ml_publications import MlChangeLog, MlItem
from app.services.ml_publications.canonical import canonical_hash
from app.services.ml_publications.diff import Change, diff, split_excluded
from app.services.ml_publications.ml_http import MlResponse
from app.services.ml_publications.resources import ResourceSpec

LOCK_TIMEOUT = "5s"
STATEMENT_TIMEOUT = "15s"
STATUS_ACTIVE = "active"

ApplyKind = Literal[
    "first_seen",
    "unchanged",
    "changed",
    "noise_only",
    "stale",
    "gone",
    "restored",
    "never_existed",
    "error_recorded",
]


@dataclass(frozen=True)
class ApplyOutcome:
    kind: ApplyKind
    change_log_id: Optional[int] = None
    events: int = 0  # event derivation arrives with PR5


@dataclass
class ApplyCounters:
    """Cumulative observability counters of the store (the caller flushes them)."""

    stale_discarded: int = 0
    noise_suppressed: Counter = field(default_factory=Counter)  # (resource, path) -> count


def _context(old: Mapping[str, Any], new: Mapping[str, Any], first_active_before: Optional[datetime]) -> dict:
    """Minimal inputs event rules need beyond the changed paths (design D8)."""
    return {
        "status_old": old.get("status"),
        "status_new": new.get("status"),
        "sub_status_old": old.get("sub_status"),
        "sub_status_new": new.get("sub_status"),
        "available_quantity_old": old.get("available_quantity"),
        "available_quantity_new": new.get("available_quantity"),
        "first_active_at_before": first_active_before.isoformat() if first_active_before else None,
        "official_store_id": new.get("official_store_id"),
        "brand": new.get("brand"),
    }


def _typed_snapshot(row: MlItem) -> dict:
    keys = ("status", "sub_status", "available_quantity", "official_store_id", "brand")
    return {key: getattr(row, key) for key in keys}


def _stale(row: MlItem, incoming_last_updated: Optional[datetime], response: MlResponse) -> bool:
    """True when the response is older than the committed state (D8 step 1)."""
    if incoming_last_updated is not None and row.ml_last_updated is not None:
        return incoming_last_updated < row.ml_last_updated
    if row.fetched_request_started_at is not None:
        return response.request_started_at <= row.fetched_request_started_at
    return False


def _set_typed(row: MlItem, typed: Mapping[str, Any]) -> None:
    for column, value in typed.items():
        if column != "item_id":
            setattr(row, column, value)


def apply_fetch(
    spec: ResourceSpec,
    key: tuple,
    response: MlResponse,
    *,
    trigger_received_at: Optional[datetime] = None,
    counters: Optional[ApplyCounters] = None,
) -> ApplyOutcome:
    """Apply one fetched item response to the store inside one transaction."""
    counters = counters if counters is not None else ApplyCounters()
    (item_id,) = key
    with database.get_background_db() as db:
        db.execute(text(f"SET LOCAL lock_timeout = '{LOCK_TIMEOUT}'"))
        db.execute(text(f"SET LOCAL statement_timeout = '{STATEMENT_TIMEOUT}'"))
        db.execute(pg_insert(MlItem).values(item_id=item_id).on_conflict_do_nothing(index_elements=["item_id"]))
        row = db.query(MlItem).filter(MlItem.item_id == item_id).with_for_update().one()

        body = response.body
        typed = spec.mapper(body)
        incoming_last_updated = typed["ml_last_updated"]
        if row.raw is not None and _stale(row, incoming_last_updated, response):
            counters.stale_discarded += 1
            return ApplyOutcome("stale")

        new_hash = canonical_hash(body, spec)
        observed_at = response.received_at
        if row.raw is None:
            _set_typed(row, typed)
            row.raw = body
            row.raw_hash = new_hash
            row.http_status = response.status
            row.fetched_at = observed_at
            row.fetched_request_started_at = response.request_started_at
            row.last_checked_at = observed_at
            row.never_existed = False
            row.gone_at = None
            if typed["status"] == STATUS_ACTIVE:
                row.first_active_at = observed_at
            db.flush()
            return ApplyOutcome("first_seen")

        if bytes(row.raw_hash) == new_hash:
            row.last_checked_at = observed_at
            db.flush()
            return ApplyOutcome("unchanged")

        reportable, excluded = split_excluded(diff(row.raw, body, spec), spec.name)
        for change in excluded:
            counters.noise_suppressed[(spec.name, change.path)] += 1
        old_snapshot = _typed_snapshot(row)
        previous_hash = bytes(row.raw_hash)
        first_active_before = row.first_active_at
        _set_typed(row, typed)
        row.raw = body
        row.raw_hash = new_hash
        row.http_status = response.status
        row.fetched_at = observed_at
        row.fetched_request_started_at = response.request_started_at
        row.last_checked_at = observed_at
        if not reportable:
            db.flush()
            return ApplyOutcome("noise_only")
        entry = _log_change(
            db,
            spec,
            item_id,
            "change",
            reportable,
            previous_hash,
            new_hash,
            response,
            incoming_last_updated,
            _context(old_snapshot, typed, first_active_before),
        )
        db.flush()
        return ApplyOutcome("changed", change_log_id=entry.id)


def _log_change(
    db,
    spec: ResourceSpec,
    item_id: str,
    kind: str,
    changes: list[Change],
    previous_hash: Optional[bytes],
    new_hash: Optional[bytes],
    response: MlResponse,
    source_last_updated: Optional[datetime],
    context: dict,
) -> MlChangeLog:
    entry = MlChangeLog(
        resource_type=spec.name,
        entity_id=item_id,
        item_id=item_id,
        kind=kind,
        observed_at=response.received_at,
        source_last_updated=source_last_updated,
        prev_hash=previous_hash,
        new_hash=new_hash,
        changed_paths=[c.path for c in changes],
        changes=[c.as_dict() for c in changes],
        context=context,
    )
    db.add(entry)
    db.flush()
    return entry
