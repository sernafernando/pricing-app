"""The daily photo of AVAILABLE stock for costo SI (S3 decision: "from T2 on keep a daily snapshot of available stock
so reconstruction is only for the past").

Taken by the existing `stock.snapshot` job (06:00) for every product that has a costo SI: principal = GBP depot 1
available now (`fuentes.principal_disponible`), Full = Mercado Libre's Full stock now (`full_ml.full_disponible`).
It stands for the start of its day: the engine reads it for that day instead of reconstructing. Taking a day again
replaces it.
"""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.services.costo_si import fuentes, full_ml


def tomar(db: Session, dia: date, ahora: datetime) -> int:
    """Replace `dia`'s photo with the available stock at `ahora` (aware); returns how many products it holds."""
    items = [r[0] for r in db.execute(text("SELECT DISTINCT item_id FROM costo_si_pasos ORDER BY 1"))]
    local = ahora.astimezone(fuentes.ZONA).replace(tzinfo=None)
    db.execute(text("DELETE FROM costo_si_stock_diario WHERE fecha = :f"), {"f": dia})
    for item_id in items:
        db.execute(
            text(
                'INSERT INTO costo_si_stock_diario (fecha, item_id, principal, "full", tomado_at) '
                "VALUES (:f, :i, :p, :fu, :t)"
            ),
            {
                "f": dia,
                "i": item_id,
                "p": fuentes.principal_disponible(db, item_id, local),
                "fu": full_ml.full_disponible(db, item_id, ahora),
                "t": ahora,
            },
        )
    return len(items)
