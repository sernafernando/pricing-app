"""Better offers per PM: the count behind the PMs' top-bar badges.

A PM is a user with (marca, categoria) assignments (`marcas_pm`): the same id the Publicaciones ML `pms` filter takes.
A PM's count is the listing's own total (`listing.count_items`) for the page the badge opens,
`/ml-publicaciones?estado=active&hay_mejores_ofertas=1&pms=<pm_id>&tiendas=<MAIN_STORE_ID>`, so the badge and the page
always agree. Only the main store counts: the other official stores (TP-Link's, etc.) take no promos. Every
badge counts with `pm_filter` through the listing's own count: `count_for_pm` for one PM, `counts_by_pm` for every PM
at once (one query for their pairs, one for their counts), the same statement per PM.
"""

from __future__ import annotations

from dataclasses import replace

from sqlalchemy.orm import Session

from app.models.marca_pm import MarcaPM
from app.services.ml_publications.view import listing
from app.services.ml_publications.view.filters import PublicationFilter, parse_filter

# The main ML official store, the only one the promos apply to: the badges' `tiendas` filter. The endpoints return it so
# the frontend links carry the same store (one source, never hardcoded twice).
MAIN_STORE_ID = 57997


def pm_filter(pm_id: int) -> PublicationFilter:
    """The filter of the badge's link for `pm_id`: active publications of that PM in the main store with better
    offers, parsed by the listing's own `parse_filter` (the `tiendas` filter the screen uses)."""
    return parse_filter(estado="active", pms=str(pm_id), tiendas=str(MAIN_STORE_ID), hay_mejores_ofertas=True)


def is_pm(db: Session, user_id: int) -> bool:
    """Whether `user_id` has any (marca, categoria) assignment, i.e. appears in the screen's PM filter."""
    return db.query(MarcaPM.usuario_id).filter(MarcaPM.usuario_id == user_id).first() is not None


def count_for_pm(db: Session, pm_id: int) -> int:
    """How many active publications of `pm_id` have better offers: the listing total of `pm_filter(pm_id)`."""
    return listing.count_items(db, pm_filter(pm_id))


def pm_pairs(db: Session) -> dict[int, tuple[tuple[str, str], ...]]:
    """Every PM (a user with `marcas_pm` rows) with their pairs, in one query: the input of `counts_by_pm`."""
    return listing.pm_pairs_by_user(db)


def counts_by_pm(db: Session, pairs: dict[int, tuple[tuple[str, str], ...]]) -> dict[int, int]:
    """`count_for_pm` of every PM in `pairs` (from `pm_pairs`) in one statement: each count is the listing total of
    that PM's `pm_filter`, with the pairs already resolved."""
    filters = {pm_id: replace(pm_filter(pm_id), pm_pairs=pm_pairs_) for pm_id, pm_pairs_ in pairs.items()}
    return listing.count_items_by_key(db, filters)
