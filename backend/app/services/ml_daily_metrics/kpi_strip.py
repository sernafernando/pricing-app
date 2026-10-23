"""The KPI strip as the API serializes it, shared by every screen that shows Métricas' numbers.

`build_kpis` turns the Board's `Kpis` into the response model: the Métricas board (`/ml-metricas/board`) and the
Publicaciones strip (`/ml-publications/view/kpis`) both call it, so they answer the same figures for the same set
and period. Without `can_see_margin` the profit figures (Total Gauss, markup) come back empty.
"""

from __future__ import annotations

from datetime import date
from typing import Any, List, Optional

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


class KpiCoverageDay(BaseModel):
    source: str
    advertiser_id: int
    day: date
    status: Optional[str] = None  # null: the day was never fetched


class KpiCoverage(BaseModel):
    """What the ads ledger admits about the range. A missing day is NOT zero spend; `available` is whether any
    trusted day exists at all, `data_through` the last day of the trusted run from the oldest ledgered day."""

    available: bool
    data_through: Optional[date] = None
    missing_days: List[KpiCoverageDay]
    mismatch_days: List[KpiCoverageDay]


class KpiDisplaySpend(BaseModel):
    cost_api: float
    cost_net: float
    subtracted: bool


class KpiBrandSpend(BaseModel):
    """Brand Ads' stored cost (measured all zero on 2026-10-08, Engram #2307: no IVA basis to apply)."""

    cost: float
    subtracted: bool


class KpiAccountLevel(BaseModel):
    display: KpiDisplaySpend
    brand: KpiBrandSpend


class KpiAdsUnattributed(BaseModel):
    """Spend no row owns, present only in the unfiltered view. `sin_producto_cost` (Product Ads of MLAs no
    product owns) already rides on the "sin producto" row; the account level only comes off the totals, and only
    where `subtracted` says so."""

    sin_producto_cost: float
    account_level: KpiAccountLevel


class KpiAds(BaseModel):
    """Product Ads of the KPI rows (only with `restar_publicidad` and `ver_ganancia`). Informational context:
    the ratios use the API cost basis and are never linked to specific sales; `cost_total` is ML's gross cost net
    of IVA, `contribution` the brand contributions covering part of it, and `subtracted_total` the amount actually
    subtracted from `total_gauss` and `markup` (Product Ads net of `contribution`, plus Display and Brand under
    `todo`). A zero denominator gives null."""

    cost_total: float
    cost_api: float
    impressions: int
    clicks: int
    direct_amount: float
    indirect_amount: float
    direct_units: int
    indirect_units: int
    organic_units: int
    organic_amount: float
    acos_pct: Optional[float] = None
    roas: Optional[float] = None
    tacos_pct: Optional[float] = None
    cpc: Optional[float] = None
    ctr_pct: Optional[float] = None
    # "mla" | "todo": the position asked for and the one the view could apply (a filtered or PM-scoped view
    # cannot carry account-level spend, so "todo" is applied as "mla" there).
    requested: str = "mla"
    applied: str = "mla"
    subtracted_total: float = 0.0
    # The brand contributions covering part of `cost_api` (ml-ads-brand-contribution S9): `cost_total` stays ML's
    # gross cost while `subtracted_total` (and Total Gauss) are net of them.
    contribution: float = 0.0
    coverage: Optional[KpiCoverage] = None
    unattributed: Optional[KpiAdsUnattributed] = None


class BoardKpis(BaseModel):
    units: KpiUnits
    gross: KpiMoney
    total_gauss: KpiMoney
    markup: KpiMarkup
    # Rows with sales in the period / all rows: products, or publications
    # when the board is grouped by publication.
    rows_with_sales: KpiShare
    ageing: KpiAgeing


class KpiTp(BaseModel):
    """ "Costos TP" ON: the known Total TP of the TP store group's operations (null when none has a TP cost) and
    how many of their sold lines lack a TP cost (incomplete, never counted as 0)."""

    value: Optional[float] = None
    incompletos: int = 0


class BoardKpisWithAds(BoardKpis):
    """The Métricas board's strip: the shared one plus the ads block (null with the toggle OFF) and Total TP (null
    with "Costos TP" OFF). Publicaciones keeps `BoardKpis`, so its strip never carries those fields."""

    ads: Optional[KpiAds] = None
    total_tp: Optional[KpiTp] = None


def round_money(value) -> Optional[float]:
    return None if value is None else round(float(value), 2)


def round_pp(value) -> Optional[float]:
    return None if value is None else round(float(value), 1)


def delta_pct(now, before) -> Optional[float]:
    if not before:
        return None
    return round((float(now) - float(before)) / float(before) * 100, 1)


def _ratio(numerator: Any, denominator: Any, scale: int = 1) -> Optional[float]:
    return round(float(numerator) * scale / float(denominator), 2) if denominator else None


def _kpi_ads(a: board.AdsKpis, gross: Any) -> KpiAds:
    attributed = a.direct_amount + a.indirect_amount
    return KpiAds(
        cost_total=round_money(a.cost_total),
        cost_api=round_money(a.cost_api),
        impressions=a.prints,
        clicks=a.clicks,
        direct_amount=round_money(a.direct_amount),
        indirect_amount=round_money(a.indirect_amount),
        direct_units=a.direct_units,
        indirect_units=a.indirect_units,
        organic_units=a.organic_units,
        organic_amount=round_money(a.organic_amount),
        acos_pct=_ratio(a.cost_api, attributed, 100),
        roas=_ratio(attributed, a.cost_api),
        tacos_pct=_ratio(a.cost_api, gross, 100),
        cpc=_ratio(a.cost_api, a.clicks),
        ctr_pct=_ratio(a.clicks, a.prints, 100),
        requested=a.requested,
        applied=a.applied,
        subtracted_total=round_money(a.subtracted_total),
        contribution=round_money(a.contribution),
        coverage=KpiCoverage(
            available=a.coverage.available,
            data_through=a.coverage.data_through,
            missing_days=[KpiCoverageDay.model_validate(d, from_attributes=True) for d in a.coverage.missing_days],
            mismatch_days=[KpiCoverageDay.model_validate(d, from_attributes=True) for d in a.coverage.mismatch_days],
        ),
        unattributed=_kpi_unattributed(a.unattributed),
    )


def _kpi_unattributed(u: Optional[board.AdsUnattributed]) -> Optional[KpiAdsUnattributed]:
    if u is None:
        return None
    account = u.account_level
    return KpiAdsUnattributed(
        sin_producto_cost=round_money(u.sin_producto_cost),
        account_level=KpiAccountLevel(
            display=KpiDisplaySpend(
                cost_api=round_money(account.display_api),
                cost_net=round_money(account.display_net),
                subtracted=u.subtracted,
            ),
            brand=KpiBrandSpend(cost=round_money(account.brand), subtracted=u.subtracted),
        ),
    )


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


def build_board_kpis(k: board.Kpis, can_see_margin: bool) -> BoardKpisWithAds:
    """`build_kpis` plus the ads block and Total TP: each present only with its toggle ON and the profit-view
    permission."""
    ads = _kpi_ads(k.ads, k.gross) if can_see_margin and k.ads is not None else None
    tp = (
        KpiTp(value=round_money(k.total_tp), incompletos=k.tp_incompletos)
        if can_see_margin and k.tp_incompletos is not None
        else None
    )
    return BoardKpisWithAds(**build_kpis(k, can_see_margin).model_dump(), ads=ads, total_tp=tp)
