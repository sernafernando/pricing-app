"""After a costo SI recompute: queue the product's ML sales, and those of every combo containing it, to be re-frozen
from the first changed date (sell-in-costo-si T3 PR 7, L15; interface §3). Only enqueues: `sell.drain` re-freezes
them in bounded passes (`ml_orders_ingestion.recongelar_costo_si.drenar`). Import-safe: no I/O at import."""

from __future__ import annotations

from datetime import date

from sqlalchemy.orm import Session

from app.services.costo_si import lote
from app.services.costo_si.despues import registrar
from app.services.ml_orders_ingestion import recongelar_costo_si


def encolar(db: Session, item_id: int, desde: date) -> None:
    combos = lote.combos_con(db, [item_id]).get(item_id, [])
    recongelar_costo_si.encolar(db, [item_id, *combos], desde)


registrar("ml_ventas", encolar)
