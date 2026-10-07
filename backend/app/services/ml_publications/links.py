"""Product links: publication units <-> our products by SKU (design D20, spec Domain 6).

A link unit is `(item_id, variation_id)`; `variation_id = 0` is the item-level unit of an item
without variations. The automatic rule matches the unit's SKU key against `ProductoERP.codigo`
with the same precedence and equality the orders use (SELLER_SKU attribute, else
`seller_custom_field`; exact string equality, no normalization). A manual decision always wins:
the automatic path only refreshes its suggestion columns.

This is the only module of the package that reads `ProductoERP`, and it writes only the link
table, the change log (resource `product_link`) and the events derived from it.
"""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime, time, timezone
from typing import Any, Callable, Mapping, Optional, Sequence
from zoneinfo import ZoneInfo

from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.core import database
from app.models.ml_publications import MlChangeLog, MlItem, MlItemProductLink, MlItemVariation, MlPubSetting
from app.models.producto import ProductoERP
from app.services.ml_publications import events_store

logger = logging.getLogger(__name__)

SKU_FIELD_ATTRIBUTE = "seller_sku_attr"
SKU_FIELD_CUSTOM = "seller_custom_field"

ITEM_LEVEL = 0  # `variation_id` of the item-level unit
RESOURCE_TYPE = "product_link"  # change-log resource type of a link change
INDEX_CHUNK = 500  # keys per `codigo IN (...)` lookup

SOURCE_AUTO = "sku_auto"
SOURCE_MANUAL = "manual"
SOURCE_MANUAL_NONE = "manual_none"

STATUS_LINKED = "linked"
STATUS_UNMATCHED = "unmatched"
STATUS_CONFLICT = "conflict"


@dataclass(frozen=True)
class LinkUnit:
    """One unit and its SKU key (None when ML carries no usable SKU for it)."""

    item_id: str
    variation_id: int
    key: Optional[str]
    sku_field: Optional[str]


@dataclass(frozen=True)
class Suggestion:
    """What the automatic rule says about a unit, whatever its current link is."""

    status: str  # linked | unmatched | conflict
    producto_item_id: Optional[int]
    matched_sku: Optional[str]
    sku_field: Optional[str]
    candidates: tuple[int, ...]  # every product holding the key's `codigo` (sorted, distinct)


def _usable(value: Any) -> Optional[str]:
    """A SKU as ML sent it, or None when absent (missing, not text or empty string)."""
    return value if isinstance(value, str) and value != "" else None


def sku_key(seller_sku: Any, seller_custom_field: Any) -> tuple[Optional[str], Optional[str]]:
    """`(key, sku_field)`: the SELLER_SKU attribute value, else `seller_custom_field`.

    Same precedence as the orders' `seller_sku` linkage; the value is never trimmed or case-folded.
    """
    sku = _usable(seller_sku)
    if sku is not None:
        return sku, SKU_FIELD_ATTRIBUTE
    custom = _usable(seller_custom_field)
    if custom is not None:
        return custom, SKU_FIELD_CUSTOM
    return None, None


def units_for_item(typed_item: Mapping[str, Any], typed_variations: Sequence[Mapping[str, Any]]) -> list[LinkUnit]:
    """The link units of an item from its typed columns (`map_item` / `map_variations` shapes).

    An item with variations has one unit per variation and no item-level unit; a variation
    without a SKU of its own inherits the item's key.
    """
    item_id = typed_item["item_id"]
    item_key, item_field = sku_key(typed_item.get("seller_sku"), typed_item.get("seller_custom_field"))
    units: list[LinkUnit] = []
    seen: set[int] = set()
    for variation in typed_variations:
        variation_id = variation.get("variation_id")
        if not isinstance(variation_id, int) or isinstance(variation_id, bool) or variation_id <= 0:
            continue
        if variation_id in seen:
            continue
        seen.add(variation_id)
        key, field = sku_key(variation.get("seller_sku"), variation.get("seller_custom_field"))
        if key is None:
            key, field = item_key, item_field
        units.append(LinkUnit(item_id, variation_id, key, field))
    if not units:
        units.append(LinkUnit(item_id, ITEM_LEVEL, item_key, item_field))
    return units


def keys_of(units: Sequence[LinkUnit]) -> list[str]:
    """The distinct SKU keys to look up in the product catalog, sorted."""
    return sorted({unit.key for unit in units if unit.key is not None})


