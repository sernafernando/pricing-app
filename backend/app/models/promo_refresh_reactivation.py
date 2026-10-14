"""Queue of publications that became active again and owe a promotions-mirror refresh.

Its own table, NOT `promo_refresh_pending`: that one belongs to the panel write path and its cron-era drainer
(`app/scripts/drain_promo_refresh.py`), which has its own retry policy and refreshes without looking at the
publication's status. Sharing rows would mean two drainers racing on one lease-less table. This queue is fed by
the ML publications store (`events_store.write_events`) and drained only by `ml_publications.promo_refresh`.
"""

from __future__ import annotations

from sqlalchemy import Column, DateTime, Index, Integer, String
from sqlalchemy.sql import func

from app.core.database import Base


class PromoRefreshReactivation(Base):
    """One row per `mla` waiting for its promotions refresh after a reactivation."""

    __tablename__ = "promo_refresh_reactivation"

    id = Column(Integer, primary_key=True, index=True)
    mla = Column(String(32), nullable=False, unique=True)
    due_at = Column(DateTime(timezone=True), nullable=False)
    attempts = Column(Integer, nullable=False, default=0, server_default="0")
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (Index("ix_promo_refresh_reactivation_due_at", "due_at"),)

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return f"<PromoRefreshReactivation mla={self.mla!r} due_at={self.due_at!r} attempts={self.attempts!r}>"
