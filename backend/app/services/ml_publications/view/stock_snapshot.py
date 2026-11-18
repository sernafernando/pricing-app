"""The daily stock photo (auditoria-stock-rotacion L1, owner: "Guardar foto diaria desde ahora"): what each product
has in stock on a day, ERP and Full apart, so the Auditoría de stock can divide the units sold in 30 days by the
AVERAGE stock of those days ("Rotación (veces)").

* `take`: today's photo. ERP = the catalog's stock (`filters.erp_stock_per_product`, the view's catalog reader); Full = the units at ML's warehouse of the product's publications,
  each user product counted once, in the product's own units (`stock_audit.full_by_product`, the Auditoría's own
  Full). Only products with some stock get a row. Taking the day again replaces that day's rows (idempotent: a
  product whose stock ran out since the first take loses its row), other days are never touched.
* `prune`: keeps the last `KEEP_DAYS` days, on the same run.
* `averages`: per product, the average over the days photographed in the last `WINDOW_DAYS` days (a product without a
  row on a photographed day had 0 that day), with how many days there were. Fewer than 30 is normal while the history
  builds up; with none the caller stands the current stock in and says so.

Written by the `stock.snapshot` job of the existing worker (`app.workers.handlers.stock_snapshot`); no cron.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Iterable

from sqlalchemy import delete, func, insert, select
from sqlalchemy.orm import Session

from app.models.stock_diario import StockDiario as S
from app.services.ml_publications.view import stock_audit
from app.services.ml_publications.view.filters import erp_stock_per_product

KEEP_DAYS = 400
WINDOW_DAYS = 30


def take(db: Session, day: date) -> int:
    """Replace `day`'s photo with the stock now; returns how many products it holds. Does not commit."""
    erp = {item: int(stock) for item, stock in db.execute(erp_stock_per_product())}
    full = {item: units for item, units in stock_audit.full_by_product(db).items() if units > 0}
    rows = [
        {"fecha": day, "item_id": item, "stock_erp": erp.get(item, 0), "stock_full": full.get(item, 0)}
        for item in sorted(erp.keys() | full.keys())
    ]
    db.execute(delete(S).where(S.fecha == day))
    if rows:
        db.execute(insert(S), rows)
    return len(rows)


def prune(db: Session, today: date) -> int:
    """Drop the photos older than the last `KEEP_DAYS` days (today included); returns the rows dropped."""
    return db.execute(delete(S).where(S.fecha <= today - timedelta(days=KEEP_DAYS))).rowcount or 0


@dataclass(frozen=True)
class Averages:
    dias: int  # days photographed in the window; 0 = no history yet
    stock: dict[int, tuple[float, float]] = field(default_factory=dict)  # item -> (ERP, Full) average


def averages(db: Session, items: Iterable[int], today: date) -> Averages:
    """The average ERP and Full stock of `items` over the days photographed in the last `WINDOW_DAYS` days."""
    since = today - timedelta(days=WINDOW_DAYS - 1)
    window = (S.fecha >= since, S.fecha <= today)
    dias = db.execute(select(func.count(func.distinct(S.fecha))).where(*window)).scalar_one()
    ids = sorted(set(items))
    if not dias or not ids:
        return Averages(dias)
    totals = db.execute(
        select(S.item_id, func.sum(S.stock_erp), func.sum(S.stock_full))
        .where(*window, S.item_id.in_(ids))
        .group_by(S.item_id)
    ).all()
    return Averages(dias, {item: (int(erp) / dias, int(full) / dias) for item, erp, full in totals})
