"""Persistence for the ads day ingestion (ADS-3, ADS-4, D2, D3).

Writers are idempotent upserts keyed by the natural keys of the tables. Nothing here stores a sum
of ours: `group_cost_sum` and `item_cost_by_group` are queries over the rows, evaluated when a day is
closed. Functions flush but never commit; the caller owns the transaction, so a day closes (or a
page lands) atomically with its ledger update.

A "fetch" is delimited by `ledger.fetch_started_at`: rows written by it have `fetched_at >=` that
instant. That is what lets a replayed page keep its drill progress while a new fetch resets it, and
what lets `delete_stale` drop the rows ML no longer reports.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Iterable, Optional

from sqlalchemy import case, delete, func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.models.ml_ads import MlAdsAdGroupDay, MlAdsDayLedger, MlAdsItemDay
from app.services.ml_ads.mapper import DaySummary, GroupFact, ItemFact

SOURCE = "product_ads"
UNFINISHED = "fetching"


def get_ledger(db: Session, advertiser_id: int, day: date) -> Optional[MlAdsDayLedger]:
    return db.get(MlAdsDayLedger, (SOURCE, advertiser_id, day))


def start_fetch(db: Session, advertiser_id: int, day: date, *, now: datetime) -> MlAdsDayLedger:
    """Open the day for fetching. A day already `fetching` is resumed untouched; any other status restarts."""
    ledger = get_ledger(db, advertiser_id, day)
    if ledger is None:
        ledger = MlAdsDayLedger(
            source=SOURCE,
            advertiser_id=advertiser_id,
            day=day,
            status="fetching",
            fetch_started_at=now,
            groups_offset=0,
        )
        db.add(ledger)
    elif ledger.status != UNFINISHED:
        ledger.status = "fetching"
        ledger.fetch_started_at = now
        ledger.groups_offset = 0
        ledger.closed_at = None
        ledger.last_error = None
    db.flush()
    return ledger


def set_groups_offset(db: Session, advertiser_id: int, day: date, offset: int) -> None:
    ledger = get_ledger(db, advertiser_id, day)
    ledger.groups_offset = offset
    db.flush()


def finish_day(
    db: Session, advertiser_id: int, day: date, *, status: str, summary: Optional[DaySummary], now: datetime
) -> MlAdsDayLedger:
    ledger = get_ledger(db, advertiser_id, day)
    ledger.status = status
    if summary is not None:
        ledger.summary_cost = summary.cost
        ledger.summary_raw = dict(summary.raw)
    ledger.closed_at = now if status == "closed" else None
    db.flush()
    return ledger


def upsert_groups(db: Session, facts: Iterable[GroupFact], *, fetch_started_at: datetime, now: datetime) -> None:
    rows = [
        {
            "advertiser_id": f.advertiser_id,
            "ad_group_id": f.ad_group_id,
            "day": f.day,
            "campaign_id": f.campaign_id,
            "ad_group_type": f.ad_group_type,
            "external_id": f.external_id,
            "cost": f.cost,
            "direct_amount": f.direct_amount,
            "indirect_amount": f.indirect_amount,
            "clicks": f.clicks,
            "prints": f.prints,
            "units_quantity": f.units_quantity,
            "drill_status": "pending" if f.needs_drill else "not_needed",
            "ads_offset": 0,
            "raw": dict(f.raw),
            "fetched_at": now,
        }
        for f in facts
    ]
    if not rows:
        return
    stmt = pg_insert(MlAdsAdGroupDay).values(rows)
    table = MlAdsAdGroupDay.__table__
    in_this_fetch = table.c.fetched_at >= fetch_started_at
    refreshed = {
        name: getattr(stmt.excluded, name)
        for name in (
            "campaign_id",
            "ad_group_type",
            "external_id",
            "cost",
            "direct_amount",
            "indirect_amount",
            "clicks",
            "prints",
            "units_quantity",
            "raw",
            "fetched_at",
        )
    }
    # Drill progress survives a replayed page of the SAME fetch and resets on a new one.
    refreshed["drill_status"] = case((in_this_fetch, table.c.drill_status), else_=stmt.excluded.drill_status)
    refreshed["ads_offset"] = case((in_this_fetch, table.c.ads_offset), else_=0)
    db.execute(stmt.on_conflict_do_update(index_elements=["advertiser_id", "ad_group_id", "day"], set_=refreshed))
    db.flush()


def upsert_items(db: Session, facts: Iterable[ItemFact], *, now: datetime) -> None:
    rows = [
        {
            "advertiser_id": f.advertiser_id,
            "ad_group_id": f.ad_group_id,
            "item_id": f.item_id,
            "day": f.day,
            "campaign_id": f.campaign_id,
            "cost": f.cost,
            "direct_amount": f.direct_amount,
            "indirect_amount": f.indirect_amount,
            "organic_amount": f.organic_amount,
            "clicks": f.clicks,
            "direct_units": f.direct_units,
            "indirect_units": f.indirect_units,
            "organic_units": f.organic_units,
            "prints": f.prints,
            "raw": dict(f.raw),
            "fetched_at": now,
        }
        for f in facts
    ]
    if not rows:
        return
    stmt = pg_insert(MlAdsItemDay).values(rows)
    refreshed = {
        name: getattr(stmt.excluded, name)
        for name in (
            "campaign_id",
            "cost",
            "direct_amount",
            "indirect_amount",
            "organic_amount",
            "clicks",
            "direct_units",
            "indirect_units",
            "organic_units",
            "prints",
            "raw",
            "fetched_at",
        )
    }
    db.execute(
        stmt.on_conflict_do_update(index_elements=["advertiser_id", "ad_group_id", "item_id", "day"], set_=refreshed)
    )
    db.flush()


def set_drill(db: Session, advertiser_id: int, ad_group_id: int, day: date, *, status: str, ads_offset: int) -> None:
    db.execute(
        update(MlAdsAdGroupDay)
        .where(
            MlAdsAdGroupDay.advertiser_id == advertiser_id,
            MlAdsAdGroupDay.ad_group_id == ad_group_id,
            MlAdsAdGroupDay.day == day,
        )
        .values(drill_status=status, ads_offset=ads_offset)
    )
    db.flush()


def pending_groups(db: Session, advertiser_id: int, day: date) -> list[tuple[int, int]]:
    """Groups still to drill as `(ad_group_id, ads_offset)`, in id order. `done` groups are never listed."""
    rows = db.execute(
        select(MlAdsAdGroupDay.ad_group_id, MlAdsAdGroupDay.ads_offset)
        .where(
            MlAdsAdGroupDay.advertiser_id == advertiser_id,
            MlAdsAdGroupDay.day == day,
            MlAdsAdGroupDay.drill_status == "pending",
        )
        .order_by(MlAdsAdGroupDay.ad_group_id)
    ).all()
    return [(group_id, offset) for group_id, offset in rows]


def group_cost_sum(db: Session, advertiser_id: int, day: date) -> Decimal:
    total = db.execute(
        select(func.coalesce(func.sum(MlAdsAdGroupDay.cost), 0)).where(
            MlAdsAdGroupDay.advertiser_id == advertiser_id, MlAdsAdGroupDay.day == day
        )
    ).scalar_one()
    return Decimal(total)


def item_cost_by_group(db: Session, advertiser_id: int, day: date) -> dict[int, Decimal]:
    rows = db.execute(
        select(MlAdsItemDay.ad_group_id, func.sum(MlAdsItemDay.cost))
        .where(MlAdsItemDay.advertiser_id == advertiser_id, MlAdsItemDay.day == day)
        .group_by(MlAdsItemDay.ad_group_id)
    ).all()
    return {group_id: Decimal(total) for group_id, total in rows}


def delete_stale(db: Session, advertiser_id: int, day: date, *, fetch_started_at: datetime) -> None:
    """Drop the day's rows that the current fetch did not rewrite (ML no longer reports them)."""
    for model in (MlAdsItemDay, MlAdsAdGroupDay):
        db.execute(
            delete(model).where(
                model.advertiser_id == advertiser_id, model.day == day, model.fetched_at < fetch_started_at
            )
        )
    db.flush()


@dataclass(frozen=True)
class DayCheck:
    group_cost: Decimal
    groups: int


def day_check(db: Session, advertiser_id: int, day: date) -> DayCheck:
    group_cost, groups = db.execute(
        select(func.coalesce(func.sum(MlAdsAdGroupDay.cost), 0), func.count()).where(
            MlAdsAdGroupDay.advertiser_id == advertiser_id, MlAdsAdGroupDay.day == day
        )
    ).one()
    return DayCheck(Decimal(group_cost), groups)
