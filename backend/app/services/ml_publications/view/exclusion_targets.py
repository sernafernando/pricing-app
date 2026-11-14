"""Publications of a Publicaciones ML filter that a bulk hay_mejores exclude / include acts on.

Exclude: not already opted out (missing promotions row counts as participating).
Include: currently ``hay_mejores_excluido``. Over ``MAX_STATUS_ITEM_IDS`` refuses, never truncates.
"""

from __future__ import annotations

from typing import Optional

from sqlalchemy import ARRAY, Text, and_, any_, exists, func, literal, not_, or_, select
from sqlalchemy.orm import Session

from app.models.ml_publications import MlItemSellerPromotions
from app.services.ml_publications.view.filters import T, PublicationFilter, build_base_select, deleted, has_product
from app.services.ml_publications.view.listing import markup_accepted, resolve_pm_pairs
from app.services.ml_publications.view.markup_service import MarkupQuery
from app.services.ml_publications.view.status_targets import StatusTargets, _eligible_capped


def _is_excluido() -> object:
    return exists(
        select(literal(1)).where(
            MlItemSellerPromotions.item_id == T.i.item_id,
            MlItemSellerPromotions.hay_mejores_excluido.is_(True),
        )
    )


def exclusion_item_ids(
    db: Session,
    f: PublicationFilter,
    *,
    excluido: bool,
    markup: Optional[MarkupQuery] = None,
) -> StatusTargets:
    """``excluido=True`` → MLAs that can be excluded (not yet); ``False`` → MLAs that can be re-included."""
    f = resolve_pm_pairs(db, f)
    already = _is_excluido()
    eligible = and_(not_(deleted()), (already if not excluido else not_(already))).label("eligible")
    base = build_base_select(f, T.i.item_id.label("mla"), eligible)
    if markup is not None and markup.filter.active:
        _, kept = markup_accepted(db, f, markup)
        base = base.where(T.i.item_id == any_(literal(sorted(kept), ARRAY(Text))))
    members = base.subquery("m")
    found = _eligible_capped(db, members)
    rest = db.execute(select(func.count()).select_from(members).where(not_(members.c.eligible))).scalar_one()
    return StatusTargets(found, int(rest))


def checked_exclusion_item_ids(
    db: Session, item_ids: list[str], producto_ids: list[int], *, excluido: bool
) -> StatusTargets:
    """Checked rows' publications that can take exclude/include (same widening rules as status bulk)."""
    asked = list(dict.fromkeys(item_ids))
    picked = or_(
        T.i.item_id == any_(literal(asked, ARRAY(Text))),
        has_product(list(dict.fromkeys(producto_ids))) if producto_ids else literal(False),
    )
    already = _is_excluido()
    can_take = and_(not_(deleted()), T.i.never_existed.isnot(True), (already if not excluido else not_(already)))
    eligible = func.coalesce(can_take, False).label("eligible")
    members = select(T.i.item_id.label("mla"), eligible).select_from(T.i).where(picked).subquery("m")
    found = _eligible_capped(db, members)
    known = set(db.execute(select(members.c.mla)).scalars())
    rest = db.execute(select(func.count()).select_from(members).where(not_(members.c.eligible))).scalar_one()
    unknown = sum(1 for mla in asked if mla not in known)
    return StatusTargets(found, int(rest) + unknown)
