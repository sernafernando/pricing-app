"""The KPI strip of the Publicaciones screen (`GET /ml-publications/view/kpis`): Métricas ML's Board over the MLAs the
screen's filter selects.

Nothing is computed here. The filter becomes the same base select the list and the tree are built from
(`filters.build_base_select`), projected to `item_id`; the Board restricts itself to that set
(`BoardFilter.mla_source`, materialized as a temp table inside its own savepoint) and answers `Board.kpis()`, the
numbers Métricas shows for the same MLAs and period. One source: the strip cannot drift from Métricas.

Decisions worth knowing:

* The Board runs in its publication view (`group_by="publication"`): the screen's unit is the MLA.
* `scope_pairs=None`: no PM scoping. This screen is a management tool over every publication, like the list.
* `mla_count` is the size of the selected set (the list's `total`), NOT the Board's `rows`, whose universe is the
  MLAs that sold plus the legacy publications; it is read from the Board's own set table, so it costs no second
  scan of the base select.
* The Board exposes no Ads figures, so the strip has none.
* Nothing commits and nothing is written; the caller ends the transaction (its `rollback()` also ends the
  `SET LOCAL statement_timeout`).

Postgres only (the Board's temp table); its tests are `@pytest.mark.postgres`.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.services.ml_daily_metrics import board
from app.services.ml_publications.view.filters import PublicationFilter, T, build_base_select
from app.services.ml_publications.view.listing import resolve_pm_pairs


@dataclass(frozen=True)
class KpiStrip:
    kpis: board.Kpis
    mla_count: int
    prev_from: date
    prev_to: date


# ponytail: Ads KPIs join the strip when the Ads adapter (P15) lands; until then they are absent, not zero.
def compute(db: Session, f: PublicationFilter, date_from: date, date_to: date, compare: str) -> KpiStrip:
    """The Board's KPIs over the MLAs of `f` for `[date_from, date_to]` against the `compare` period."""
    f = resolve_pm_pairs(db, f)
    board_filter = board.BoardFilter(
        date_from=date_from,
        date_to=date_to,
        compare=compare,
        group_by="publication",
        mla_source=build_base_select(f, T.i.item_id),
    )
    prev_from, prev_to = board.previous_period(board_filter)
    with board.Board(db, board_filter, scope_pairs=None) as b:
        strip = b.kpis()
        mla_count = db.execute(select(func.count()).select_from(b.mla_set)).scalar_one()
    return KpiStrip(strip, mla_count, prev_from, prev_to)
