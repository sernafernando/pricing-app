"""Ventas por fuera after a costo SI recompute (owner L15: "se tienen que recalcular todos los costos posteriores";
sell-in-costo-si T3 PR 9, inventory §12).

When the costo SI of a product changes from `desde`, the Precio Costo of every PDF line of that product, and of the
combos that contain it (`lote.combos_con`), sold on or after `desde` is recomputed from its costo SI
(`costo_erp.recostear`): lines with a manual cost are skipped, a combo broken down in its document stays 0 (owner L19),
only lines whose value differs are written. The previous values go first to `costo_si_backups`
(`motivo = MOTIVO`, one row per recompute with every changed line before and after). The callback runs inside
`queue.drenar`'s transaction and never commits: the new average, the recosted lines, their backup and the `sell_dirty`
rows the line trigger queues commit together, or the product is rolled back and retried (orchestrator, option b:
recost inline instead of a queue of its own).
"""

from __future__ import annotations

import json
from datetime import date

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.services.costo_si import despues, lote
from app.services.ventas_fuera_pdf.costo_erp import Recosteo, recostear

MOTIVO = "ventas_fuera precio_costo"


def _respaldo(db: Session, item_id: int, desde: date):
    def guardar(cambios: list[Recosteo]) -> None:
        if not cambios:
            return
        pasos = [
            {
                "linea_id": c.linea_id,
                "item_id": c.item_id,
                "fecha": c.fecha.isoformat(),
                "precio_costo_antes": str(c.antes),
                "precio_costo_despues": str(c.despues),
            }
            for c in cambios
        ]
        db.execute(
            text(
                "INSERT INTO costo_si_backups (item_id, desde, motivo, pasos) "
                "VALUES (:i, :desde, :motivo, CAST(:pasos AS jsonb))"
            ),
            {"i": item_id, "desde": desde, "motivo": MOTIVO, "pasos": json.dumps(pasos)},
        )

    return guardar


def recostear_desde(db: Session, item_id: int, desde: date) -> None:
    """Recompute the PDF lines of `item_id` and of its combos dated on or after `desde` (module docstring)."""
    productos = {item_id, *lote.combos_con(db, [item_id]).get(item_id, [])}
    recostear(db, desde=desde, aplicar=True, respaldo=_respaldo(db, item_id, desde), items=productos, commit=False)


despues.registrar("ventas_fuera", recostear_desde)
