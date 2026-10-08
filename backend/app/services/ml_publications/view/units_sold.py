"""Units sold per publication, from the SAME base as Métricas ML (design §7, addendum decision 6).

`ml_daily_metrics.sales.sale_lines` is the one per-sold-item base the Métricas board reads: same accreditation
day, same cancellation rules, same seller. The Ads cost of a publication is spread over THESE units, so the
per-unit figure on the Publicaciones screen agrees with the board. Units are per MLA (the whole publication, every
variation), which is why the figure is a plain `SUM(qty) GROUP BY mla` over the lines.
"""

from __future__ import annotations

from datetime import date
from typing import Mapping, Optional, Sequence

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.services.ml_daily_metrics import sales


class UnitsSoldProvider:
    def units_by_mla(
        self, db: Session, mlas: Optional[Sequence[str]], date_from: date, date_to: date
    ) -> Mapping[str, int]:
        """Units sold in the business days `[date_from, date_to]` by MLA; `mlas=None` means every MLA with sales."""
        if mlas is not None and not mlas:
            return {}
        sqlite = db.get_bind().dialect.name == "sqlite"
        lines = sales.sale_lines(sqlite=sqlite, ranges=[sales.day_bounds(date_from, date_to)])
        query = select(lines.c.mla, func.sum(lines.c.qty)).group_by(lines.c.mla)
        if mlas is not None:
            query = query.where(lines.c.mla.in_(list(mlas)))
        return {mla: int(units) for mla, units in db.execute(query).all() if units}
