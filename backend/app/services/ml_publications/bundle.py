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
    CORE_RESOURCE,
    FAMILY_KIND,
    ITEM_KIND,
    PROMOTIONS_RESOURCE,
    RESOURCES,
    USER_PRODUCT_KIND,
)
from app.services.ml_publications.subresource_store import MODELS


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
    )
}

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


def _applies_to(name: str, kind: str) -> bool:
    """Whether a fetcher can run for an entry of `kind`: an item entry reaches every fetcher (the
    user product and family through the item's row); a user product or family entry only its own."""
    return kind == ITEM_KIND or FETCHERS[name].entity == kind


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
            if not has_fetcher(name) or name in gated_off:
                dropped.add(name)
            elif _applies_to(name, kind):  # another entity's resource is not applicable, not dropped
                wanted[name] = False
    for name in requested:
        if name in (CORE_RESOURCE, BUNDLE_RESOURCE):
            if kind == ITEM_KIND:
                needs_core = True
            elif name == CORE_RESOURCE:
                dropped.add(name)
        elif has_fetcher(name) and _applies_to(name, kind) and name in bundle_resources and name not in gated_off:
            wanted[name] = True
        else:
            dropped.add(name)
    return Plan(needs_core=needs_core, wanted=wanted, dropped=frozenset(dropped))


def min_age_seconds(resource: str, configured: Mapping[str, Any]) -> int:
    """Minimum seconds between bundle fetches of `resource` (the `min_age_seconds` setting; 0 when unset)."""
    value = configured.get(resource, 0)
    return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else 0


def is_due(*, explicit: bool, min_age: int, last_checked_at: Optional[datetime], now: datetime) -> bool:
    if explicit or min_age <= 0 or last_checked_at is None:
        return True
    return now - last_checked_at >= timedelta(seconds=min_age)


def last_checked(resource: str, keys: Sequence[str]) -> Dict[str, datetime]:
    """`last_checked_at` of the stored `resource` rows of `keys` (never checked: absent). The key is
    the id the resource's row is keyed by: item, user product or family id."""
    if not keys:
        return {}
    model = MODELS[resource]
    column = getattr(model, RESOURCES[resource].key_columns[0])
    with database.get_background_db() as db:
        rows = (
            db.query(column, model.last_checked_at)
            .filter(column.in_([_key_value(column, key) for key in keys]), model.last_checked_at.isnot(None))
            .all()
        )
    return {str(key): checked for key, checked in rows}


def _key_value(column, key: str):
    """The key as its column type holds it (a family id is an integer)."""
    return int(key) if column.type.python_type is int else key


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
        ids = {}
        if user_product_id:
            ids[USER_PRODUCT_KIND] = user_product_id
        if family_id is not None:
            ids[FAMILY_KIND] = str(family_id)
        linked[item_id] = ids
    return linked
