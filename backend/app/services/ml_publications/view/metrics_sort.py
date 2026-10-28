"""Sorting the Publicaciones list by Métricas ML's figures: the WHOLE filtered set ranked by the Board's own
publication figures over the last 30 business days, then cut to the page -- never the page alone.

Nothing is computed here (one metric, one source). The filtered set becomes the Board's MLA set
(`BoardFilter.mla_source`, as the KPI strip does) and the Board's publication rows give the figure; ONE statement
then ranks the set against them and cuts the page:

* a publication without sales in the 30 days -- unknown to the Board, or there with no units -- has no figure, and
  neither has a markup without cost: both go LAST in either direction;
* `item_id` closes every tie, so the order is total and pages never repeat or skip a row.

A fixed number of statements whatever the page (the Board's, plus the ranking). Postgres only (the Board's temp
tables).
"""

from __future__ import annotations

from typing import Any, Optional

from sqlalchemy import case, select
from sqlalchemy.orm import Session

from app.services.ml_daily_metrics import board
from app.services.ml_publications.view import row_metrics

# `orden` -> (the Board row's column, whether it is a margin figure: `ml_metricas.ver_ganancia` only)
METRIC_SORTS: dict[str, tuple[str, bool]] = {
    "facturado_30d": ("gross", False),
    "unidades_7d": ("w7d", False),
    "unidades_30d": ("w30d", False),
    "markup_30d": ("markup", True),
    "total_gauss_30d": ("tg", True),
}


def needs_margin(key: str) -> bool:
    return METRIC_SORTS[key][1]


def ranked_page(
    db: Session, mla_source: Any, key: str, descending: bool, limit: Optional[int], offset: int
) -> list[str]:
    """The MLAs of `mla_source` (a one-column select of the filtered set) at `[offset, offset + limit)` once ranked
    by the figure `key` names (`limit` None: every MLA from `offset` on)."""
    first, last = row_metrics.window(board.today_business())
    f = board.BoardFilter(date_from=first, date_to=last, group_by="publication", mla_source=mla_source)
    with board.Board(db, f, scope_pairs=None) as b:
        rows = b.rows()
        figure = _figure(rows, key)
        ordered = figure.desc() if descending else figure.asc()
        query = (
            select(b.mla_set.c.mla)
            .outerjoin(rows, rows.c.rk == b.mla_set.c.mla)
            .order_by(ordered.nulls_last(), b.mla_set.c.mla)
            .limit(limit)
            .offset(offset)
        )
        return [mla for (mla,) in db.execute(query)]


def _figure(rows: Any, key: str) -> Any:
    """The figure `key` names, only for a publication that sold in the window (null otherwise: last in either way)."""
    return case((rows.c.units > 0, rows.c[METRIC_SORTS[key][0]]), else_=None)


def metric_figures(db: Session, mla_source: Any, key: str) -> dict[str, Any]:
    """Every MLA of `mla_source` with the figure `key` names (None when it has none), for a sort with more keys."""
    first, last = row_metrics.window(board.today_business())
    f = board.BoardFilter(date_from=first, date_to=last, group_by="publication", mla_source=mla_source)
    with board.Board(db, f, scope_pairs=None) as b:
        rows = b.rows()
        query = select(b.mla_set.c.mla, _figure(rows, key)).outerjoin(rows, rows.c.rk == b.mla_set.c.mla)
        return dict(db.execute(query).all())
