"""PCs: combos that are their own product for sell out and cost bonuses (L-owner-2, 2026-11-18).

Owner: "hay que corregir que siso aplique a pcs como si fueran entidades como hicimos en auditoría, porque al no
aplicar a combos no están aplicando a las pcs". A PC is a combo of the PC category, the rule Auditoría de stock
uses (`ml_publications.view.stock_audit.classify_combos`): the ERP category of the combo itself, its first company
row (`tb_item`, as `producto_maestro` reads a category). Its sale counts for the PC's own sell-out campaigns and
cost bonuses, never for its components'. Other combos keep counting for their components (`combos.ventas`).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import TypeVar

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.tb_item import TBItem

CAT_PC = 47

V = TypeVar("V")


def pcs_entre(db: Session, item_ids: Iterable[int]) -> set[int]:
    """The PCs among `item_ids` (one query; none for no ids)."""
    ids = sorted({int(i) for i in item_ids if i is not None})
    if not ids:
        return set()
    categorias = (
        select(TBItem.item_id, TBItem.cat_id)
        .where(TBItem.item_id.in_(ids))
        .distinct(TBItem.item_id)
        .order_by(TBItem.item_id, TBItem.comp_id)
        .subquery()
    )
    rows = db.execute(select(categorias.c.item_id).where(categorias.c.cat_id == CAT_PC))
    return {item_id for (item_id,) in rows}


def sin_pcs(db: Session, combos: Mapping[int, V]) -> dict[int, V]:
    """`combos` (keyed by combo) without the PCs: what is left is split into its components."""
    pcs = pcs_entre(db, combos)
    return {combo: value for combo, value in combos.items() if combo not in pcs}
