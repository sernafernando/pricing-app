"""Resource registry: what the generic store engine needs to know per resource.

A resource may only be registered with a parser AND a committed real-capture
fixture (spec "Fixture-first parsers": no parser without a capture). More
resources register here as their PRs land.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Mapping, MutableMapping, Optional, Sequence

from app.services.ml_publications.canonical import ArrayKeys
from app.services.ml_publications.mappers import map_item
from app.services.ml_publications.parsers.items_bulk import parse_items_bulk


@dataclass(frozen=True)
class ResourceSpec:
    name: str
    key_columns: tuple[str, ...]
    mapper: Callable[..., Any]
    parser: Optional[Callable[..., Any]]
    fixture: str  # file under tests/fixtures/ml_publications backing the parser (existence checked by tests)
    array_keys: ArrayKeys = field(default_factory=dict)
    # HTTP status -> state name for declared negative answers that are states, not errors.
    negative_states: Mapping[int, str] = field(default_factory=dict)


# Names a queue entry may carry in `resources` (design D12): the single list read by the refresh
# handler and the enqueue CLI. `core` is the item itself (`/items/bulk`), `bundle` means "the item
# plus every sub-resource enabled in `bundle_resources`"; the rest are the sub-resources whose
# fetchers ship in later PRs (naming one earlier is harmless: the handler drops it uncharged).
CORE_RESOURCE = "core"
BUNDLE_RESOURCE = "bundle"
REFRESH_RESOURCES: tuple[str, ...] = (
    BUNDLE_RESOURCE,
    CORE_RESOURCE,
    "description",
    "prices",
    "sale_price",
    "promotions",
    "user_product",
    "stock",
    "family",
    "competition",
    "moderation",
    "performance",
    "visits",
)

RESOURCES: dict[str, ResourceSpec] = {}


def register(spec: ResourceSpec, registry: Optional[MutableMapping[str, ResourceSpec]] = None) -> ResourceSpec:
    target = RESOURCES if registry is None else registry
    if spec.parser is None:
        raise ValueError(f"resource {spec.name!r} has no parser")
    if not spec.fixture:
        raise ValueError(f"resource {spec.name!r} names no fixture")  # existence is asserted by the test suite
    if spec.name in target:
        raise ValueError(f"resource {spec.name!r} is already registered")
    target[spec.name] = spec
    return spec


def key_columns_of(name: str) -> Sequence[str]:
    return RESOURCES[name].key_columns


register(
    ResourceSpec(
        name="item",
        key_columns=("item_id",),
        mapper=map_item,
        parser=parse_items_bulk,
        fixture="items_bulk_capture_20261006_015628.json",
    )
)
