"""Stored markups follow costo SI (sell-in-costo-si T3 PR 4; owner L15: "se tienen que recalcular todos los costos
posteriores"; D4: "el precio de una venta no se toca, ni de las publicaciones").

When a product's costo SI history changes, its stored markups (`productos_pricing.markup_*`) and those of the combos
that contain it are rewritten over the current costo SI, from the stored prices; no price is ever written. Inline, not
queued (orchestrator OK): at most one `productos_pricing` row per product, idempotent. A markup that cannot be
recomputed is logged and skipped, so a pricing gap never rolls back the costo SI recompute.
"""

from __future__ import annotations

from datetime import date

from sqlalchemy.orm import Session

from app.services.costo_si import lote
from app.services.costo_si.despues import registrar
from app.services.recalcular_markups_service import recalcular_markups_guardados


def recalcular_markups(db: Session, item_id: int, desde: date) -> None:
    """`desde` does not matter: stored markups are figures over the CURRENT cost, so recomputing is idempotent."""
    recalcular_markups_guardados(db, [item_id, *lote.combos_con(db, [item_id]).get(item_id, [])])


registrar("pricing", recalcular_markups)
