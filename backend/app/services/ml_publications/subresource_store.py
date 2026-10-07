"""Transactional upsert of one fetched sub-resource (design D8 for sub-resources).

The same contract as `store.apply_fetch`, for the sub-resource tables keyed by item id
(`description`, `prices`, `sale_price`, `promotions`), by user product id (`user_product`, `stock`) or
by family id (`family`): one call is one transaction on one entity, the row is locked, the response is
compared against the COMMITTED state and the state, its change-log row and its events commit together or
not at all. Nothing here deletes a store row.

Differences from the item core: classification is by HTTP status through the resource parser
(`ok`, `not_found`, `error`), a response is ordered by the time its request started (these
resources have no ML `last_updated` to order by), and events read their inputs from the
`entries` context written with the change-log row (`subresource_context`).

Postgres only (`SET LOCAL`, row locks, `ON CONFLICT`).
"""

from __future__ import annotations

from typing import Any, Mapping, Optional

from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.core import database
from app.models.ml_publications import (
    MlItem,
    MlItemDescription,
    MlItemPrices,
    MlItemSalePrice,
    MlItemSellerPromotions,
    MlUserProduct,
    MlUserProductFamily,
    MlUserProductStock,
)
from app.services.ml_publications.canonical import canonical_hash
from app.services.ml_publications.diff import diff, split_excluded
from app.services.ml_publications.ml_http import MlResponse
from app.services.ml_publications.parsers.subresource import MalformedSubResource, ParsedSubResource
from app.services.ml_publications.resources import RESOURCES, ResourceSpec

# Writes and bookkeeping shared with the item core, so both stores keep one definition of "write
# the state", "record an error" and "log a change".
from app.services.ml_publications.store import (
    LOCK_TIMEOUT,
    STATEMENT_TIMEOUT,
    ApplyCounters,
    ApplyOutcome,
    _emit_events,
    _events_enabled,
    _later,
    _log_change,
    _mark_ok,
    _record_error,
    _write_state,
)
from app.services.ml_publications.subresource_context import entries_context

MODELS: dict[str, Any] = {
    "description": MlItemDescription,
    "prices": MlItemPrices,
    "sale_price": MlItemSalePrice,
    "promotions": MlItemSellerPromotions,
    "user_product": MlUserProduct,
    "stock": MlUserProductStock,
    "family": MlUserProductFamily,
}

ITEM_KEY = "item_id"

MAX_REASON_CHARS = 300


def supports(resource: str) -> bool:
    return resource in MODELS


def _parse(spec: ResourceSpec, response: MlResponse) -> tuple[Optional[ParsedSubResource], Optional[str]]:
    try:
        return spec.parser(response.status, response.body), None
    except MalformedSubResource as exc:
        return None, f"malformed: {exc}"[:MAX_REASON_CHARS]


def _stale(row: Any, response: MlResponse) -> bool:
    """True when this request started no later than the one whose answer is stored (D8 step 1)."""
    return row.fetched_request_started_at is not None and response.request_started_at <= row.fetched_request_started_at


def _key_column(spec: ResourceSpec) -> str:
    return spec.key_columns[0]


def _is_item_scoped(spec: ResourceSpec) -> bool:
    """Rows keyed by item id belong to an item (its store and brand are attributed to their events);
    user product and family rows belong to no single item."""
    return _key_column(spec) == ITEM_KEY


class InvalidKey(ValueError):
    """An entity id the key column cannot hold (a family id that is not a BIGINT)."""


MAX_BIGINT = 2**63 - 1


def typed_key(resource: str, key: str) -> Any:
    """The queue's text id as the key column of `resource` holds it (a family id is a BIGINT); raises
    `InvalidKey` for an id that column cannot hold. Queue ids are not validated on enqueue, so every
    reader of a key goes through here before it reaches the database."""
    model = MODELS[resource]
    if getattr(model, RESOURCES[resource].key_columns[0]).type.python_type is not int:
        return key
    if not (isinstance(key, str) and key.isascii() and key.isdigit() and int(key) <= MAX_BIGINT):
        raise InvalidKey(f"{key!r} is not a valid {resource} id")
    return int(key)


def _checked(row: Any, response: MlResponse) -> None:
    row.last_checked_at = _later(row.last_checked_at, response.received_at)


def _attribution(db, spec: ResourceSpec, item_id: str) -> dict:
    """Store and brand of the item, read (not locked) for the events' denormalized columns; empty for a
    resource that belongs to no single item."""
    if not _is_item_scoped(spec):
        return {}
    item = db.query(MlItem.official_store_id, MlItem.brand).filter(MlItem.item_id == item_id).first()
    return {"official_store_id": item.official_store_id if item else None, "brand": item.brand if item else None}


