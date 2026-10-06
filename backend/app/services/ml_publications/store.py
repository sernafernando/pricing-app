"""Transactional upsert of one fetched resource (design D8).

`apply_fetch` is the only writer of the item state, its change log and its
variation projection. One call is one transaction on one entity: the row is
locked, the response is compared against the COMMITTED state, and everything
(state, change-log row) commits together or not at all. No application code in
this module deletes a store row.

Postgres only (`SET LOCAL`, row locks, `ON CONFLICT`).
"""

from __future__ import annotations

import logging
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal, Mapping, Optional

from sqlalchemy import null, text
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.core import database
from app.models.ml_publications import MlChangeLog, MlItem, MlItemVariation
from app.services.ml_publications import events_store, settings_store
from app.services.ml_publications.canonical import canonical_hash
from app.services.ml_publications.diff import Change, diff, split_excluded
from app.services.ml_publications.mappers import map_variations
from app.services.ml_publications.ml_http import MlResponse
from app.services.ml_publications.resources import ResourceSpec

logger = logging.getLogger(__name__)

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
    events: int = 0  # business events written with the change-log row (0 when the flag is off)


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
        "first_active_at_before": first_active_before.astimezone(timezone.utc).isoformat()
        if first_active_before
        else None,
        "official_store_id": new.get("official_store_id"),
        "brand": new.get("brand"),
    }


def _events_enabled() -> bool:
    """The `events.enabled` DB flag, read before the transaction opens. Fails closed: an
    unreadable flag means no events (the change log is always written; events can be rebuilt
    from it later with `events_store.rederive_events`)."""
    try:
        return settings_store.is_enabled("events") is True
    except Exception:  # noqa: BLE001 -- a settings failure must never block the change log
        logger.exception("ml_pub events flag unreadable; no events for this fetch")
        return False


def _typed_snapshot(row: MlItem) -> dict:
    keys = ("status", "sub_status", "available_quantity", "official_store_id", "brand")
    return {key: getattr(row, key) for key in keys}


def _stale(row: MlItem, incoming_last_updated: Optional[datetime], response: MlResponse) -> bool:
    """True when the response is older than the committed state (D8 step 1).

    Items order by ML `last_updated`: strictly older is stale, strictly newer is not. A response
    without one (404, error, declared negative state), an EQUAL one (ML can change a sub-field
    without bumping it, so another observation may sit in between) and any answer about a row
    last seen as gone are ordered by the request start time instead: the state ML reported was
    read at or after that instant.
    """
    if incoming_last_updated is not None and row.ml_last_updated is not None:
        if incoming_last_updated < row.ml_last_updated:
            return True
        if incoming_last_updated > row.ml_last_updated and row.gone_at is None:
            return False
    if row.fetched_request_started_at is None:
        return False
    return response.request_started_at <= row.fetched_request_started_at


def _set_typed(row: MlItem, typed: Mapping[str, Any]) -> None:
    for column, value in typed.items():
        if column != "item_id":
            setattr(row, column, value)


def _later(current: Optional[datetime], candidate: datetime) -> datetime:
    return candidate if current is None or candidate > current else current


def _touch(row: MlItem, response: MlResponse, trigger_received_at: Optional[datetime]) -> None:
    """The narrow freshness update: `last_checked_at` (and the notification time when given)."""
    row.last_checked_at = _later(row.last_checked_at, response.received_at)
    if trigger_received_at is not None:
        row.last_trigger_received_at = _later(row.last_trigger_received_at, trigger_received_at)


def _mark_ok(row: MlItem, response: MlResponse) -> None:
    row.http_status = response.status
    row.error_body = null()
    row.last_error = None


def _record_error(row: MlItem, response: MlResponse, reason: Optional[str] = None) -> None:
    row.http_status = response.status or None
    body = response.body
    row.error_body = body if isinstance(body, (dict, list)) else null()
    row.last_error = reason or (f"HTTP {response.status}" if response.status else response.error or "no response")


def _write_state(row: MlItem, typed: Mapping[str, Any], body: dict, new_hash: bytes, response: MlResponse) -> None:
    _set_typed(row, typed)
    row.raw = body
    row.raw_hash = new_hash
    row.fetched_at = response.received_at
    row.fetched_request_started_at = response.request_started_at
    row.never_existed = False
    row.gone_at = None
    _mark_ok(row, response)


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
    events_enabled = _events_enabled()
    with database.get_background_db() as db:
        db.execute(text(f"SET LOCAL lock_timeout = '{LOCK_TIMEOUT}'"))
        db.execute(text(f"SET LOCAL statement_timeout = '{STATEMENT_TIMEOUT}'"))
        db.execute(pg_insert(MlItem).values(item_id=item_id).on_conflict_do_nothing(index_elements=["item_id"]))
        row = db.query(MlItem).filter(MlItem.item_id == item_id).with_for_update().one()

        is_state = 200 <= response.status < 300 or response.status in spec.negative_states
        typed: Optional[dict] = None
        malformed: Optional[str] = None
        if is_state:
            body = response.body
            if not isinstance(body, dict):
                malformed = "invalid body"
            elif response.status in spec.negative_states:
                typed = {}  # a declared negative state is recorded as-is: its body is not an item
            elif body.get("id") == item_id:
                typed = spec.mapper(body)
            else:
                malformed = "body id mismatch"

        incoming_last_updated = typed.get("ml_last_updated") if typed else None
        if _stale(row, incoming_last_updated, response):
            counters.stale_discarded += 1
            return ApplyOutcome("stale")
        if malformed:
            return _error(db, row, response, malformed)

        if typed is None:
            if response.status == 404:
                return _not_found(db, spec, row, response, trigger_received_at, events_enabled)
            return _error(db, row, response)

        return _apply_state(db, spec, row, body, typed, response, trigger_received_at, counters, events_enabled)


