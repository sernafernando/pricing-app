"""Resource registry: what the generic store engine needs to know per resource.

A resource may only be registered with a parser AND a committed real-capture
fixture (spec "Fixture-first parsers": no parser without a capture). More
resources register here as their PRs land.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Mapping, MutableMapping, Optional, Sequence

from app.services.ml_publications.canonical import ArrayKeys
from app.services.ml_publications.diff import array_keys_for
from app.services.ml_publications.mappers import map_item
from app.services.ml_publications.parsers.description import map_description, parse_description
from app.services.ml_publications.parsers.family import map_family, parse_family
from app.services.ml_publications.parsers.items_bulk import parse_items_bulk
from app.services.ml_publications.parsers.moderation import NEGATIVE_STATES as MODERATION_NEGATIVE_STATES
from app.services.ml_publications.parsers.moderation import map_moderation, parse_moderation
from app.services.ml_publications.parsers.performance import NEGATIVE_STATES as PERFORMANCE_NEGATIVE_STATES
from app.services.ml_publications.parsers.performance import map_performance, parse_performance
from app.services.ml_publications.parsers.price_to_win import map_price_to_win, parse_price_to_win
from app.services.ml_publications.parsers.prices import map_prices, parse_prices
from app.services.ml_publications.parsers.sale_price import map_sale_price, parse_sale_price
from app.services.ml_publications.parsers.seller_promotions import map_seller_promotions, parse_seller_promotions
from app.services.ml_publications.parsers.user_product import map_user_product, parse_user_product
from app.services.ml_publications.parsers.user_product_stock import map_user_product_stock, parse_user_product_stock
from app.services.ml_publications.parsers.visits import map_visits, parse_visits


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
PROMOTIONS_RESOURCE = "promotions"
# Queue entry kinds (design D10): an item, a user product (stock/UP notifications) or a family. The kind
# is also the entity a fetcher's path takes the id of.
ITEM_KIND = "item"
USER_PRODUCT_KIND = "user_product"
FAMILY_KIND = "family"
COMPETITION_RESOURCE = "competition"
MODERATION_RESOURCE = "moderation"
PERFORMANCE_RESOURCE = "performance"
VISITS_RESOURCE = "visits"
REFRESH_RESOURCES: tuple[str, ...] = (
    BUNDLE_RESOURCE,
    CORE_RESOURCE,
    "description",
    "prices",
    "sale_price",
    PROMOTIONS_RESOURCE,
    "user_product",
    "stock",
    "family",
    COMPETITION_RESOURCE,
    MODERATION_RESOURCE,
    PERFORMANCE_RESOURCE,
    VISITS_RESOURCE,
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

# Sub-resources, named as in REFRESH_RESOURCES. Their fetchers arrive in later PRs.
for _name, _keys, _mapper, _parser, _fixture, _array_keys, _negative_states in (
    ("description", ("item_id",), map_description, parse_description, "description_20261006.json", {}, {}),
    ("prices", ("item_id",), map_prices, parse_prices, "prices_20261006.json", {}, {}),
    ("sale_price", ("item_id",), map_sale_price, parse_sale_price, "sale_price_20261006.json", {}, {}),
    (
        PROMOTIONS_RESOURCE,
        ("item_id",),
        map_seller_promotions,
        parse_seller_promotions,
        "seller_promotions_20261006.json",
        array_keys_for("promotions"),
        {},
    ),
    (
        "user_product",
        ("user_product_id",),
        map_user_product,
        parse_user_product,
        "user_product_20261006.json",
        {},
        {},
    ),
    (
        "stock",
        ("user_product_id",),
        map_user_product_stock,
        parse_user_product_stock,
        "user_product_stock_20261006.json",
        array_keys_for("stock"),
        {},
    ),
    ("family", ("family_id",), map_family, parse_family, "family_20261006.json", {}, {}),
    (
        COMPETITION_RESOURCE,
        ("item_id",),
        map_price_to_win,
        parse_price_to_win,
        "price_to_win_20261006.json",
        {},
        {},
    ),
    (
        PERFORMANCE_RESOURCE,
        ("item_id",),
        map_performance,
        parse_performance,
        "performance_20261006.json",
        {},
        PERFORMANCE_NEGATIVE_STATES,
    ),
    (
        MODERATION_RESOURCE,
        ("item_id",),
        map_moderation,
        parse_moderation,
        "moderation_20261006.json",
        {},
        MODERATION_NEGATIVE_STATES,
    ),
    (VISITS_RESOURCE, ("item_id",), map_visits, parse_visits, "visits_20261006.json", array_keys_for("visits"), {}),
):
    register(
        ResourceSpec(
            name=_name,
            key_columns=_keys,
            mapper=_mapper,
            parser=_parser,
            fixture=_fixture,
            array_keys=_array_keys,
            negative_states=_negative_states,
        )
    )
