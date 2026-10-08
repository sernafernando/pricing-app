"""The markup of a page or of a whole filtered set of publications (design §4.4).

One entry point, `compute_markups`, for both paths:

* page path: `item_ids` (the rows of the page, at most `MAX_LIMIT`): the inputs of those publications only;
* set-wide path: `f` (a PM-resolved filter): the inputs of every publication of the filtered set, for sorting
  and filtering by markup.

Either way the cost is a fixed number of statements: three for the inputs (`markup_inputs`), one shipping batch
(`resolver_costos_envio_batch`, once per request, for the distinct priceable products) and the pricing context
(`build_pricing_context`, built by the caller or here), then a Python loop over the pure functions
(`markup.unit_markup`, `markup.aggregate_publication`). Nothing here names the product catalog.

`db` reads the publication store; `pricing_db` reads the pricing tables, the shipping history and the sales (in
production both are the application session).
"""

from __future__ import annotations

import time
from collections import Counter
from dataclasses import dataclass
from typing import Mapping, Optional, Sequence

from sqlalchemy.orm import Session

from app.services.envio_real_service import resolver_costos_envio_batch
from app.services.ml_publications.view.filters import MarkupFilter, PublicationFilter
from app.services.ml_publications.view.markup import PublicationMarkup, UnitInputs, aggregate_publication, unit_markup
from app.services.ml_publications.view.markup_inputs import PublicationInputs, fetch_inputs
from app.services.pricing_context import PricingContext, build_pricing_context


@dataclass(frozen=True)
class MarkupQuery:
    """What a list request asks of the markup: the session the pricing tables are read through and the
    `markup_*` filter. Its presence means the caller may see margins (`ml_metricas.ver_ganancia`)."""

    pricing_db: Session
    filter: MarkupFilter = MarkupFilter()


@dataclass(frozen=True)
class MarkupStats:
    """What a request computed: publications with a value, why the others have none, and the time it took."""

    computed: int
    null_by_reason: Mapping[str, int]
    ms: float


@dataclass(frozen=True)
class ItemMarkup:
    markup: PublicationMarkup


@dataclass(frozen=True)
class MarkupResult:
    items: Mapping[str, ItemMarkup]
    stats: MarkupStats


def _units(inputs: PublicationInputs) -> list[UnitInputs]:
    return [inputs.item_unit, *(u for u in inputs.variation_units if u is not None)]


def _priceable_products(publications: Sequence[PublicationInputs]) -> list[int]:
    """Distinct products whose cost is usable: only those are priced, so only their shipping is looked up."""
    return sorted(
        {
            unit.producto_item_id
            for pub in publications
            for unit in _units(pub)
            if unit.producto_item_id is not None and unit.costo is not None and unit.costo > 0
        }
    )


def price_publication(ctx: PricingContext, inputs: PublicationInputs, envio: Mapping[int, float]) -> PublicationMarkup:
    """One publication: its item-level unit and each variation, priced and aggregated."""
    item_unit = unit_markup(ctx, inputs.item_unit, envio)
    own = [unit_markup(ctx, unit, envio) if unit is not None else None for unit in inputs.variation_units]
    return aggregate_publication(item_unit, own)


def compute_markups(
    db: Session,
    pricing_db: Session,
    *,
    item_ids: Optional[Sequence[str]] = None,
    f: Optional[PublicationFilter] = None,
    ctx: Optional[PricingContext] = None,
) -> MarkupResult:
    """Markup of the given publications (page path) or of a filter's whole set (set-wide path)."""
    started = time.perf_counter()
    inputs = fetch_inputs(db, item_ids=item_ids, f=f)
    publications = list(inputs.values())
    products = _priceable_products(publications)
    envio: Mapping[int, float] = resolver_costos_envio_batch(pricing_db, products) if products else {}
    ctx = ctx or build_pricing_context(pricing_db)
    items = {pub.item_id: ItemMarkup(price_publication(ctx, pub, envio)) for pub in publications}
    unpriced = Counter(m.markup.reason for m in items.values() if m.markup.worst is None)
    stats = MarkupStats(
        computed=len(items) - sum(unpriced.values()),
        null_by_reason=dict(unpriced),
        ms=round((time.perf_counter() - started) * 1000, 1),
    )
    return MarkupResult(items, stats)