def resolve(unit: LinkUnit, codigo_index: Mapping[str, Sequence[int]]) -> Suggestion:
    """Pure rule: one product with that `codigo` links, none is unmatched, several conflict."""
    if unit.key is None:
        return Suggestion(STATUS_UNMATCHED, None, None, None, ())
    candidates = tuple(sorted(set(codigo_index.get(unit.key, ()))))
    if len(candidates) == 1:
        return Suggestion(STATUS_LINKED, candidates[0], unit.key, unit.sku_field, candidates)
    status = STATUS_CONFLICT if candidates else STATUS_UNMATCHED
    return Suggestion(status, None, unit.key, unit.sku_field, candidates)


# --- evaluation (writes the link table; shares the caller's transaction) --------------------------


@dataclass
class EvaluationResult:
    """Tallies of one or more evaluated items."""

    created: int = 0  # first evaluations (a row written, no history)
    changed: int = 0  # automatic units whose link moved (change-log row written)
    unchanged: int = 0  # evaluated, nothing but the timestamp moved
    skipped: int = 0  # units whose SKU key was already evaluated (nothing read, nothing written)
    manual_differs: int = 0  # manual / manual_none units whose decision differs from the SKU suggestion

    def add(self, other: "EvaluationResult") -> None:
        self.created += other.created
        self.changed += other.changed
        self.unchanged += other.unchanged
        self.skipped += other.skipped
        self.manual_differs += other.manual_differs


@dataclass(frozen=True)
class LinkState:
    """The fields of a link that make a change effective (and are logged)."""

    producto_item_id: Optional[int]
    source: str
    match_status: str
    matched_sku: Optional[str]
    sku_field: Optional[str]
    linked_by: Optional[int]

    @classmethod
    def of(cls, row: MlItemProductLink) -> "LinkState":
        return cls(row.producto_item_id, row.source, row.match_status, row.matched_sku, row.sku_field, row.linked_by)


LOGGED_FIELDS = ("producto_item_id", "source", "match_status", "matched_sku")


def load_codigo_index(db, keys: Sequence[str]) -> dict[str, list[int]]:
    """`codigo -> [product item_id]` for the given keys (`codigo` is not unique and is indexed)."""
    index: dict[str, list[int]] = {}
    for start in range(0, len(keys), INDEX_CHUNK):
        chunk = list(keys[start : start + INDEX_CHUNK])
        rows = db.query(ProductoERP.codigo, ProductoERP.item_id).filter(ProductoERP.codigo.in_(chunk)).all()
        for codigo, producto_item_id in rows:
            index.setdefault(codigo, []).append(producto_item_id)
    return index


def evaluate_item(
    db,
    item_id: str,
    typed_item: Mapping[str, Any],
    typed_variations: Sequence[Mapping[str, Any]],
    *,
    now: datetime,
    events_enabled: bool,
    force: bool = False,
) -> EvaluationResult:
    """Evaluate every link unit of one item inside the caller's transaction.

    Without `force`, an item whose units were all evaluated with their current SKU key is skipped
    before the product catalog is read. `force` (catalog changed, daily pass) re-evaluates anyway.
    """
    units = units_for_item(typed_item, typed_variations)
    rows = {
        row.variation_id: row
        for row in db.query(MlItemProductLink)
        .filter(
            MlItemProductLink.item_id == item_id, MlItemProductLink.variation_id.in_([u.variation_id for u in units])
        )
        .with_for_update()
    }
    result = EvaluationResult()
    if not force and all(_up_to_date(rows.get(u.variation_id), u) for u in units):
        result.skipped = len(units)
        return result
    keys = keys_of(units)
    index = load_codigo_index(db, keys) if keys else {}
    for unit in units:
        row = rows.get(unit.variation_id)
        suggestion = resolve(unit, index)
        if row is None:
            row = _insert_first(db, unit, suggestion, now)
            if row is None:  # a concurrent writer created it between our read and insert
                row = _lock(db, unit)
            else:
                result.created += 1
                continue
        _apply_existing(db, row, unit, suggestion, typed_item, now, events_enabled, result)
    return result


def _up_to_date(row: Optional[MlItemProductLink], unit: LinkUnit) -> bool:
    return row is not None and row.evaluated_at is not None and row.evaluated_sku_key == unit.key


