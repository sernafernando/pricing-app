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
from app.services.ml_publications.resources import BUNDLE_RESOURCE, CORE_RESOURCE, PROMOTIONS_RESOURCE
from app.services.ml_publications.subresource_store import MODELS


@dataclass(frozen=True)
class SubFetcher:
    """One sub-resource endpoint of an item: its counter family, path and fixed query."""

    resource: str  # registry name; also the endpoint family of the ML counters and pacing
    path: str  # `{item_id}` is substituted
    params: Optional[Mapping[str, str]] = None

    def request(self, item_id: str) -> tuple[str, Optional[Mapping[str, str]]]:
        return self.path.format(item_id=item_id), self.params


FETCHERS: Dict[str, SubFetcher] = {
    fetcher.resource: fetcher
    for fetcher in (
        SubFetcher("description", "/items/{item_id}/description"),
        SubFetcher("prices", "/items/{item_id}/prices"),
        # The marketplace price is the one the buyer pays and the one the typed columns follow.
        SubFetcher("sale_price", "/items/{item_id}/sale_price", {"context": "channel_marketplace"}),
        # The seller's promotions of the item, fetched from ML (never read from the bridge mirror).
        SubFetcher(PROMOTIONS_RESOURCE, "/seller-promotions/items/{item_id}", {"app_version": "v2"}),
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


def plan(requested: Sequence[str], bundle_resources: Sequence[str], gated_off: frozenset = frozenset()) -> Plan:
    """What an entry that requests `requested` needs, given the enabled `bundle_resources`.

    A resource in `gated_off` (its flag in `FLAG_GATES` is off) is dropped like one with no fetcher,
    whether the entry names it or the bundle would include it."""
    needs_core = False
    wanted: Dict[str, bool] = {}
    dropped: set[str] = set()
    if BUNDLE_RESOURCE in requested:
        for name in bundle_resources:
            if name in (CORE_RESOURCE, BUNDLE_RESOURCE):
                continue
            if has_fetcher(name) and name not in gated_off:
                wanted[name] = False
            else:
                dropped.add(name)
    for name in requested:
        if name in (CORE_RESOURCE, BUNDLE_RESOURCE):
            needs_core = True
        elif has_fetcher(name) and name in bundle_resources and name not in gated_off:
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


def last_checked(resource: str, item_ids: Sequence[str]) -> Dict[str, datetime]:
    """`last_checked_at` of the stored `resource` rows of `item_ids` (items never checked are absent)."""
    if not item_ids:
        return {}
    model = MODELS[resource]
    with database.get_background_db() as db:
        rows = (
            db.query(model.item_id, model.last_checked_at)
            .filter(model.item_id.in_(list(item_ids)), model.last_checked_at.isnot(None))
            .all()
        )
    return {item_id: checked for item_id, checked in rows}
