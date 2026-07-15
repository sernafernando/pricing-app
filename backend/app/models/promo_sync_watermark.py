"""Watermark for the periodic promo-price sync job (slice 4).

A single row keyed by `job_name` tracks the last `ml_item_promotions.updated_at`
value fully processed by `app/scripts/sync_promo_prices.py`. This is the
simplest correct storage: no existing key-value/config table exists in this
codebase to reuse (checked `app/models/*` before adding this), and a
dedicated table keeps the watermark queryable/auditable like any other model.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import Column, DateTime, Integer, String
from sqlalchemy.orm import Session

from app.core.database import Base

SYNC_PROMO_PRICES_JOB = "sync_promo_prices"


class PromoSyncWatermark(Base):
    """One row per job_name; `last_updated_at` is the max
    `ml_item_promotions.updated_at` fully processed so far."""

    __tablename__ = "promo_sync_watermark"

    id = Column(Integer, primary_key=True, index=True)
    job_name = Column(String(100), nullable=False, unique=True)
    last_updated_at = Column(DateTime(timezone=True), nullable=True)


def get_watermark(db: Session, job_name: str = SYNC_PROMO_PRICES_JOB) -> Optional[datetime]:
    """Returns the persisted watermark, or None if the job has never run
    successfully (first run processes everything currently active)."""
    row = db.query(PromoSyncWatermark).filter(PromoSyncWatermark.job_name == job_name).first()
    return row.last_updated_at if row else None


def set_watermark(db: Session, value: datetime, job_name: str = SYNC_PROMO_PRICES_JOB) -> None:
    """Upserts the watermark. Does not commit — caller controls the
    transaction boundary (only call this after a fully successful pass)."""
    row = db.query(PromoSyncWatermark).filter(PromoSyncWatermark.job_name == job_name).first()
    if row:
        row.last_updated_at = value
    else:
        db.add(PromoSyncWatermark(job_name=job_name, last_updated_at=value))