def _lock(db, unit: LinkUnit) -> MlItemProductLink:
    return (
        db.query(MlItemProductLink)
        .filter(MlItemProductLink.item_id == unit.item_id, MlItemProductLink.variation_id == unit.variation_id)
        .with_for_update()
        .one()
    )


def _suggestion_columns(suggestion: Suggestion) -> dict[str, Any]:
    return {
        "suggested_producto_item_id": suggestion.producto_item_id,
        "suggestion_status": suggestion.status,
        "suggestion_candidates": len(suggestion.candidates),
    }


def _link_columns(suggestion: Suggestion) -> dict[str, Any]:
    return {
        "producto_item_id": suggestion.producto_item_id,
        "match_status": suggestion.status,
        "matched_sku": suggestion.matched_sku,
        "sku_field": suggestion.sku_field,
        "candidate_ids": list(suggestion.candidates) if suggestion.status == STATUS_CONFLICT else None,
    }


def _insert_first(db, unit: LinkUnit, suggestion: Suggestion, now: datetime) -> Optional[MlItemProductLink]:
    """First evaluation of a unit: the row only (first sighting: no change-log row, no event)."""
    values = {
        "item_id": unit.item_id,
        "variation_id": unit.variation_id,
        "source": SOURCE_AUTO,
        **_link_columns(suggestion),
        **_suggestion_columns(suggestion),
        "evaluated_sku_key": unit.key,
        "evaluated_at": now,
        "linked_at": now,
        "first_seen_at": now,
        "updated_at": now,
    }
    inserted = db.execute(
        pg_insert(MlItemProductLink)
        .values(values)
        .on_conflict_do_nothing(index_elements=["item_id", "variation_id"])
        .returning(MlItemProductLink.variation_id)
    ).all()
    return _lock(db, unit) if inserted else None


def _assign(row: MlItemProductLink, values: Mapping[str, Any]) -> bool:
    """Set the columns that differ; True when any did."""
    changed = False
    for column, value in values.items():
        if getattr(row, column) != value:
            setattr(row, column, value)
            changed = True
    return changed


def _apply_existing(
    db,
    row: MlItemProductLink,
    unit: LinkUnit,
    suggestion: Suggestion,
    typed_item: Mapping[str, Any],
    now: datetime,
    events_enabled: bool,
    result: EvaluationResult,
) -> None:
    """Store the suggestion; move the link only when it is automatic (manual always wins)."""
    before = LinkState.of(row)
    moved = False
    touched = _assign(row, _suggestion_columns(suggestion))
    if row.source == SOURCE_AUTO:
        touched |= _assign(row, _link_columns(suggestion))
        moved = (row.producto_item_id, row.match_status) != (before.producto_item_id, before.match_status)
    elif suggestion.status == STATUS_LINKED and suggestion.producto_item_id != row.producto_item_id:
        result.manual_differs += 1
    row.evaluated_sku_key = unit.key
    row.evaluated_at = now
    if moved:
        row.linked_at = now
    if touched:
        row.updated_at = now
    if moved:
        log_link_change(db, unit.item_id, unit.variation_id, before, LinkState.of(row), now, events_enabled, typed_item)
        result.changed += 1
    else:
        result.unchanged += 1


def log_link_change(
    db,
    item_id: str,
    variation_id: int,
    old: LinkState,
    new: LinkState,
    observed_at: datetime,
    events_enabled: bool,
    typed_item: Mapping[str, Any],
) -> MlChangeLog:
    """Change-log row (resource `product_link`) of an effective link change, plus its events.

    Written in the caller's transaction: the link change, its history row and its event commit
    together or not at all. The context carries everything `product_link_changed` needs, so the
    event can be re-derived from the row alone.
    """
    changes = [
        {"p": name, "op": "replace", "old": getattr(old, name), "new": getattr(new, name)}
        for name in LOGGED_FIELDS
        if getattr(old, name) != getattr(new, name)
    ]
    entry = MlChangeLog(
        resource_type=RESOURCE_TYPE,
        entity_id=f"{item_id}:{variation_id}",
        item_id=item_id,
        kind="change",
        observed_at=observed_at,
        changed_paths=[c["p"] for c in changes],
        changes=changes,
        context={
            "variation_id": variation_id,
            "producto_item_id_old": old.producto_item_id,
            "producto_item_id_new": new.producto_item_id,
            "source_old": old.source,
            "source_new": new.source,
            "match_status_old": old.match_status,
            "match_status_new": new.match_status,
            "matched_sku": new.matched_sku,
            "sku_field": new.sku_field,
            "linked_by": new.linked_by,
            "official_store_id": typed_item.get("official_store_id"),
            "brand": typed_item.get("brand"),
        },
    )
    db.add(entry)
    db.flush()
    if events_enabled:
        events_store.write_events(db, entry)
    return entry


