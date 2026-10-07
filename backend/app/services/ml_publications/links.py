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
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Mapping, Optional, Sequence

from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.models.ml_publications import MlChangeLog, MlItemProductLink
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
