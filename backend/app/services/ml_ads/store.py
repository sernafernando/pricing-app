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
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any, Iterable, Mapping, Optional

from sqlalchemy import and_, case, delete, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.models.ml_ads import MlAdsAdGroupDay, MlAdsDayLedger, MlAdsDisplayCampaignDay, MlAdsItemDay
from app.services.ml_ads.mapper import DaySummary, DisplayFact, GroupFact, ItemFact

SOURCE = "product_ads"
DISPLAY_SOURCE = "display"
UNFINISHED = "fetching"
# `groups_offset` is the offset of the next `ad_groups/search` page; this value says every page was read,
# so a resumed day goes straight to the drill instead of asking ML for a page past the end.
GROUPS_DONE = -1


def get_ledger(db: Session, advertiser_id: int, day: date, *, source: str = SOURCE) -> Optional[MlAdsDayLedger]:
    return db.get(MlAdsDayLedger, (source, advertiser_id, day))


def start_fetch(db: Session, advertiser_id: int, day: date, *, now: datetime, source: str = SOURCE) -> MlAdsDayLedger:
    """Open the day for fetching. A day already `fetching` is resumed untouched; any other status restarts."""
    ledger = get_ledger(db, advertiser_id, day, source=source)
    if ledger is None:
        ledger = MlAdsDayLedger(
            source=source,
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


def set_groups_offset(db: Session, advertiser_id: int, day: date, offset: int, *, source: str = SOURCE) -> None:
    ledger = get_ledger(db, advertiser_id, day, source=source)
    ledger.groups_offset = offset
    db.flush()


def finish_day(
    db: Session,
    advertiser_id: int,
    day: date,
    *,
    status: str,
    summary: Optional[DaySummary],
    now: datetime,
    source: str = SOURCE,
    detail: Optional[Mapping[str, Any]] = None,
) -> MlAdsDayLedger:
    """`detail` is for sources without an ML day total (Display): it goes to `summary_raw` as is."""
    ledger = get_ledger(db, advertiser_id, day, source=source)
    ledger.status = status
    if summary is not None:
        ledger.summary_cost = summary.cost
        ledger.summary_raw = dict(summary.raw)
    elif detail is not None:
        ledger.summary_raw = dict(detail)
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
class DrillSums:
    """Computed when a group's last `/ads` page lands; compared with ML's own group cost, never stored."""

    group_cost: Decimal
    items_cost: Decimal
    items: int


def drill_sums(
    db: Session, advertiser_id: int, ad_group_id: int, day: date, *, fetch_started_at: datetime
) -> DrillSums:
    group_cost = db.execute(
        select(MlAdsAdGroupDay.cost).where(
            MlAdsAdGroupDay.advertiser_id == advertiser_id,
            MlAdsAdGroupDay.ad_group_id == ad_group_id,
            MlAdsAdGroupDay.day == day,
        )
    ).scalar_one()
    items_cost, items = db.execute(
        select(func.coalesce(func.sum(MlAdsItemDay.cost), 0), func.count()).where(
            MlAdsItemDay.advertiser_id == advertiser_id,
            MlAdsItemDay.ad_group_id == ad_group_id,
            MlAdsItemDay.day == day,
            # Rows of an earlier fetch are only dropped when the day closes; they must not count here.
            MlAdsItemDay.fetched_at >= fetch_started_at,
        )
    ).one()
    return DrillSums(Decimal(group_cost), Decimal(items_cost), items)


@dataclass(frozen=True)
class DayCheck:
    group_cost: Decimal
    groups: int
    pending: int
    drill_mismatches: int


def day_check(db: Session, advertiser_id: int, day: date) -> DayCheck:
    group_cost, groups, pending, drill_mismatches = db.execute(
        select(
            func.coalesce(func.sum(MlAdsAdGroupDay.cost), 0),
            func.count(),
            func.count().filter(MlAdsAdGroupDay.drill_status == "pending"),
            func.count().filter(MlAdsAdGroupDay.drill_status == "mismatch"),
        ).where(MlAdsAdGroupDay.advertiser_id == advertiser_id, MlAdsAdGroupDay.day == day)
    ).one()
    return DayCheck(Decimal(group_cost), groups, pending, drill_mismatches)


def attempts_exhausted(
    db: Session, advertiser_id: int, day: date, *, today: date, limit: int, source: str = SOURCE
) -> bool:
    ledger = get_ledger(db, advertiser_id, day, source=source)
    return ledger is not None and ledger.attempts_day == today and ledger.attempts >= limit


def record_failure(db: Session, advertiser_id: int, day: date, *, today: date, error: str, source: str = SOURCE) -> int:
    """Count one failed attempt for the local day `today` (the counter restarts on a new local day)."""
    ledger = get_ledger(db, advertiser_id, day, source=source)
    if ledger.attempts_day != today:
        ledger.attempts = 0
        ledger.attempts_day = today
    ledger.attempts += 1
    ledger.last_error = error[:500]
    db.flush()
    return ledger.attempts


# --- work selection for the scheduler (ADS-5, ADS-6) -------------------------------------------------

OPEN_STATUSES = ("fetching", "refetch")


def open_units(db: Session, *, source: str = SOURCE) -> list[tuple[int, date]]:
    """Days left `fetching` or marked `refetch`, as `(advertiser_id, day)`, oldest day first (it expires first)."""
    rows = db.execute(
        select(MlAdsDayLedger.advertiser_id, MlAdsDayLedger.day)
        .where(MlAdsDayLedger.source == source, MlAdsDayLedger.status.in_(OPEN_STATUSES))
        .order_by(MlAdsDayLedger.day, MlAdsDayLedger.advertiser_id)
    ).all()
    return [(advertiser_id, day) for advertiser_id, day in rows]


def ledgered(db: Session, first: date, last: date, *, source: str = SOURCE) -> set[tuple[int, date]]:
    """Every `(advertiser_id, day)` in the window that has a ledger row, whatever its status ("fetched" at all)."""
    rows = db.execute(
        select(MlAdsDayLedger.advertiser_id, MlAdsDayLedger.day).where(
            MlAdsDayLedger.source == source, MlAdsDayLedger.day.between(first, last)
        )
    ).all()
    return {(advertiser_id, day) for advertiser_id, day in rows}


def reopen_for_daily_run(db: Session, *, today: date, recent_days: int, max_laps: int, source: str = SOURCE) -> None:
    """The once-a-day refresh: D-1..D-`recent_days` are refetched, and so is a mismatch that has had fewer than
    `max_laps` retries (D4). Days that are still being fetched are left alone."""
    recent = and_(
        MlAdsDayLedger.day >= today - timedelta(days=recent_days), MlAdsDayLedger.status.in_(("closed", "mismatch"))
    )
    lapped = and_(MlAdsDayLedger.status == "mismatch", MlAdsDayLedger.mismatch_laps < max_laps)
    db.execute(
        update(MlAdsDayLedger)
        .where(MlAdsDayLedger.source == source, or_(recent, lapped))
        .values(
            mismatch_laps=MlAdsDayLedger.mismatch_laps + case((MlAdsDayLedger.status == "mismatch", 1), else_=0),
            status="refetch",
        )
    )
    db.flush()


def unverified(
    db: Session, *, today: date, newest_ago: int, oldest_ago: int, since: datetime
) -> list[tuple[int, date]]:
    """Closed, non-final days from D-`oldest_ago` to D-`newest_ago` not closed or verified since `since`."""
    checked = func.greatest(MlAdsDayLedger.verified_at, MlAdsDayLedger.closed_at)
    rows = db.execute(
        select(MlAdsDayLedger.advertiser_id, MlAdsDayLedger.day)
        .where(
            MlAdsDayLedger.source == SOURCE,
            MlAdsDayLedger.status == "closed",
            MlAdsDayLedger.final.is_(False),
            MlAdsDayLedger.day.between(today - timedelta(days=oldest_ago), today - timedelta(days=newest_ago)),
            checked < since,
        )
        .order_by(MlAdsDayLedger.day, MlAdsDayLedger.advertiser_id)
    ).all()
    return [(advertiser_id, day) for advertiser_id, day in rows]


def finalize_old(db: Session, *, before: date) -> None:
    """Closed days older than the verification window are `final`: ML no longer changes them."""
    db.execute(
        update(MlAdsDayLedger)
        .where(
            MlAdsDayLedger.source == SOURCE,
            MlAdsDayLedger.status == "closed",
            MlAdsDayLedger.final.is_(False),
            MlAdsDayLedger.day < before,
        )
        .values(final=True)
    )
    db.flush()


# --- Display (account-level, ADS-9) -----------------------------------------------------------------


def upsert_display_days(db: Session, facts: Iterable[DisplayFact], *, now: datetime) -> None:
    rows = [
        {
            "advertiser_id": f.advertiser_id,
            "campaign_id": f.campaign_id,
            "day": f.day,
            "consumed_budget": f.consumed_budget,
            "prints": f.prints,
            "clicks": f.clicks,
            "reach": f.reach,
            "raw": dict(f.raw),
            "fetched_at": now,
        }
        for f in facts
    ]
    if not rows:
        return
    stmt = pg_insert(MlAdsDisplayCampaignDay).values(rows)
    refreshed = {
        name: getattr(stmt.excluded, name)
        for name in ("consumed_budget", "prints", "clicks", "reach", "raw", "fetched_at")
    }
    db.execute(stmt.on_conflict_do_update(index_elements=["advertiser_id", "campaign_id", "day"], set_=refreshed))
    db.flush()


def delete_stale_display(db: Session, advertiser_id: int, day: date, *, fetch_started_at: datetime) -> None:
    """Drop the day's Display rows that the current fetch did not rewrite (the campaign lost its activity)."""
    db.execute(
        delete(MlAdsDisplayCampaignDay).where(
            MlAdsDisplayCampaignDay.advertiser_id == advertiser_id,
            MlAdsDisplayCampaignDay.day == day,
            MlAdsDisplayCampaignDay.fetched_at < fetch_started_at,
        )
    )
    db.flush()
