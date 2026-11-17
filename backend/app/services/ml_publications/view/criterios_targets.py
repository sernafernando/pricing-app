"""Publications of a Publicaciones ML filter that bulk criterios apply acts on.

All non-deleted publications in the filter (or checked set). Over ``MAX_STATUS_ITEM_IDS``
refuses, never truncates.
"""

from __future__ import annotations

from typing import Optional

from sqlalchemy import ARRAY, Text, and_, any_, func, literal, not_, or_, select
from sqlalchemy.orm import Session

from app.services.ml_publications.view.filters import T, PublicationFilter, build_base_select, deleted, has_product
from app.services.ml_publications.view.listing import markup_accepted, resolve_pm_pairs
from app.services.ml_publications.view.markup_service import MarkupQuery
from app.services.ml_publications.view.status_targets import StatusTargets, _eligible_capped


def criterios_item_ids(
    db: Session,
    f: PublicationFilter,
    *,
    markup: Optional[MarkupQuery] = None,
) -> StatusTargets:
    """Every publication the filter shows that can receive criterios (not deleted / never_existed)."""
    f = resolve_pm_pairs(db, f)
    eligible = and_(not_(deleted()), T.i.never_existed.isnot(True)).label("eligible")
    base = build_base_select(f, T.i.item_id.label("mla"), eligible)
    if markup is not None and markup.filter.active:
        _, kept = markup_accepted(db, f, markup)
        base = base.where(T.i.item_id == any_(literal(sorted(kept), ARRAY(Text))))
    members = base.subquery("m")
    found = _eligible_capped(db, members)
    rest = db.execute(select(func.count()).select_from(members).where(not_(members.c.eligible))).scalar_one()
    return StatusTargets(found, int(rest))


def checked_criterios_item_ids(db: Session, item_ids: list[str], producto_ids: list[int]) -> StatusTargets:
    """Checked rows' publications that can receive criterios."""
    asked = list(dict.fromkeys(item_ids))
    picked = or_(
        T.i.item_id == any_(literal(asked, ARRAY(Text))),
        has_product(list(dict.fromkeys(producto_ids))) if producto_ids else literal(False),
    )
    can_take = and_(not_(deleted()), T.i.never_existed.isnot(True))
    eligible = func.coalesce(can_take, False).label("eligible")
    members = select(T.i.item_id.label("mla"), eligible).select_from(T.i).where(picked).subquery("m")
    found = _eligible_capped(db, members)
    known = set(db.execute(select(members.c.mla)).scalars())
    rest = db.execute(select(func.count()).select_from(members).where(not_(members.c.eligible))).scalar_one()
    unknown = sum(1 for mla in asked if mla not in known)
    return StatusTargets(found, int(rest) + unknown)
