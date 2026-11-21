"""Publicaciones ML after a costo SI recompute (owner L15: "se tienen que recalcular todos los costos posteriores y
los promedios claramente"; plan sell-in-costo-si-t3-pr5-plan.md §9, orchestrator Q8 (a)).

pubml markups are computed live from the current costo SI, so they need nothing. Only two stored values depend on the
cost: the `hay_mejores_ofertas` flag (the C1 markup bands of `ml_hay_mejores_criterios` are absolute, so a cost change
can flip it) and the competitor markups of the catalog competition snapshots. For every MLA linked to the product or
to a combo (not a PC) that contains it, this callback only ENQUEUES: the MLAs go to the hay-mejores handler's
`pending_ids` and their catalog listing to `catalog_competition_refresh_pending`. Both writes are idempotent.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import List

from sqlalchemy.orm import Session

from app.models.ml_publications import MlItemProductLink
from app.services import catalog_competition_refresh_queue, ml_hay_mejores_pendientes
from app.services.catalog_competition_target import mlas_for_catalog_competition_refresh
from app.services.costo_si import lote
from app.services.costo_si.despues import registrar
from app.services.ml_publications.links import STATUS_LINKED


def _mlas(db: Session, productos: List[int]) -> List[str]:
    """MLAs linked to any of `productos` (any variation), distinct and sorted."""
    rows = (
        db.query(MlItemProductLink.item_id)
        .filter(
            MlItemProductLink.producto_item_id.in_(productos),
            MlItemProductLink.match_status == STATUS_LINKED,
        )
        .distinct()
        .all()
    )
    return sorted(row[0] for row in rows)


def _on_costo_si(db: Session, item_id: int, desde: date) -> None:
    """Queue the hay-mejores recompute and the catalog competition refresh of every MLA priced with `item_id`'s cost.

    `desde` is unused: both consumers read only the current cost, never a past one.

    Errors propagate (the drain rolls the product back and retries it, `despues.despachar`): unlike the best-effort
    `ml_promotions_hay_mejores._enqueue_catalog_competition_refresh`, losing this enqueue would leave a stale
    snapshot no later event repairs. "Nothing to refresh" is not an error: an MLA without a catalog listing yields
    no target and `enqueue` of no MLAs runs no statement. The enqueue runs in a SAVEPOINT like that helper's.
    """
    del desde
    productos = [item_id, *lote.combos_con(db, [item_id]).get(item_id, [])]
    mlas = _mlas(db, productos)
    if not mlas:
        return
    ml_hay_mejores_pendientes.agregar(db, mlas)
    targets = sorted(mlas_for_catalog_competition_refresh(db, mlas))  # three statements, whatever the MLAs
    if targets:
        with db.begin_nested():
            catalog_competition_refresh_queue.enqueue(db, targets, datetime.now(UTC))


registrar("pubml", _on_costo_si)
