"""The daily photo of AVAILABLE stock for costo SI (S3 decision: "from T2 on keep a daily snapshot of available stock
so reconstruction is only for the past").

Taken by the existing `stock.snapshot` job (06:00, after it fetched the day's Full operations) for every product that
has a costo SI, at 00:00 of its day, the instant the engine reads it for: principal = GBP depot 1 available
(`fuentes.principal_disponible`), Full = Mercado Libre's Full walked back to that instant (`full_ml.full_disponible`).
Once taken it is read instead of the reconstruction, so later mirror rewrites cannot move a closed day. Taking a day
again replaces it.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.services.costo_si import fuentes, full_ml

_INSERT_SQL = text(
    'INSERT INTO costo_si_stock_diario (fecha, item_id, principal, "full", tomado_at) VALUES (:f, :i, :p, :fu, :t)'
)


def tomar(db: Session, dia: date, ahora: datetime, deadline: Optional[datetime] = None) -> int:
    """Replace `dia`'s photo with the available stock at 00:00 of `dia`; returns how many products it holds. Stops
    at `deadline`: a product left out keeps an earlier photo of the day, or is reconstructed when read."""
    items = [r[0] for r in db.execute(text("SELECT DISTINCT item_id FROM costo_si_pasos ORDER BY 1"))]
    t = fuentes.inicio_del_dia(dia)
    filas = []
    for item_id in items:
        if deadline is not None and datetime.now(UTC) >= deadline:
            break
        principal = fuentes.principal_disponible(db, item_id, t)
        full = full_ml.full_disponible(db, item_id, t.replace(tzinfo=fuentes.ZONA))
        filas.append({"f": dia, "i": item_id, "p": principal, "fu": full, "t": ahora})
    if filas:  # only the products photographed now: a run cut by the deadline keeps the rest of an earlier photo
        db.execute(
            text("DELETE FROM costo_si_stock_diario WHERE fecha = :f AND item_id = ANY(:items)"),
            {"f": dia, "items": [f["i"] for f in filas]},
        )
        db.execute(_INSERT_SQL, filas)
    return len(filas)
