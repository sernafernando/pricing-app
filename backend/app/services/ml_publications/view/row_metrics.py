"""The Métricas ML figures of each publication on a Publicaciones page: the 7/30-day units, the 90-day series, the
gross revenue, Total Gauss and real markup of the last 30 business days, the last sale and the ageing.

Nothing is computed here (one metric, one source). The page's MLAs become the Board's MLA set
(`BoardFilter.mla_source`, materialized inside the Board's own savepoint) and the Board answers its PUBLICATION rows
for the last 30 business days -- the very rows Métricas ML shows for those MLAs over that period, with its sold-lines
switch (`sales.lines_source`, `METRICAS_SALE_LINES_ENABLED`), markup rule, windows, series and ageing definitions.

Decisions worth knowing:

* ONE Board per page: a fixed number of statements whatever the page size, never one per row. A caller that needs
  both the rows and their Full split passes a `PageBoard` where these functions take `db`: both answers then come
  from that one Board (pubml-lentitud: the stock audit read the same lines and pairs twice).
* `scope_pairs=None`: no PM scoping, like the rest of this screen.
* An MLA the Board has no row for (never sold and unknown to the ERP mirror) is absent: the screen reads "—".
* Nothing commits and nothing is written; the Board rolls its savepoint back on the way out.

Postgres only (the Board's temp tables); its tests are `@pytest.mark.postgres`.
"""

from __future__ import annotations

from contextlib import ExitStack
from datetime import date, timedelta
from typing import Any, Dict, Optional, Sequence, Tuple, Union

from sqlalchemy import ARRAY, String, func, literal, select
from sqlalchemy.orm import Session

from app.services.ml_daily_metrics import board

WINDOW_DAYS = 30


def window(today: date) -> Tuple[date, date]:
    """The last `WINDOW_DAYS` business days, today included (the board's "30d" window)."""
    return today - timedelta(days=WINDOW_DAYS - 1), today


def _mla_source(mlas: Sequence[str]):
    """The page's MLAs as the one-column SELECT the Board materializes as its MLA set: ONE array parameter, unnested
    (as `listing._by_figures`). A SELECT per MLA joined by UNION ALL blows Postgres' stack depth on a "Todos" page."""
    return select(func.unnest(literal(list(mlas), ARRAY(String))).label("mla"))


def _filter(mlas: Sequence[str], sell_in_out: bool) -> board.BoardFilter:
    first, last = window(board.today_business())
    return board.BoardFilter(
        date_from=first,
        date_to=last,
        group_by="publication",
        mla_source=_mla_source(mlas),
        sell_in_out=sell_in_out,
    )


class PageBoard:
    """ONE Board over a page's MLAs for `metrics_by_mla` and `fulfillment_by_mla` together: pass it where they take
    `db`. Opened on first use (a caller whose reads are both replaced never opens it) and rolled back on exit. The
    split reads only the lines' units and their orders' shipping, which `sell_in_out` never changes, so each answer is
    the one its own Board gives (`test_row_metrics_postgres`)."""

    def __init__(self, db: Session, mlas: Sequence[str], sell_in_out: bool = False) -> None:
        self.db, self.mlas, self.sell_in_out = db, sorted(set(mlas)), sell_in_out
        self._stack = ExitStack()
        self._board: Optional[board.Board] = None

    def __enter__(self) -> "PageBoard":
        return self

    def __exit__(self, *exc: Any) -> Optional[bool]:
        return self._stack.__exit__(*exc)

    def read(self, mlas: Sequence[str]) -> board.Board:
        if sorted(set(mlas)) != self.mlas:
            raise ValueError("a PageBoard answers only the MLAs it was opened for")
        if self._board is None:
            self._board = self._stack.enter_context(
                board.Board(self.db, _filter(self.mlas, self.sell_in_out), scope_pairs=None)
            )
        return self._board


def metrics_by_mla(
    db: Union[Session, PageBoard], mlas: Sequence[str], sell_in_out: bool = False
) -> Dict[str, board.Row]:
    """The Board's publication row of each of `mlas` over the last 30 business days; an MLA without one is absent.
    `sell_in_out` adds each row's sell in / sell out (`board.SellInOut`; `ml_metricas.ver_ganancia` callers only).

    The period ends on the Board's own business day (`board.today_business`, from `board.now_utc`): the clock its
    windows, series and ageing count from, so the two can never disagree."""
    mlas = sorted(set(mlas))
    if not mlas:
        return {}
    if isinstance(db, PageBoard):
        if sell_in_out != db.sell_in_out:
            raise ValueError("the PageBoard was opened with another sell_in_out")
        rows = db.read(mlas).rows_for_keys(mlas, with_series=True)
    else:
        with board.Board(db, _filter(mlas, sell_in_out), scope_pairs=None) as b:
            rows = b.rows_for_keys(mlas, with_series=True)
    return {row.mla: row for row in rows}


def fulfillment_by_mla(db: Union[Session, PageBoard], mlas: Sequence[str]) -> Dict[str, board.ShippingSplit]:
    """Each of `mlas`' 7d / 30d units split into Full and ERP (`board.Board.units_by_fulfillment`), over the SAME
    Board window `metrics_by_mla` reads, so the split adds up to its rows' windows. An MLA without a sold line in the
    30d window is absent (all its units, none, are ERP)."""
    mlas = sorted(set(mlas))
    if not mlas:
        return {}
    if isinstance(db, PageBoard):
        return db.read(mlas).units_by_fulfillment()
    with board.Board(db, _filter(mlas, False), scope_pairs=None) as b:
        return b.units_by_fulfillment()