# --- re-link sweep (no ML call; driven by the `ml_publications.relink` worker handler) ------------

SWEEP_BATCH = 500
ARGENTINA_TZ = ZoneInfo("America/Argentina/Buenos_Aires")
DAILY_PASS_AT = time(4, 30)  # Argentina local: the safety-net full pass
SWEEP_STATEMENT_TIMEOUT = "30s"
SWEEP_LOCK_TIMEOUT = "5s"

# Internal `ml_pub_settings` rows (not operator-writable: they are not in the settings allow-list).
SWEEP_STATE_KEY = "links.sweep_state"
FINGERPRINT_KEY = "links.catalog_fingerprint"
LAST_FULL_PASS_KEY = "links.last_full_pass_at"

FINGERPRINT_SQL = (
    "SELECT md5(coalesce(string_agg(item_id::text || ':' || coalesce(codigo, ''), ',' ORDER BY item_id), '')) "
    "FROM productos_erp"
)

STOPPED_DEADLINE = "deadline"
STOPPED_DISABLED = "disabled"

# `gate()` is read at every batch boundary: the events flag while linking stays on, None to stop.
Gate = Callable[[], Optional[bool]]


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class SweepResult:
    """What one sweep run did; `complete` means a whole lap over the items finished."""

    batches: int = 0
    items: int = 0
    errors: int = 0
    contended: int = 0  # items skipped because a fetch held their row; the next lap picks them up
    complete: bool = False
    forced: bool = False
    stopped: Optional[str] = None
    units: EvaluationResult = field(default_factory=EvaluationResult)

    def as_detail(self) -> dict[str, Any]:
        detail = asdict(self.units)
        detail.update(
            batches=self.batches,
            items=self.items,
            errors=self.errors,
            contended=self.contended,
            complete=self.complete,
            forced=self.forced,
        )
        if self.stopped:
            detail["stopped"] = self.stopped
        return detail


@dataclass
class _SweepState:
    cursor: Optional[str] = None  # last item_id of the lap in progress (keyset)
    force: bool = False  # the lap in progress re-evaluates every unit (catalog change / daily pass)
    target: Optional[str] = None  # catalog fingerprint the forced lap converges to
    started_at: Optional[str] = None  # when the forced lap began (ISO, UTC)
    retry: bool = False  # an item failed or was busy during a forced lap: do not record it as converged

    def as_value(self) -> dict[str, Any]:
        return asdict(self)


def _read_setting(db, key: str) -> Any:
    row = db.get(MlPubSetting, key)
    return row.value if row is not None else None


def _write_setting(db, key: str, value: Any, now: datetime) -> None:
    db.execute(
        pg_insert(MlPubSetting)
        .values(key=key, value=value, updated_by="links", updated_at=now)
        .on_conflict_do_update(index_elements=["key"], set_={"value": value, "updated_by": "links", "updated_at": now})
    )


def catalog_fingerprint(db) -> str:
    """Cheap fingerprint of the product catalog (`item_id`, `codigo`): any added, removed or edited code changes it."""
    return db.execute(text(FINGERPRINT_SQL)).scalar()


def _daily_pass_due(now: datetime, last_full: Optional[str]) -> bool:
    """Today's slot reached and no full pass since it (same rule as `scheduling.is_due` for daily jobs)."""
    local_now = now.astimezone(ARGENTINA_TZ)
    slot = local_now.replace(hour=DAILY_PASS_AT.hour, minute=DAILY_PASS_AT.minute, second=0, microsecond=0)
    if local_now < slot:
        return False
    return last_full is None or datetime.fromisoformat(last_full).astimezone(ARGENTINA_TZ) < slot


