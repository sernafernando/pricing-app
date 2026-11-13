"""Better offers per PM: the count behind the PMs' top-bar badges.

A PM is a user with (marca, categoria) assignments (`marcas_pm`): the same id the Publicaciones ML `pms` filter takes.
A PM's count is the listing's own total (`listing.count_items`) for the page the badge opens,
`/ml-publicaciones?estado=active&hay_mejores_ofertas=1&pms=<pm_id>`, so the badge and the page always agree. Every
badge (the PM's own and any grouped one) counts through `count_for_pm`: one query shape.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.models.marca_pm import MarcaPM
from app.services.ml_publications.view import listing
from app.services.ml_publications.view.filters import PublicationFilter, parse_filter


def pm_filter(pm_id: int) -> PublicationFilter:
    """The filter of the badge's link for `pm_id`: active publications of that PM with better offers."""
    return parse_filter(estado="active", pms=str(pm_id), hay_mejores_ofertas=True)


def is_pm(db: Session, user_id: int) -> bool:
    """Whether `user_id` has any (marca, categoria) assignment, i.e. appears in the screen's PM filter."""
    return db.query(MarcaPM.usuario_id).filter(MarcaPM.usuario_id == user_id).first() is not None


def pm_ids(db: Session) -> list[int]:
    """Every user id with (marca, categoria) assignments: the PMs, in id order."""
    rows = db.query(MarcaPM.usuario_id).filter(MarcaPM.usuario_id.isnot(None)).distinct().all()
    return sorted(usuario_id for (usuario_id,) in rows)


def count_for_pm(db: Session, pm_id: int) -> int:
    """How many active publications of `pm_id` have better offers: the listing total of `pm_filter(pm_id)`."""
    return listing.count_items(db, pm_filter(pm_id))
