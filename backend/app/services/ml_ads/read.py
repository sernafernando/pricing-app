"""Ads read side (ml-billing-balance, design D9): the native cost provider and its adapter to the
publications view.

Everything here is a query over the stored facts; no sum is ever stored (ADS-4). Only `product_ads` cost per
MLA feeds these functions: Display and Brand Ads are account-level and are never attributed to an MLA.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Literal, Mapping, Optional, Sequence

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.ml_ads import MlAdsDayLedger, MlAdsItemDay
from app.services.ml_ads.iva import ads_cost_net_of_iva
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