def _plan_lap(db, state: _SweepState, now: datetime) -> _SweepState:
    """Decide, when no lap is in progress, whether the next one is forced (catalog changed or daily pass)."""
    if state.force or state.cursor is not None:
        return state
    fingerprint = catalog_fingerprint(db)
    if fingerprint != _read_setting(db, FINGERPRINT_KEY) or _daily_pass_due(now, _read_setting(db, LAST_FULL_PASS_KEY)):
        return _SweepState(force=True, target=fingerprint, started_at=now.isoformat())
    return state


def _load_state(db) -> _SweepState:
    stored = _read_setting(db, SWEEP_STATE_KEY)
    if not isinstance(stored, dict):
        return _SweepState()
    return _SweepState(**{k: stored.get(k) for k in ("cursor", "force", "target", "started_at", "retry")})


def _variations_by_item(db, ids: Sequence[str]) -> dict[str, list[dict[str, Any]]]:
    """Live (not gone) variations of the given items, in the typed shape `units_for_item` reads."""
    variations: dict[str, list[dict[str, Any]]] = {item_id: [] for item_id in ids}
    for row in db.query(
        MlItemVariation.item_id,
        MlItemVariation.variation_id,
        MlItemVariation.seller_sku,
        MlItemVariation.seller_custom_field,
    ).filter(MlItemVariation.item_id.in_(list(ids)), MlItemVariation.gone_at.is_(None)):
        variations[row.item_id].append(
            {
                "variation_id": row.variation_id,
                "seller_sku": row.seller_sku,
                "seller_custom_field": row.seller_custom_field,
            }
        )
    return variations


_ITEM_COLUMNS = (MlItem.item_id, MlItem.seller_sku, MlItem.seller_custom_field, MlItem.official_store_id, MlItem.brand)


def _typed_batch(db, cursor: Optional[str], size: int) -> list[tuple[dict[str, Any], list[dict[str, Any]]]]:
    """The next `size` stored items after `cursor` (keyset on `item_id`) with their live variations.

    An unlocked snapshot: it only decides which items look like they need work. Whatever is evaluated
    is re-read under the item's row lock (`_evaluate_one`).
    """
    query = db.query(*_ITEM_COLUMNS).filter(MlItem.raw.isnot(None))
    if cursor is not None:
        query = query.filter(MlItem.item_id > cursor)
    items = query.order_by(MlItem.item_id).limit(size).all()
    if not items:
        return []
    variations = _variations_by_item(db, [item.item_id for item in items])
    return [(dict(item._mapping), variations[item.item_id]) for item in items]


def _evaluated_keys(db, ids: Sequence[str]) -> dict[tuple[str, int], tuple[Optional[str], Optional[datetime]]]:
    rows = db.query(
        MlItemProductLink.item_id,
        MlItemProductLink.variation_id,
        MlItemProductLink.evaluated_sku_key,
        MlItemProductLink.evaluated_at,
    ).filter(MlItemProductLink.item_id.in_(list(ids)))
    return {(r.item_id, r.variation_id): (r.evaluated_sku_key, r.evaluated_at) for r in rows}


def _needs_evaluation(units: Sequence[LinkUnit], evaluated: Mapping[tuple[str, int], Any]) -> bool:
    for unit in units:
        known = evaluated.get((unit.item_id, unit.variation_id))
        if known is None or known[1] is None or known[0] != unit.key:
            return True
    return False


def run_sweep(*, deadline: datetime, gate: Gate, now: Callable[[], datetime] = _utcnow) -> SweepResult:
    """Evaluate the links of the stored items in keyset batches until the lap ends or the deadline hits.

    An ordinary lap evaluates only units never evaluated or whose SKU key changed; a forced lap
    (the product catalog fingerprint changed, or the daily 04:30 safety net) re-evaluates every
    unit, which also refreshes the suggestion of manual units. Progress lives in `ml_pub_settings`
    (the cursor commits with each batch's work), so a stopped run resumes where it ended.
    """
    result = SweepResult()
    started = now()
    with database.get_background_db() as db:
        _set_timeouts(db)
        state = _plan_lap(db, _load_state(db), started)
        _write_setting(db, SWEEP_STATE_KEY, state.as_value(), started)
    result.forced = state.force
    while True:
        batch_now = now()
        if batch_now >= deadline:
            result.stopped = STOPPED_DEADLINE
            return result
        events_enabled = gate()
        if events_enabled is None:
            result.stopped = STOPPED_DISABLED
            return result
        with database.get_background_db() as db:  # unlocked snapshot, no write
            _set_timeouts(db)
            batch = _typed_batch(db, state.cursor, SWEEP_BATCH)
            evaluated = _evaluated_keys(db, [typed["item_id"] for typed, _ in batch])
        result.batches += 1 if batch else 0
        for typed, variations in batch:
            _sweep_item(typed, variations, evaluated, state, batch_now, events_enabled, result)
        with database.get_background_db() as db:  # progress, committed after the batch's per-item work
            if batch:
                state.cursor = batch[-1][0]["item_id"]
            if len(batch) < SWEEP_BATCH:
                _finish_lap(db, state, batch_now)
                result.complete = True
            else:
                _write_setting(db, SWEEP_STATE_KEY, state.as_value(), batch_now)
        if result.complete:
            return result


