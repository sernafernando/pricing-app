"""A publication's listing kind (Clásica, 3/6/9/12 cuotas) and its sort rank, as SQL.

Métricas ML and Publicaciones ML list publications Clásica first, then 3, 6, 9 and 12 cuotas (owner, 2026-11-02),
and both paginate on the server: the kind has to be a column the ORDER BY reads before LIMIT/OFFSET, not a
Python step after it. The decision is `pricelist_resolver`'s (the pricelist each kind maps to), written as one SQL
CASE over the same three inputs; a parity test pins the two together.

* `gold_special` is `clasica`, or `clasica_cofinanciada` with the `pcj-co-funded` tag (ML co-funds the
  installments): same rank, the badge tells them apart.
* `gold_pro` follows its campaign: the first campaign tag in tag order, else the `installments_campaign` sale
  term; no campaign (or `6x_campaign`) is `cuotas_6`. An unknown campaign has no kind: it keeps `gold_pro`.
* Any other listing type keeps its raw id and sorts after the known kinds; no listing type at all sorts last.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import Integer, Text, case, func, literal, type_coerce
from sqlalchemy.dialects.postgresql import ARRAY

from app.services.ml_publications.pricelist_resolver import CAMPAIGN_TAGS, CO_FUNDED_TAG

KIND_RANKS: dict[str, int] = {
    "clasica": 0,
    "clasica_cofinanciada": 0,
    "cuotas_3": 1,
    "cuotas_6": 2,
    "cuotas_9": 3,
    "cuotas_12": 4,
}
OTHER_RANK = 5
NO_TYPE_RANK = 6

_KIND_BY_CAMPAIGN = {
    "3x_campaign": "cuotas_3",
    "6x_campaign": "cuotas_6",
    "9x_campaign": "cuotas_9",
    "12x_campaign": "cuotas_12",
}


def _campaign(tags: Any, sale_terms_campaign: Any) -> Any:
    """The resolver's campaign: the campaign tag that comes FIRST in `tags`, else the sale term. `least` skips the
    NULL positions of the tags the item does not carry."""
    positions = {tag: func.array_position(tags, literal(tag)) for tag in CAMPAIGN_TAGS}
    first = func.least(*positions.values())
    return case(
        *((position == first, literal(tag)) for tag, position in positions.items()),
        else_=sale_terms_campaign,
    )


def listing_kind(listing_type_id: Any, tags: Any, sale_terms_campaign: Any) -> Any:
    """The kind of one publication (Postgres only: it reads the `tags` array). `tags` is read as a text array
    whatever type its column carries, so `@>` and `array_position` compile as array operators."""
    tags = func.coalesce(type_coerce(tags, ARRAY(Text)), literal([], ARRAY(Text)))
    campaign = _campaign(tags, sale_terms_campaign)
    # A simple CASE reads the campaign once for all its values: the publications list orders its whole set by this.
    gold_pro = case(
        {value: literal(kind) for value, kind in _KIND_BY_CAMPAIGN.items()},
        value=campaign,
        else_=case((campaign.is_(None), literal("cuotas_6")), else_=listing_type_id),
    )
    return case(
        (
            listing_type_id == "gold_special",
            case((tags.contains([CO_FUNDED_TAG]), literal("clasica_cofinanciada")), else_=literal("clasica")),
        ),
        (listing_type_id == "gold_pro", gold_pro),
        else_=listing_type_id,
    )


def listing_kind_from_type(listing_type_id: Any) -> Any:
    """The kind with no tags or campaign to read (the SQLite test database): Clásica, or 6 cuotas for premium."""
    return case(
        (listing_type_id == "gold_special", literal("clasica")),
        (listing_type_id == "gold_pro", literal("cuotas_6")),
        else_=listing_type_id,
    )


def listing_rank(kind: Any) -> Any:
    """The sort rank of a kind: the known kinds in installments order, then any other type, then none. A simple
    CASE reads the kind once for all the known ones."""
    return case(
        {name: literal(rank, Integer) for name, rank in KIND_RANKS.items()},
        value=kind,
        else_=case((kind.is_(None), literal(NO_TYPE_RANK, Integer)), else_=literal(OTHER_RANK, Integer)),
    )
