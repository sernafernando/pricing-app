"""Sales summary per publication for the Publicaciones list: units, gross revenue and real markup of each MLA over
the last 30 business days, from the SAME base as Métricas ML (`ml_daily_metrics.sales`, one metric, one source).

The lines come from `sales.lines_source` -- the persisted `ml_sale_lines` or the live derivation, by the board's own
switch -- and the markup is the board's: the ratio of the summed markup numerator and denominator (`mtg / mcosto`,
each rounded to the cent as the board does), never an average of percentages; no cost means no markup.

Only the MLAs of the page are read, in one statement: the live derivation is bounded to the groups that sold them
(whole groups, so a pack's markup rule still sees every member) and the lines are then kept for those MLAs.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import Dict, Optional, Sequence, Tuple

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.services.ml_daily_metrics import board, sales

WINDOW_DAYS = 30


@dataclass(frozen=True)
class SalesSummary:
    units: int
    gross: Decimal
    mtg: Decimal
    mcosto: Decimal

    @property
    def markup(self) -> Optional[Decimal]:
        """Percent, one decimal (what the board shows); `None` without cost."""
        value = board.markup_of(self.mtg, self.mcosto)
        return None if value is None else value.quantize(Decimal("0.1"))


def window(today: date) -> Tuple[date, date]:
    """The last `WINDOW_DAYS` business days, today included (the board's "30d" window)."""
    return today - timedelta(days=WINDOW_DAYS - 1), today


def summary_by_mla(db: Session, mlas: Sequence[str], today: Optional[date] = None) -> Dict[str, SalesSummary]:
    """The summary of each of `mlas` that sold in the window; an MLA without sales is absent."""
    mlas = sorted(set(mlas))
    if not mlas:
        return {}
    first, last = window(today or board.today_business())
    sqlite = db.get_bind().dialect.name == "sqlite"
    groups = None
    if not sales.reads_persisted_lines(sqlite):
        groups = sales.groups_touching([lambda item, cost: item.item_id.in_(mlas)])
    lines = sales.lines_source(sqlite=sqlite, ranges=[sales.day_bounds(first, last)], groups=groups)
    query = (
        select(
            lines.c.mla,
            func.sum(lines.c.qty),
            func.sum(lines.c.gross),
            func.sum(lines.c.mtg),
            func.sum(lines.c.mcosto),
        )
        .where(lines.c.mla.in_(mlas))
        .group_by(lines.c.mla)
    )
    return {
        mla: SalesSummary(units=int(units), gross=board.cents(gross), mtg=board.cents(mtg), mcosto=board.cents(mcosto))
        for mla, units, gross, mtg, mcosto in db.execute(query).all()
        if units
    }