def apply_subresource(
    spec: ResourceSpec,
    key: tuple,
    response: MlResponse,
    *,
    counters: Optional[ApplyCounters] = None,
    events_enabled: Optional[bool] = None,
) -> ApplyOutcome:
    """Apply one fetched sub-resource response to the store inside one transaction.

    `events_enabled` is the `events.enabled` flag as the caller already read it; `None` reads it
    here, before the transaction opens (fail closed, see `store._events_enabled`).
    """
    model = MODELS[spec.name]
    counters = counters if counters is not None else ApplyCounters()
    column = _key_column(spec)
    (entity_key,) = key
    entity_key = typed_key(spec.name, entity_key)
    if events_enabled is None:
        events_enabled = _events_enabled()
    parsed, malformed = _parse(spec, response)
    with database.get_background_db() as db:
        db.execute(text(f"SET LOCAL lock_timeout = '{LOCK_TIMEOUT}'"))
        db.execute(text(f"SET LOCAL statement_timeout = '{STATEMENT_TIMEOUT}'"))
        db.execute(pg_insert(model).values({column: entity_key}).on_conflict_do_nothing(index_elements=[column]))
        row = db.query(model).filter(getattr(model, column) == entity_key).with_for_update().one()

        if _stale(row, response):
            counters.stale_discarded += 1
            return ApplyOutcome("stale")
        if parsed is None or parsed.state == "error":
            _record_error(row, response, malformed)
            db.flush()
            return ApplyOutcome("error_recorded")
        if parsed.state == "not_found":
            return _not_found(db, spec, row, response, events_enabled)
        return _apply_state(db, spec, row, parsed.body, response, counters, events_enabled)


def _apply_state(
    db,
    spec: ResourceSpec,
    row: Any,
    body: Mapping[str, Any],
    response: MlResponse,
    counters: ApplyCounters,
    events_enabled: bool,
) -> ApplyOutcome:
    """A 2xx body: first sighting, unchanged, noise-only, change or restore."""
    entity_id = str(getattr(row, _key_column(spec)))
    typed = spec.mapper(body)
    new_hash = canonical_hash(body, spec)
    if row.raw is None:
        _write_state(row, typed, body, new_hash, response)
        _checked(row, response)
        db.flush()
        return ApplyOutcome("first_seen")

    restoring = row.gone_at is not None
    if not restoring and bytes(row.raw_hash) == new_hash:
        _checked(row, response)
        row.fetched_request_started_at = _later(row.fetched_request_started_at, response.request_started_at)
        _mark_ok(row, response)
        db.flush()
        return ApplyOutcome("unchanged")

    old_raw, previous_hash = row.raw, bytes(row.raw_hash)
    reportable, excluded = split_excluded(diff(old_raw, body, spec), spec.name)
    for change in excluded:
        counters.noise_suppressed[(spec.name, change.path)] += 1
    _write_state(row, typed, body, new_hash, response)
    _checked(row, response)
    if not reportable and not restoring:
        db.flush()
        return ApplyOutcome("noise_only")
    entry = _log_change(
        db,
        spec,
        entity_id,
        "restored" if restoring else "change",
        reportable,
        previous_hash,
        new_hash,
        response,
        None,
        {**entries_context(spec.name, old_raw, body), **_attribution(db, spec, entity_id)},
        item_scoped=_is_item_scoped(spec),
    )
    return ApplyOutcome(
        "restored" if restoring else "changed",
        change_log_id=entry.id,
        events=_emit_events(db, entry, events_enabled),
    )


def _not_found(db, spec: ResourceSpec, row: Any, response: MlResponse, events_enabled: bool) -> ApplyOutcome:
    """The sub-resource answered 404: mark it gone once, keep the last raw, never delete anything."""
    if row.gone_at is not None:
        _record_error(row, response)
        row.fetched_request_started_at = _later(row.fetched_request_started_at, response.request_started_at)
        _checked(row, response)
        db.flush()
        return ApplyOutcome("unchanged")
    _record_error(row, response)
    row.gone_at = response.received_at
    row.fetched_request_started_at = response.request_started_at
    _checked(row, response)
    if row.raw is None:
        row.never_existed = True
        db.flush()
        return ApplyOutcome("never_existed")
    entity_id = str(getattr(row, _key_column(spec)))
    entry = _log_change(
        db,
        spec,
        entity_id,
        "gone",
        [],
        bytes(row.raw_hash),
        bytes(row.raw_hash),
        response,
        None,
        _attribution(db, spec, entity_id),
        item_scoped=_is_item_scoped(spec),
    )
    return ApplyOutcome("gone", change_log_id=entry.id, events=_emit_events(db, entry, events_enabled))
