"""The KPI strip as the API serializes it, shared by every screen that shows Métricas' numbers.

`build_kpis` turns the Board's `Kpis` into the response model: the Métricas board (`/ml-metricas/board`) and the
Publicaciones strip (`/ml-publications/view/kpis`) both call it, so they answer the same figures for the same set
and period. Without `can_see_margin` the profit figures (Total Gauss, markup) come back empty.
"""

from __future__ import annotations

from datetime import date
from typing import List, Optional

from pydantic import BaseModel

from app.services.ml_daily_metrics import board


# The KPI daily series holds one entry per day of the period: an unbounded
# range would build millions of them in memory. One year (a leap year
# included) is the most the screen offers ("3m" preset, custom ranges).
MAX_PERIOD_DAYS = 366
# Sane ends for the period AND its comparison period (a year back, or the
# same length back), so the date arithmetic can never underflow/overflow.
MIN_BOARD_DATE = date(2001, 1, 1)
MAX_BOARD_DATE = date(2100, 12, 31)


class BoardPeriod(BaseModel):
    date_from: date
    date_to: date
    prev_from: date
    prev_to: date


class KpiMoney(BaseModel):
    value: Optional[float] = None
    delta_pct: Optional[float] = None
    series: Optional[List[float]] = None


class KpiUnits(BaseModel):
    value: int
    delta_pct: Optional[float] = None
    series: List[int]


class KpiMarkup(BaseModel):
    value: Optional[float] = None
    delta_pp: Optional[float] = None
    series: Optional[List[Optional[float]]] = None


class KpiShare(BaseModel):
    value: int
    of_total: int


class KpiAgeing(BaseModel):
    """Ageing of the filtered rows (days since the last sale, or since the
    publication started if it never sold). The three buckets split ALL the
    rows with an ageing and drive the card's bar: up to 30 days, 31 to 60
    days, over 60 days (the "Ageing > 60d" alert)."""

    avg_days: Optional[float] = None
    up_to_30: int
    from_31_to_60: int
    over_60: int


class BoardKpis(BaseModel):
    units: KpiUnits
    gross: KpiMoney
    total_gauss: KpiMoney
    markup: KpiMarkup
    # Rows with sales in the period / all rows: products, or publications
    # when the board is grouped by publication.
    rows_with_sales: KpiShare
    ageing: KpiAgeing


def round_money(value) -> Optional[float]:
    return None if value is None else round(float(value), 2)


def round_pp(value) -> Optional[float]:
    return None if value is None else round(float(value), 1)


def delta_pct(now, before) -> Optional[float]:
    if not before:
        return None
    return round((float(now) - float(before)) / float(before) * 100, 1)


def build_kpis(k: board.Kpis, can_see_margin: bool) -> BoardKpis:
    """The KPI strip as the API serializes it. Public: Publicaciones' strip (`/ml-publications/view/kpis`) uses
    it too, so both screens answer the same figures; without `can_see_margin` the profit ones are null."""
    markup = board.markup_of(k.mtg, k.costo)
    markup_prev = board.markup_of(k.prev_mtg, k.prev_costo)
    return BoardKpis(
        units=KpiUnits(value=k.units, delta_pct=delta_pct(k.units, k.prev_units), series=k.series_units),
        gross=KpiMoney(
            value=round_money(k.gross),
            delta_pct=delta_pct(k.gross, k.prev_gross),
            series=[round_money(v) for v in k.series_gross],
        ),
        total_gauss=(
            KpiMoney(
                value=round_money(k.tg),
                delta_pct=delta_pct(k.tg, k.prev_tg),
                series=[round_money(v) for v in k.series_tg],
            )
            if can_see_margin
            else KpiMoney()
        ),
        markup=(
            KpiMarkup(
                value=round_pp(markup),
                delta_pp=round_pp(markup - markup_prev) if markup is not None and markup_prev is not None else None,
                series=k.series_markup,
            )
            if can_see_margin
            else KpiMarkup()
        ),
        rows_with_sales=KpiShare(value=k.with_sales, of_total=k.rows),
        ageing=KpiAgeing(
            avg_days=round(k.ageing_avg, 1) if k.ageing_avg is not None else None,
            up_to_30=k.up_to_30,
            from_31_to_60=k.from_31_to_60,
            over_60=k.over_60,
        ),
    )
