"""Ads read side (ml-billing-balance, design D9): the native cost provider and its adapter to the
publications view.

Everything here is a query over the stored facts; no sum is ever stored (ADS-4). Only `product_ads` cost per
MLA feeds the per-MLA and per-product functions: Display and Brand Ads are account-level and are never
attributed to an MLA (`ads_account_level`). Brand Ads is informational and has no net cost.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Literal, Mapping, Optional, Sequence

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.ml_ads import MlAdsBrandDay, MlAdsDayLedger, MlAdsDisplayCampaignDay, MlAdsItemDay
from app.services.ml_ads.ingestion import LOCAL_TZ
from app.services.ml_ads.iva import ads_cost_net_of_iva
from app.services.ml_ads.owner import NO_PRODUCT, ads_owner_select
from app.services.ml_publications.view.ads import AdsAvailability

SOURCE = "product_ads"
COVERED = ("closed", "mismatch")


@dataclass(frozen=True)
class AdsAvailabilityInfo:
    """Field-for-field the `AdsAvailability` dataclass of the publicaciones-ml-vista design (#2279)."""

    available: bool
    reason: Literal["provider_missing", "no_data", "ok"]
    data_through: Optional[date]


class MlAdsCostProvider:
    """The native provider: ARS cost per MLA, NET of IVA, no units."""

    def availability(self, db: Session) -> AdsAvailabilityInfo:
        """`no_data` until a product_ads day is closed. Otherwise `data_through` is the last day D such that
        every advertiser has a closed or mismatch row for every day from the oldest ledgered day through D."""
        rows = db.execute(
            select(MlAdsDayLedger.advertiser_id, MlAdsDayLedger.day, MlAdsDayLedger.status).where(
                MlAdsDayLedger.source == SOURCE
            )
        ).all()
        covered: dict[int, set[date]] = {}
        for advertiser, day, status in rows:
            covered.setdefault(advertiser, set())
            if status in COVERED:
                covered[advertiser].add(day)
        days = set().union(*covered.values()) if covered else set()
        if not days:
            return AdsAvailabilityInfo(False, "no_data", None)
        first = min(days)
        through: Optional[date] = None
        day = first
        while all(day in seen for seen in covered.values()):
            through = day
            day = date.fromordinal(day.toordinal() + 1)
        return AdsAvailabilityInfo(True, "ok", through)

    def cost_by_mla(
        self, db: Session, mlas: Optional[Sequence[str]], date_from: date, date_to: date
    ) -> Mapping[str, Decimal]:
        """Cost summed over the ad days in `[date_from, date_to]`, keyed `MLA...`. `mlas=None` means every MLA
        with cost > 0; `{}` when there is no data."""
        total = func.sum(MlAdsItemDay.cost)
        query = (
            select(MlAdsItemDay.item_id, total)
            .where(MlAdsItemDay.day.between(date_from, date_to))
            .group_by(MlAdsItemDay.item_id)
            .having(total > 0)
        )
        if mlas is not None:
            query = query.where(MlAdsItemDay.item_id.in_(list(mlas)))
        return {mla: ads_cost_net_of_iva(cost, SOURCE) for mla, cost in db.execute(query).all()}


class ViewAdsProvider:
    """Adapter to the `AdsCostProvider` Protocol of `ml_publications.view.ads`, bound to a session.

    `reason` and `data_through` stay on the native API; the consumer only sees available / unavailable."""

    def __init__(self, db: Session) -> None:
        self._db = db
        self._native = MlAdsCostProvider()

    def availability(self) -> AdsAvailability:
        available = self._native.availability(self._db).available
        return AdsAvailability.AVAILABLE if available else AdsAvailability.UNAVAILABLE

    def amounts(self, mla_ids: Optional[Sequence[str]], date_from: date, date_to: date) -> Mapping[str, float]:
        return {
            mla: float(cost) for mla, cost in self._native.cost_by_mla(self._db, mla_ids, date_from, date_to).items()
        }


# --- the read service behind /ml-ads/* (AR-1, AR-3, AR-4) ---------------------------------------------


@dataclass(frozen=True)
class AdsMlaRow:
    """One MLA's Product Ads in a range. Money is Decimal (API basis and net); units/amounts are informational."""

    mla: str
    owner_product_id: int
    cost_api: Decimal
    cost_net: Decimal
    clicks: int
    prints: int
    direct_units: int
    indirect_units: int
    direct_amount: Decimal
    indirect_amount: Decimal
    organic_units: int
    organic_amount: Decimal


@dataclass(frozen=True)
class AdsProductRow:
    """The read-time sum of the `AdsMlaRow`s of one owner; `product_id == NO_PRODUCT` is "sin producto"."""

    product_id: int
    mlas_count: int
    cost_api: Decimal
    cost_net: Decimal
    clicks: int
    prints: int
    direct_units: int
    indirect_units: int
    direct_amount: Decimal
    indirect_amount: Decimal
    organic_units: int
    organic_amount: Decimal


@dataclass(frozen=True)
class DisplayCampaign:
    campaign_id: int
    cost_api: Decimal
    cost_net: Decimal
    prints: int
    clicks: int


@dataclass(frozen=True)
class DisplayTotals:
    cost_api: Decimal
    cost_net: Decimal
    prints: int
    clicks: int
    by_campaign: list[DisplayCampaign]


@dataclass(frozen=True)
class BrandTotals:
    """Informational only (ADS-10): there is deliberately no net cost, and nothing subtracts it."""

    cost_informational: Decimal
    prints: int
    clicks: int


@dataclass(frozen=True)
class AccountLevel:
    display: DisplayTotals
    brand: BrandTotals


@dataclass(frozen=True)
class CoverageDay:
    source: str
    advertiser_id: int
    day: date
    status: Optional[str]  # None: the day was never ledgered


@dataclass(frozen=True)
class Coverage:
    data_through: Optional[date]
    missing_days: list[CoverageDay]
    mismatch_days: list[CoverageDay]


# Row field -> stored column (the API-basis cost is the `cost` column).
_MLA_SUMS = {
    "cost_api": MlAdsItemDay.cost,
    "clicks": MlAdsItemDay.clicks,
    "prints": MlAdsItemDay.prints,
    "direct_units": MlAdsItemDay.direct_units,
    "indirect_units": MlAdsItemDay.indirect_units,
    "direct_amount": MlAdsItemDay.direct_amount,
    "indirect_amount": MlAdsItemDay.indirect_amount,
    "organic_units": MlAdsItemDay.organic_units,
    "organic_amount": MlAdsItemDay.organic_amount,
}


def ads_by_mla(db: Session, date_from: date, date_to: date, mlas: Optional[Sequence[str]] = None) -> list[AdsMlaRow]:
    """Product Ads per MLA with cost > 0 (the provider's own rule) in `[date_from, date_to]`, with its owner."""
    sums = [func.sum(column) for column in _MLA_SUMS.values()]
    in_range = [MlAdsItemDay.day.between(date_from, date_to)]
    if mlas is not None:
        in_range.append(MlAdsItemDay.item_id.in_(list(mlas)))
    spent = (
        select(MlAdsItemDay.item_id, *sums)
        .where(*in_range)
        .group_by(MlAdsItemDay.item_id)
        .having(sums[0] > 0)
        .order_by(MlAdsItemDay.item_id)
    )
    found = db.execute(spent).all()
    if not found:
        return []
    mla_ids = select(MlAdsItemDay.item_id).where(*in_range).distinct()
    owners = dict(db.execute(ads_owner_select(sqlite=db.get_bind().dialect.name == "sqlite", mlas=mla_ids)).all())
    return [
        AdsMlaRow(
            mla=mla,
            owner_product_id=owners.get(mla, NO_PRODUCT),
            cost_api=cost,
            cost_net=ads_cost_net_of_iva(cost, SOURCE),
            **dict(zip(list(_MLA_SUMS)[1:], values)),
        )
        for mla, cost, *values in found
    ]


def ads_by_product(
    db: Session, date_from: date, date_to: date, product_ids: Optional[Sequence[int]] = None
) -> list[AdsProductRow]:
    """AR-4: the read-time sum of `ads_by_mla` per owner product, "sin producto" (0) included."""
    grouped: dict[int, list[AdsMlaRow]] = {}
    for row in ads_by_mla(db, date_from, date_to):
        grouped.setdefault(row.owner_product_id, []).append(row)
    wanted = None if product_ids is None else set(product_ids)
    return [
        AdsProductRow(
            product_id=product,
            mlas_count=len(rows),
            cost_net=sum((r.cost_net for r in rows), Decimal(0)),
            **{name: sum(getattr(r, name) for r in rows) for name in _MLA_SUMS},
        )
        for product, rows in sorted(grouped.items())
        if wanted is None or product in wanted
    ]


def ads_account_level(db: Session, date_from: date, date_to: date) -> AccountLevel:
    """AR-3: Display (net through the single IVA function, per campaign) and Brand Ads (informational)."""
    D = MlAdsDisplayCampaignDay
    campaigns = [
        DisplayCampaign(campaign, cost, ads_cost_net_of_iva(cost, "display"), prints, clicks)
        for campaign, cost, prints, clicks in db.execute(
            select(D.campaign_id, func.sum(D.consumed_budget), func.sum(D.prints), func.sum(D.clicks))
            .where(D.day.between(date_from, date_to))
            .group_by(D.campaign_id)
            .order_by(D.campaign_id)
        ).all()
    ]
    cost = sum((c.cost_api for c in campaigns), Decimal(0))
    display = DisplayTotals(
        cost,
        ads_cost_net_of_iva(cost, "display"),
        sum(c.prints for c in campaigns),
        sum(c.clicks for c in campaigns),
        campaigns,
    )
    B = MlAdsBrandDay
    brand_cost, brand_prints, brand_clicks = db.execute(
        select(func.sum(B.cost), func.sum(B.prints), func.sum(B.clicks)).where(B.day.between(date_from, date_to))
    ).one()
    return AccountLevel(display, BrandTotals(brand_cost or Decimal(0), brand_prints or 0, brand_clicks or 0))


def ads_coverage(db: Session, date_from: date, date_to: date, *, today: Optional[date] = None) -> Coverage:
    """Which days of the range are not (yet) trustworthy, from the ledger alone (ADS-5).

    A day is missing for an (source, advertiser) the ledger knows when it has no closed/mismatch row; only
    days before `today` (account-local) count, since today is still open. Mismatch days are listed apart."""
    today = today or datetime.now(LOCAL_TZ).date()
    known = db.execute(select(MlAdsDayLedger.source, MlAdsDayLedger.advertiser_id).distinct()).all()
    rows = db.execute(
        select(MlAdsDayLedger.source, MlAdsDayLedger.advertiser_id, MlAdsDayLedger.day, MlAdsDayLedger.status)
        .where(MlAdsDayLedger.day.between(date_from, date_to))
        .order_by(MlAdsDayLedger.source, MlAdsDayLedger.advertiser_id, MlAdsDayLedger.day)
    ).all()
    status = {(source, advertiser, day): value for source, advertiser, day, value in rows}
    last = min(date_to, today - timedelta(days=1))
    missing = [
        CoverageDay(source, advertiser, day, status.get((source, advertiser, day)))
        for source, advertiser in sorted(known)
        for day in (date_from + timedelta(days=n) for n in range((last - date_from).days + 1))
        if status.get((source, advertiser, day)) not in COVERED
    ]
    mismatch = [CoverageDay(s, a, d, v) for s, a, d, v in rows if v == "mismatch"]
    return Coverage(MlAdsCostProvider().availability(db).data_through, missing, mismatch)
