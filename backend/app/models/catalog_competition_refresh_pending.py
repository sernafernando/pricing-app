"""Queue of MLAs waiting for a catalog-competition snapshot refresh.

Enqueued when `hay_mejores_ofertas` is newly set (or re-marked with a new
fingerprint). Drained by `ml_publications.catalog_competition_refresh`.
"""

from __future__ import annotations

from sqlalchemy import Column, DateTime, Index, Integer, String
from sqlalchemy.sql import func

from app.core.database import Base


class CatalogCompetitionRefreshPending(Base):
    """One row per MLA pending a `ml_catalog_competition` snapshot refresh."""

    __tablename__ = "catalog_competition_refresh_pending"

    id = Column(Integer, primary_key=True)
    mla = Column(String(32), nullable=False, unique=True)
    due_at = Column(DateTime(timezone=True), nullable=False)
    attempts = Column(Integer, nullable=False, server_default="0")
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (Index("ix_catalog_competition_refresh_pending_due_at", "due_at"),)

    def __repr__(self) -> str:  # pragma: no cover
        return f"<CatalogCompetitionRefreshPending mla={self.mla!r} due_at={self.due_at!r} attempts={self.attempts!r}>"
