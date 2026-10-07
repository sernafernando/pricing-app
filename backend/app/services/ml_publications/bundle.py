"""Item bundle policy of the refresh handler (design D12): which sub-resources a queue entry
fetches, behind the `bundle_resources` gate and per-resource minimum ages.

Pure planning plus one read of the last check times. A resource is fetched only when it has a
fetcher here AND is listed in the `bundle_resources` setting (default `["core"]`), so shipping a
fetcher makes no ML call until an operator enables it. An entry asks for a resource either
implicitly (the `bundle` name: the item plus everything enabled, each subject to its minimum age)
or explicitly (the resource named, which bypasses the minimum age: topic-specific or manual).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Dict, Mapping, Optional, Sequence

from app.core import database
from app.models.ml_publications import MlItem
from app.services.ml_publications.resources import (
    BUNDLE_RESOURCE,
    COMPETITION_RESOURCE,
    CORE_RESOURCE,
    FAMILY_KIND,
    ITEM_KIND,
    MODERATION_RESOURCE,
    PERFORMANCE_RESOURCE,
    PROMOTIONS_RESOURCE,
    RESOURCES,
    USER_PRODUCT_KIND,
    VISITS_RESOURCE,
)
from app.services.ml_publications.subresource_store import MODELS, InvalidKey, typed_key


@dataclass(frozen=True)
class SubFetcher:
    """One sub-resource endpoint: its counter family, path and fixed query.

    `entity` is the kind of entity whose id the path takes and the state row is keyed by: an item, a
    user product or a family. An item entry reaches the user product and the family of the item through
    the stored item row."""

    resource: str  # registry name; also the endpoint family of the ML counters and pacing
    path: str  # `{id}` is substituted
    params: Optional[Mapping[str, str]] = None
    entity: str = ITEM_KIND

    def request(self, entity_id: str) -> tuple[str, Optional[Mapping[str, str]]]:
        return self.path.format(id=entity_id), self.params


FETCHERS: Dict[str, SubFetcher] = {
    fetcher.resource: fetcher
    for fetcher in (
        SubFetcher("description", "/items/{id}/description"),
        SubFetcher("prices", "/items/{id}/prices"),
        # The marketplace price is the one the buyer pays and the one the typed columns follow.
        SubFetcher("sale_price", "/items/{id}/sale_price", {"context": "channel_marketplace"}),
        # The seller's promotions of the item, fetched from ML (never read from the bridge mirror).
        SubFetcher(PROMOTIONS_RESOURCE, "/seller-promotions/items/{id}", {"app_version": "v2"}),
        # The user product of the item and its stock; `stock` is the endpoint with its own pacing sub-budget.
        SubFetcher("user_product", "/user-products/{id}", entity=USER_PRODUCT_KIND),
        SubFetcher("stock", "/user-products/{id}/stock", entity=USER_PRODUCT_KIND),
        # The family the item belongs to (`/sites/MLA/user-products-families/{family_id}`).
        SubFetcher("family", "/sites/MLA/user-products-families/{id}", entity=FAMILY_KIND),
        # Catalog buy-box competition; only catalog listings have one (`is_applicable`).
        SubFetcher(COMPETITION_RESOURCE, "/items/{id}/price_to_win", {"version": "v2"}),
        # Last moderation; `404 {"Status": 404}` means "none" and is stored as a state (parsers/moderation.py).
        SubFetcher(MODERATION_RESOURCE, "/moderations/last_moderation/{id}-ITM"),
        # Note `item`, singular. A catalog product item answers a 400 that is stored as a state.
        SubFetcher(PERFORMANCE_RESOURCE, "/item/{id}/performance"),
        SubFetcher(VISITS_RESOURCE, "/items/{id}/visits/time_window", {"last": "30", "unit": "day"}),
    )
}

# Never part of the bundle (design D12: no notification topic, too costly per sale-triggered event): an entry
# reaches them only by naming them, which the sweeps do. Listing them in `bundle_resources` enables the named
# request; the bundle itself skips them.
SWEEP_ONLY: frozenset = frozenset({PERFORMANCE_RESOURCE, VISITS_RESOURCE})

# Resources that need their own flag on top of being listed in `bundle_resources` (design D14: the
# promotions endpoint is shared with the bridge's ML application, so it has a separate kill point).
FLAG_GATES: Dict[str, str] = {PROMOTIONS_RESOURCE: "promotions.enabled"}


def has_fetcher(resource: str) -> bool:
    return resource in FETCHERS


@dataclass(frozen=True)
class Plan:
    needs_core: bool
    # sub-resource -> asked for by name (True: bypasses the minimum age) or through the bundle (False)
    wanted: Mapping[str, bool] = field(default_factory=dict)
    # requested names that cannot run now: no fetcher, or not enabled in `bundle_resources`
    dropped: frozenset = frozenset()


def applies_to_kind(name: str, kind: str) -> bool:
    """Whether resource `name` is meant for entries of `kind`: an item entry has the core and every fetcher;
    a user product or family entry only the fetchers of its own entity."""
    return kind == ITEM_KIND or (has_fetcher(name) and FETCHERS[name].entity == kind)


def plan(
    requested: Sequence[str],
    bundle_resources: Sequence[str],
    gated_off: frozenset = frozenset(),
    kind: str = ITEM_KIND,
) -> Plan:
    """What an entry of `kind` that requests `requested` needs, given the enabled `bundle_resources`.

    A resource in `gated_off` (its flag in `FLAG_GATES` is off) is dropped like one with no fetcher,
    whether the entry names it or the bundle would include it. Only an item entry has a core: the
    `bundle` of a user product or family entry is its own resources, and a resource of another entity
    named on it is dropped like one with no fetcher (uncharged)."""
    needs_core = False
    wanted: Dict[str, bool] = {}
    dropped: set[str] = set()
    if BUNDLE_RESOURCE in requested:
        for name in bundle_resources:
            if name in (CORE_RESOURCE, BUNDLE_RESOURCE):
                continue
            if not applies_to_kind(name, kind):
                continue  # not meant for this entity (item resources, other entities): not applicable, not dropped
            if name in SWEEP_ONLY and has_fetcher(name) and name not in gated_off:
                continue  # never part of the bundle: reached only by naming it
            if not has_fetcher(name) or name in gated_off:
                dropped.add(name)
            else:
                wanted[name] = False
    for name in requested:
        if name in (CORE_RESOURCE, BUNDLE_RESOURCE):
            if kind == ITEM_KIND:
                needs_core = True
            elif name == CORE_RESOURCE:
                dropped.add(name)
        elif has_fetcher(name) and applies_to_kind(name, kind) and name in bundle_resources and name not in gated_off:
            wanted[name] = True
        else:
            dropped.add(name)
    dropped.difference_update(wanted)  # a sweep-only name skipped by the bundle but asked for by name is wanted
    return Plan(needs_core=needs_core, wanted=wanted, dropped=frozenset(dropped))


# What makes an item worth a moderation request on a bundle refresh. `under_review` is the item status the
# store already scans for. The sub_status and tag values come from the ML documentation, NOT from a capture
# (no item under review or penalized existed on 2026-10-06, see the apply notes): a value missing here only
# means the bundle does not ask, and a named `moderation` entry always does.
MODERATION_STATUSES: frozenset = frozenset({"under_review"})
MODERATION_SUB_STATUSES: frozenset = frozenset({"forbidden", "waiting_for_patch"})
MODERATION_TAGS: frozenset = frozenset({"moderation_penalty"})


# Resources whose `is_applicable` reads the stored item.
SIGNAL_RESOURCES: frozenset = frozenset({COMPETITION_RESOURCE, MODERATION_RESOURCE})


@dataclass(frozen=True)
class ItemSignals:
    """The stored facts of an item that decide whether a sub-resource applies to it."""

    catalog_listing: Optional[bool]
    status: Optional[str]
    sub_status: Sequence[str] = ()
    tags: Sequence[str] = ()


def is_applicable(resource: str, signals: Optional[ItemSignals], *, explicit: bool) -> bool:
    """Whether `resource` is worth asking ML about for an item (`None`: the item is not in the store).

    Competition exists only for catalog listings, so it is never requested for anything else, not even by
    name (spec "Sub-resource not applicable"). Moderation is asked on the bundle only for an item whose state
    suggests one; a named request always goes through. Every other resource always applies."""
    if resource == COMPETITION_RESOURCE:
        return signals is not None and signals.catalog_listing is True
    if resource == MODERATION_RESOURCE and not explicit:
        return signals is not None and (
            signals.status in MODERATION_STATUSES
            or bool(MODERATION_SUB_STATUSES.intersection(signals.sub_status or ()))
            or bool(MODERATION_TAGS.intersection(signals.tags or ()))
        )
    return True


def item_signals(item_ids: Sequence[str]) -> Dict[str, ItemSignals]:
    """`ItemSignals` of the stored items among `item_ids` (items not stored are absent)."""
    if not item_ids:
        return {}
    with database.get_background_db() as db:
        rows = (
            db.query(MlItem.item_id, MlItem.catalog_listing, MlItem.status, MlItem.sub_status, MlItem.tags)
            .filter(MlItem.item_id.in_(list(item_ids)))
            .all()
        )
    return {
        item_id: ItemSignals(catalog_listing, status, sub_status or (), tags or ())
        for item_id, catalog_listing, status, sub_status, tags in rows
    }


def min_age_seconds(resource: str, configured: Mapping[str, Any]) -> int:
    """Minimum seconds between bundle fetches of `resource` (the `min_age_seconds` setting; 0 when unset)."""
    value = configured.get(resource, 0)
    return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else 0


def is_due(*, explicit: bool, min_age: int, last_checked_at: Optional[datetime], now: datetime) -> bool:
    if explicit or min_age <= 0 or last_checked_at is None:
        return True
    return now - last_checked_at >= timedelta(seconds=min_age)


def is_valid_key(resource: str, key: str) -> bool:
    """Whether `key` is an id the state table of `resource` can hold (see `subresource_store.typed_key`)."""
    try:
        typed_key(resource, key)
    except InvalidKey:
        return False
    return True


def last_checked(resource: str, keys: Sequence[str]) -> Dict[str, datetime]:
    """`last_checked_at` of the stored `resource` rows of `keys` (never checked: absent). The key is
    the id the resource's row is keyed by: item, user product or family id. The keys must already be valid
    (`is_valid_key`): the refresh handler settles an entry with an invalid id before it asks for ages."""
    if not keys:
        return {}
    model = MODELS[resource]
    column = getattr(model, RESOURCES[resource].key_columns[0])
    with database.get_background_db() as db:
        rows = (
            db.query(column, model.last_checked_at)
            .filter(column.in_([typed_key(resource, key) for key in keys]), model.last_checked_at.isnot(None))
            .all()
        )
    return {str(key): checked for key, checked in rows}


def linked_ids(item_ids: Sequence[str]) -> Dict[str, Dict[str, str]]:
    """Per stored item, the ids its user product and family resources are keyed by:
    `{item_id: {"user_product": id, "family": id}}`, a key absent when the item has none (or is unknown)."""
    if not item_ids:
        return {}
    with database.get_background_db() as db:
        rows = (
            db.query(MlItem.item_id, MlItem.user_product_id, MlItem.family_id)
            .filter(MlItem.item_id.in_(list(item_ids)))
            .all()
        )
    linked: Dict[str, Dict[str, str]] = {}
    for item_id, user_product_id, family_id in rows:
        candidates = ((USER_PRODUCT_KIND, user_product_id), (FAMILY_KIND, family_id))
        linked[item_id] = {entity: str(value) for entity, value in candidates if value}
    return linked