def _apply_state(
    db,
    spec: ResourceSpec,
    row: MlItem,
    body: dict,
    typed: dict,
    response: MlResponse,
    trigger_received_at: Optional[datetime],
    counters: ApplyCounters,
    events_enabled: bool,
) -> ApplyOutcome:
    """A 2xx (or declared negative-state) body: first sighting, unchanged, noise-only, change or restore."""
    item_id = row.item_id
    incoming_last_updated = typed.get("ml_last_updated")
    new_hash = canonical_hash(body, spec)
    if row.raw is None:
        _write_state(row, typed, body, new_hash, response)
        if typed.get("status") == STATUS_ACTIVE:
            row.first_active_at = response.received_at
        _touch(row, response, trigger_received_at)
        if typed:  # a negative-state body carries no variations
            _project_variations(db, item_id, body, response)
        db.flush()
        return ApplyOutcome("first_seen")

    restoring = row.gone_at is not None
    if not restoring and bytes(row.raw_hash) == new_hash:
        _touch(row, response, trigger_received_at)
        row.fetched_request_started_at = _later(row.fetched_request_started_at, response.request_started_at)
        _mark_ok(row, response)
        db.flush()
        return ApplyOutcome("unchanged")

    reportable, excluded = split_excluded(diff(row.raw, body, spec), spec.name)
    for change in excluded:
        counters.noise_suppressed[(spec.name, change.path)] += 1
    old_snapshot = _typed_snapshot(row)
    previous_hash = bytes(row.raw_hash)
    first_active_before = row.first_active_at
    _write_state(row, typed, body, new_hash, response)
    if row.first_active_at is None and typed.get("status") == STATUS_ACTIVE:
        row.first_active_at = response.received_at
    _touch(row, response, trigger_received_at)
    if typed:  # a negative-state body carries no variations
        _project_variations(db, item_id, body, response)
    if not reportable and not restoring:
        db.flush()
        return ApplyOutcome("noise_only")
    kind = "restored" if restoring else "change"
    entry = _log_change(
        db,
        spec,
        item_id,
        kind,
        reportable,
        previous_hash,
        new_hash,
        response,
        incoming_last_updated,
        _context(old_snapshot, typed or old_snapshot, first_active_before),
    )
    return ApplyOutcome(
        "restored" if restoring else "changed",
        change_log_id=entry.id,
        events=_emit_events(db, entry, events_enabled),
    )


def _project_variations(db, item_id: str, body: Mapping[str, Any], response: MlResponse) -> None:
    """Keep `ml_item_variations` a typed projection of the item's `variations` (same transaction).

    Only new, changed or returning variations are written; a variation that vanished
    from the body is kept and marked gone. Their changes are logged in the item's
    change-log row, never in a row of their own.
    """
    existing = {v.variation_id: v for v in db.query(MlItemVariation).filter(MlItemVariation.item_id == item_id)}
    seen: set[int] = set()
    for typed in map_variations(body):
        variation_id = typed["variation_id"]
        if variation_id is None or variation_id in seen:
            continue
        seen.add(variation_id)
        raw_hash = canonical_hash(typed["raw"])
        current = existing.get(variation_id)
        if current is None:
            current = MlItemVariation(item_id=item_id, variation_id=variation_id)
            db.add(current)
        elif bytes(current.raw_hash) == raw_hash and current.gone_at is None:
            continue
        for column, value in typed.items():
            if column not in ("item_id", "variation_id"):
                setattr(current, column, value)
        current.raw_hash = raw_hash
        current.fetched_at = response.received_at
        current.gone_at = None
    for variation_id, variation in existing.items():
        if variation_id not in seen and variation.gone_at is None:
            variation.gone_at = response.received_at


def _error(db, row: MlItem, response: MlResponse, reason: Optional[str] = None) -> ApplyOutcome:
    """Record a failed fetch (D8 step 3): the last known raw and typed values stay as they were."""
    _record_error(row, response, reason)
    db.flush()
    return ApplyOutcome("error_recorded")


def _not_found(
    db,
    spec: ResourceSpec,
    row: MlItem,
    response: MlResponse,
    trigger_received_at: Optional[datetime],
    events_enabled: bool,
) -> ApplyOutcome:
    """The resource answered 404 (D8 step 2): mark it gone once, never delete anything."""
    if row.gone_at is not None:
        _record_error(row, response)
        row.fetched_request_started_at = _later(row.fetched_request_started_at, response.request_started_at)
        _touch(row, response, trigger_received_at)
        db.flush()
        return ApplyOutcome("unchanged")
    _record_error(row, response)
    row.gone_at = response.received_at
    row.fetched_request_started_at = response.request_started_at
    _touch(row, response, trigger_received_at)
    if row.raw is None:
        row.never_existed = True
        db.flush()
        return ApplyOutcome("never_existed")
    snapshot = _typed_snapshot(row)
    entry = _log_change(
        db,
        spec,
        row.item_id,
        "gone",
        [],
        bytes(row.raw_hash),
        bytes(row.raw_hash),
        response,
        None,
        _context(snapshot, snapshot, row.first_active_at),
    )
    return ApplyOutcome("gone", change_log_id=entry.id, events=_emit_events(db, entry, events_enabled))


def _emit_events(db, entry: MlChangeLog, events_enabled: bool) -> int:
    """Events of the row just logged, in the same transaction (D8 step 6)."""
    return events_store.write_events(db, entry) if events_enabled else 0


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
