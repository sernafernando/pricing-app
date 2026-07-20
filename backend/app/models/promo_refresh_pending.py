"""Persisted retry queue for the promo point-refresh (promo-state-dynamic-refresh).

Mirrors `promo_sync_watermark.py`'s minimal shape: no existing key-value/
queue table exists in this codebase to reuse, and a dedicated table keeps
the queue queryable/auditable like any other model.

One row per `mla` (UNIQUE) is enqueued by `_maybe_refresh_after_write` right
after the immediate best-effort refresh, so a slower-consistency write
(e.g. SMART, ~10-18s) still gets a reliable follow-up refresh even if the
operator closes the panel. The drainer script
(`app/scripts/drain_promo_refresh.py`) polls `due_at <= now()` every
minute, deletes the row on a successful refresh, and backs off/quarantines
on repeated failure.
"""

from __future__ import annotations

from sqlalchemy import Column, DateTime, Index, Integer, String
from sqlalchemy.sql import func

from app.core.database import Base


class PromoRefreshPending(Base):
    """One row per `mla` pending a server-side promo point-refresh."""

    __tablename__ = "promo_refresh_pending"

    id = Column(Integer, primary_key=True, index=True)
    mla = Column(String(32), nullable=False, unique=True)
    due_at = Column(DateTime(timezone=True), nullable=False)
    attempts = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (Index("ix_promo_refresh_pending_due_at", "due_at"),)

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return f"<PromoRefreshPending mla={self.mla!r} due_at={self.due_at!r} attempts={self.attempts!r}>"