def _set_timeouts(db) -> None:
    db.execute(text(f"SET LOCAL lock_timeout = '{SWEEP_LOCK_TIMEOUT}'"))
    db.execute(text(f"SET LOCAL statement_timeout = '{SWEEP_STATEMENT_TIMEOUT}'"))


def _sweep_item(
    typed: Mapping[str, Any],
    variations: Sequence[Mapping[str, Any]],
    evaluated: Mapping[tuple[str, int], Any],
    state: _SweepState,
    now: datetime,
    events_enabled: bool,
    result: SweepResult,
) -> None:
    result.items += 1
    units = units_for_item(typed, variations)
    if not state.force and not _needs_evaluation(units, evaluated):
        result.units.skipped += len(units)
        return
    try:
        outcome = _evaluate_one(typed["item_id"], force=state.force, now=now, events_enabled=events_enabled)
    except Exception:  # noqa: BLE001 -- one item must not stop the lap; the next lap retries it
        result.errors += 1
        state.retry = state.retry or state.force
        logger.exception("product links sweep failed for %s", typed["item_id"])
        return
    if outcome is None:
        result.contended += 1
        state.retry = state.retry or state.force
        return
    result.units.add(outcome)


def _evaluate_one(item_id: str, *, force: bool, now: datetime, events_enabled: bool) -> Optional[EvaluationResult]:
    """Evaluate one item in its own short transaction, on its CURRENT state.

    The item row is share-locked (`SKIP LOCKED`) and its SKU fields re-read under that lock, so a fetch
    that committed after the sweep's snapshot is never evaluated against stale data, and a fetch in
    flight is neither waited for nor blocked for longer than this one item (it evaluates the item itself).
    Returns None when the row is busy. The transaction ends here, so no link-row lock outlives the item.
    """
    with database.get_background_db() as db:
        _set_timeouts(db)
        row = (
            db.query(*_ITEM_COLUMNS)
            .filter(MlItem.item_id == item_id, MlItem.raw.isnot(None))
            .with_for_update(read=True, skip_locked=True, of=MlItem)
            .first()
        )
        if row is None:
            return None
        variations = _variations_by_item(db, [item_id])[item_id]
        return evaluate_item(
            db, item_id, dict(row._mapping), variations, now=now, events_enabled=events_enabled, force=force
        )


def _finish_lap(db, state: _SweepState, now: datetime) -> None:
    """The lap ended: a forced lap that evaluated every item records the catalog it converged to.

    A lap with a failed or busy item records nothing, so the next run forces another lap.
    """
    if state.force and not state.retry:
        _write_setting(db, FINGERPRINT_KEY, state.target, now)
        _write_setting(db, LAST_FULL_PASS_KEY, state.started_at, now)
    _write_setting(db, SWEEP_STATE_KEY, _SweepState().as_value(), now)


# --- coverage report (read-only) ---------------------------------------------------------------------

CLASSES = (
    "linked_auto",
    "linked_manual",
    "manual_none",
    "unmatched_no_key",
    "unmatched_key_not_found",
    "conflict",
    "dangling",
    "never_evaluated",
)
DEFAULT_SAMPLE_SIZE = 10
COVERAGE_STATEMENT_TIMEOUT = "5s"

