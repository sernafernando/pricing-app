"""Free-text search `q` (spec `ml-sales-search`, R25/R25a/R26/R27).

Applied to an already-scoped (seller + date + status-filtered) query, so
search INTERSECTS with the active filters/toggles rather than replacing
them (R26) -- the caller (`filters.build_scope`) applies it last, after
the status filters.

R25a is the load-bearing rule: free text matches the sale's OWN item
fields (`ml_order_items_ops.title`, `ml_order_items_ops.seller_sku`),
never through `producto_item_id` (the frozen-cost join used by the
product-level facets). An order-item with no `ml_order_item_costos` row
still has its own `title`/`seller_sku` from ingestion, so it must still be
findable by them.
"""

from __future__ import annotations

import re
from typing import Optional

from sqlalchemy import false, or_
from sqlalchemy.orm import Query, Session

from app.models.ml_orders_ops import MlOrderItemOps, MlOrdersOps

_MLA_ITEM_ID_RE = re.compile(r"^MLA\d+$", re.IGNORECASE)
_MIN_FREE_TEXT_LEN = 3


# `order_id`/`pack_id` are BIGINT: anything outside this range cannot match,
# and comparing it would raise in the driver instead of returning no rows.
_BIGINT_MIN = -(2**63)
_BIGINT_MAX = 2**63 - 1

# The user's text is DATA, not a pattern: without escaping, a search for
# "%%%" would match every sale and "_" would act as a single-character
# wildcard.
_LIKE_ESCAPE = "\\"


def _escape_like(text: str) -> str:
    return (
        text.replace(_LIKE_ESCAPE, _LIKE_ESCAPE * 2).replace("%", _LIKE_ESCAPE + "%").replace("_", _LIKE_ESCAPE + "_")
    )


# PERFORMANCE NOTE: the item subquery is an unanchored ILIKE over
# `ml_order_items_ops.title`/`seller_sku`, not bounded by seller or date, and
# a listing request runs it several times (rows, total and the facet
# counts). It is fine at today's volume; if it stops being fine, the fixes
# are a `pg_trgm` index (already an open question in the design) or bounding
# the subquery to the same scope as the outer query.
def apply_search(query: Query, db: Session, q: Optional[str]) -> Query:
    """Applies `q` to an order-level query.

    - No `q` (`None` or blank) -> query unchanged.
    - All digits -> `order_id` OR `pack_id` (matches a pack too, R25
      scenario 1).
    - `^MLA\\d+$` (case-insensitive) -> `item_id`, via `ml_order_items_ops`.
    - Otherwise, 3+ chars -> ILIKE on `buyer_nickname` and the sale's OWN
      item fields (`title`, `seller_sku`), via `ml_order_items_ops`.
    - Anything else (fewer than 3 chars, not digits, not an MLA id) ->
      matches nothing explicitly (R27: an empty/no-match search state is
      explicit, never a silent "no filter" or an error).
    """
    if q is None:
        return query
    text = q.strip()
    if not text:
        return query

    if text.isdigit():
        # `str.isdigit()` is True for unicode digits too ("²³"), which `int()`
        # rejects, and a long run of ASCII digits overflows the BIGINT
        # order_id/pack_id columns. Both must read as "matches nothing"
        # (R27), never as a 500.
        try:
            value = int(text)
        except ValueError:
            return query.filter(false())
        if not (_BIGINT_MIN <= value <= _BIGINT_MAX):
            return query.filter(false())
        return query.filter(or_(MlOrdersOps.order_id == value, MlOrdersOps.pack_id == value))

    if _MLA_ITEM_ID_RE.match(text):
        item_order_ids = db.query(MlOrderItemOps.order_id).filter(MlOrderItemOps.item_id.ilike(text)).scalar_subquery()
        return query.filter(MlOrdersOps.order_id.in_(item_order_ids))

    if len(text) < _MIN_FREE_TEXT_LEN:
        return query.filter(false())

    like = f"%{_escape_like(text)}%"
    item_order_ids = (
        db.query(MlOrderItemOps.order_id)
        .filter(
            or_(
                MlOrderItemOps.title.ilike(like, escape=_LIKE_ESCAPE),
                MlOrderItemOps.seller_sku.ilike(like, escape=_LIKE_ESCAPE),
            )
        )
        .scalar_subquery()
    )
    return query.filter(
        or_(MlOrdersOps.buyer_nickname.ilike(like, escape=_LIKE_ESCAPE), MlOrdersOps.order_id.in_(item_order_ids))
    )
