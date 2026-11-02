"""The publications of a Publicaciones ML filter that a bulk pause / activate acts on.

Only an active publication is paused and only a paused one activated, never a deleted one (`filters.deleted`): the
rest of the filtered set is counted apart (`no_aplican`) so the confirmation can say so. Over `MAX_STATUS_ITEM_IDS`
it refuses, never truncates: a bulk write over part of what the operator sees is the bug this exists to prevent.
Each write checks its publication again (`ml_item_status_write_service`); this set only decides what is asked.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from sqlalchemy import ARRAY, Text, and_, any_, func, literal, not_, or_, select
from sqlalchemy.sql.selectable import Subquery
from sqlalchemy.orm import Session

from app.services.ml_publications.view.caps import MAX_STATUS_ITEM_IDS
from app.services.ml_publications.view.filters import T, PublicationFilter, build_base_select, deleted, has_product
from app.services.ml_publications.view.listing import markup_accepted, resolve_pm_pairs
from app.services.ml_publications.view.markup_service import MarkupQuery

# The status a publication must have to take each target.
SOURCE_STATUS = {"paused": "active", "active": "paused"}


class TooManyPublications(Exception):
    def __init__(self, count: int, cap: int) -> None:
        super().__init__(f"{count} publications over the cap of {cap}")
        self.count = count
        self.cap = cap


@dataclass(frozen=True)
class StatusTargets:
    item_ids: list[str]  # the MLAs that can take the target status, ascending
    no_aplican: int  # the rest of the filtered set: another status, or deleted


def _eligible_capped(db: Session, members: Subquery) -> list[str]:
    """The eligible MLAs of `members` (columns `mla`, `eligible`), ascending. The ids and their total come from ONE
    statement (a window evaluated before the LIMIT): the cap checks the very snapshot the list is read from. LIMIT
    cap+1 keeps an over-cap answer small. Raises `TooManyPublications` over `MAX_STATUS_ITEM_IDS`."""
    found = db.execute(
        select(members.c.mla, func.count().over().label("total"))
        .where(members.c.eligible)
        .order_by(members.c.mla)
        .limit(MAX_STATUS_ITEM_IDS + 1)
    ).all()
    count = found[0].total if found else 0
    if count > MAX_STATUS_ITEM_IDS:
        raise TooManyPublications(int(count), MAX_STATUS_ITEM_IDS)
    return [row.mla for row in found]


def status_item_ids(
    db: Session, f: PublicationFilter, target: str, markup: Optional[MarkupQuery] = None
) -> StatusTargets:
    """`markup` (its filter active) narrows the MLAs as `/items` does (`listing.markup_accepted`). Raises
    `TooManyPublications` over `MAX_STATUS_ITEM_IDS`."""
    f = resolve_pm_pairs(db, f)
    eligible = and_(T.i.status == SOURCE_STATUS[target], not_(deleted())).label("eligible")
    base = build_base_select(f, T.i.item_id.label("mla"), eligible)
    if markup is not None and markup.filter.active:
        _, kept = markup_accepted(db, f, markup)
        base = base.where(T.i.item_id == any_(literal(sorted(kept), ARRAY(Text))))
    members = base.subquery("m")
    found = _eligible_capped(db, members)
    # A second read, informative only (the confirmation's "N no aplican"): it may differ from the list by a
    # publication that changed in between, and nothing is written from it.
    rest = db.execute(select(func.count()).select_from(members).where(not_(members.c.eligible))).scalar_one()
    return StatusTargets(found, int(rest))


def checked_status_item_ids(db: Session, item_ids: list[str], producto_ids: list[int], target: str) -> StatusTargets:
    """The checked rows' publications that can take `target`: exactly `item_ids` (each checked publication alone,
    never widened to the other publications of its product) plus every publication linked to one of `producto_ids`
    (a checked product row of the Producto view). No filter takes part. A checked MLA that is not in `ml_items`, or
    cannot take the status (another status, or deleted), is counted in `no_aplican` and never named. Raises
    `TooManyPublications` over `MAX_STATUS_ITEM_IDS`, never truncates."""
    asked = list(dict.fromkeys(item_ids))
    picked = or_(
        T.i.item_id == any_(literal(asked, ARRAY(Text))),
        has_product(list(dict.fromkeys(producto_ids))) if producto_ids else literal(False),
    )
    eligible = and_(T.i.status == SOURCE_STATUS[target], not_(deleted())).label("eligible")
    members = select(T.i.item_id.label("mla"), eligible).select_from(T.i).where(picked).subquery("m")
    found = _eligible_capped(db, members)
    known = set(db.execute(select(members.c.mla)).scalars())
    rest = db.execute(select(func.count()).select_from(members).where(not_(members.c.eligible))).scalar_one()
    unknown = sum(1 for mla in asked if mla not in known)
    return StatusTargets(found, int(rest) + unknown)
