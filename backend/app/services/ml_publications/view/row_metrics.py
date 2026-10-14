"""The Métricas ML figures of each publication on a Publicaciones page: the 7/30-day units, the 90-day series, the
gross revenue, Total Gauss and real markup of the last 30 business days, the last sale and the ageing.

Nothing is computed here (one metric, one source). The page's MLAs become the Board's MLA set
(`BoardFilter.mla_source`, materialized inside the Board's own savepoint) and the Board answers its PUBLICATION rows
for the last 30 business days -- the very rows Métricas ML shows for those MLAs over that period, with its sold-lines
switch (`sales.lines_source`, `METRICAS_SALE_LINES_ENABLED`), markup rule, windows, series and ageing definitions.

Decisions worth knowing:

* ONE Board per page: a fixed number of statements whatever the page size, never one per row.
* `scope_pairs=None`: no PM scoping, like the rest of this screen.
* An MLA the Board has no row for (never sold and unknown to the ERP mirror) is absent: the screen reads "—".
* Nothing commits and nothing is written; the Board rolls its savepoint back on the way out.

Postgres only (the Board's temp tables); its tests are `@pytest.mark.postgres`.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Dict, Optional, Sequence, Tuple

from sqlalchemy import String, literal, select, union_all
from sqlalchemy.orm import Session

from app.services.ml_daily_metrics import board

WINDOW_DAYS = 30


def window(today: date) -> Tuple[date, date]:
    """The last `WINDOW_DAYS` business days, today included (the board's "30d" window)."""
    return today - timedelta(days=WINDOW_DAYS - 1), today


def _mla_source(mlas: Sequence[str]):
    """The page's MLAs as the one-column SELECT the Board materializes as its MLA set."""
    return union_all(*(select(literal(mla, String).label("mla")) for mla in mlas))


def metrics_by_mla(db: Session, mlas: Sequence[str], today: Optional[date] = None) -> Dict[str, board.Row]:
    """The Board's publication row of each of `mlas` over the last 30 business days; an MLA without one is absent."""
    mlas = sorted(set(mlas))
    if not mlas:
        return {}
    first, last = window(today or board.today_business())
    f = board.BoardFilter(date_from=first, date_to=last, group_by="publication", mla_source=_mla_source(mlas))
    with board.Board(db, f, scope_pairs=None) as b:
        rows = b.rows_for_keys(mlas, with_series=True)
    return {row.mla: row for row in rows}