# Every unit is classified exactly once: the stored links first, then the units that have no link row
# yet (items without live variations have an item-level unit, every live variation has its own).
_UNITS_CTE = """
WITH units AS (
    SELECT coalesce(i.status, 'unknown') AS item_status, (l.variation_id > 0) AS is_variation,
           l.item_id, l.variation_id,
           CASE
               WHEN l.evaluated_at IS NULL THEN 'never_evaluated'
               WHEN l.producto_item_id IS NOT NULL
                    AND NOT EXISTS (SELECT 1 FROM productos_erp p WHERE p.item_id = l.producto_item_id)
                   THEN 'dangling'
               WHEN l.source = 'manual_none' THEN 'manual_none'
               WHEN l.source = 'manual' THEN 'linked_manual'
               WHEN l.match_status = 'linked' THEN 'linked_auto'
               WHEN l.match_status = 'conflict' THEN 'conflict'
               WHEN l.matched_sku IS NULL THEN 'unmatched_no_key'
               ELSE 'unmatched_key_not_found'
           END AS cls
    FROM ml_item_product_links l
    LEFT JOIN ml_items i ON i.item_id = l.item_id
    UNION ALL
    SELECT coalesce(i.status, 'unknown'), false, i.item_id, 0, 'never_evaluated'
    FROM ml_items i
    WHERE i.raw IS NOT NULL
      AND NOT EXISTS (SELECT 1 FROM ml_item_variations v WHERE v.item_id = i.item_id AND v.gone_at IS NULL)
      AND NOT EXISTS (SELECT 1 FROM ml_item_product_links l WHERE l.item_id = i.item_id AND l.variation_id = 0)
    UNION ALL
    SELECT coalesce(i.status, 'unknown'), true, v.item_id, v.variation_id, 'never_evaluated'
    FROM ml_item_variations v
    LEFT JOIN ml_items i ON i.item_id = v.item_id
    WHERE v.gone_at IS NULL
      AND NOT EXISTS (
          SELECT 1 FROM ml_item_product_links l WHERE l.item_id = v.item_id AND l.variation_id = v.variation_id
      )
)
"""
_COUNTS_SQL = _UNITS_CTE + "SELECT item_status, is_variation, cls, count(*) FROM units GROUP BY 1, 2, 3"
_SAMPLES_SQL = (
    _UNITS_CTE
    + """
SELECT cls, item_id, variation_id FROM (
    SELECT cls, item_id, variation_id,
           row_number() OVER (PARTITION BY cls ORDER BY item_id, variation_id) AS rn
    FROM units
) ranked
WHERE rn <= :size
ORDER BY cls, item_id, variation_id
"""
)
_MANUAL_DIFFERS_SQL = """
SELECT count(*) FROM ml_item_product_links
WHERE source <> 'sku_auto' AND suggestion_status = 'linked'
  AND suggested_producto_item_id IS DISTINCT FROM producto_item_id
"""


def coverage(db, *, sample_size: int = DEFAULT_SAMPLE_SIZE) -> dict[str, Any]:
    """Link coverage: counts per primary class by item status, item-level vs variation units, and bounded samples.

    `classes` sums to `total_units` (each unit is in exactly one primary class). `manual_differs` is
    reported beside them: manual and manual_none units whose decision differs from the SKU suggestion
    are also counted in their own class. Read-only; one pass over the link table, the items and the
    products' primary key.
    """
    db.execute(text(f"SET LOCAL statement_timeout = '{COVERAGE_STATEMENT_TIMEOUT}'"))
    classes = {name: 0 for name in CLASSES}
    by_status: dict[str, dict[str, dict[str, int]]] = {}
    for status, is_variation, cls, count in db.execute(text(_COUNTS_SQL)).all():
        classes[cls] += count
        level = by_status.setdefault(status, {"item_level": {}, "variation": {}})[
            "variation" if is_variation else "item_level"
        ]
        level[cls] = count
    samples: dict[str, list[dict[str, Any]]] = {name: [] for name in CLASSES}
    for cls, item_id, variation_id in db.execute(text(_SAMPLES_SQL), {"size": sample_size}).all():
        samples[cls].append({"item_id": item_id, "variation_id": variation_id})
    return {
        "total_units": sum(classes.values()),
        "classes": classes,
        "by_status": by_status,
        "manual_differs": db.execute(text(_MANUAL_DIFFERS_SQL)).scalar(),
        "samples": samples,
    }
