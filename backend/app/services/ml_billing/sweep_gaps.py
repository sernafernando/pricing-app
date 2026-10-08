"""Gaps of the billing sweep (ml-billing-balance PR 4a, BS-7).

A position ML refused with a bare 400 is recorded here instead of halting the
period. A gap is a pointer to what is missing, never a substitute for it: the
missing row keeps its document incomplete through the per-document
completeness query, so nothing here is read to decide completeness.

Re-seeing a gap upserts it (`seen_count` and `last_seen_at` move, `first_seen_at`
stays). A gap that fails again after it was resolved opens again, because the
row is missing again.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import select, update
from sqlalchemy.dialects import postgresql, sqlite
from sqlalchemy.orm import Session

from app.models.ml_billing import MlBillingSweepGap

_KEY = ("period_key", "document_type", "billing_source", "paging", "position")


def _insert_stmt(db: Session):
    """Same dialect pick as `ml_billing_ingestion/ingestion_service.py`."""
    dialect_name = db.bind.dialect.name if db.bind is not None else "postgresql"
    if dialect_name == "sqlite":
        return sqlite.insert(MlBillingSweepGap.__table__)
    return postgresql.insert(MlBillingSweepGap.__table__)


def record_gap(
    db: Session,
    *,
    period_key: str,
    document_type: str,
    billing_source: str,
    paging: str,
    position: str,
    window: Optional[str],
    http_status: Optional[int],
    error: Optional[str],
    now: datetime,
    lap_id: Optional[str] = None,
) -> None:
    """Upserts the gap at `position`. The caller commits."""
    values = {
        "period_key": period_key,
        "document_type": document_type,
        "billing_source": billing_source,
        "paging": paging,
        "position": str(position),
        "window": window,
        "http_status": http_status,
        "error": error,
        "first_seen_at": now,
        "last_seen_at": now,
        "seen_count": 1,
        "resolved_at": None,
        "lap_id": lap_id,
    }
    stmt = _insert_stmt(db).values(**values)
    table = MlBillingSweepGap.__table__
    stmt = stmt.on_conflict_do_update(
        index_elements=list(_KEY),
        set_={
            "window": stmt.excluded.window,
            "http_status": stmt.excluded.http_status,
            "error": stmt.excluded.error,
            "last_seen_at": stmt.excluded.last_seen_at,
            "seen_count": table.c.seen_count + 1,
            "resolved_at": None,
            "lap_id": stmt.excluded.lap_id,
        },
    )
    db.execute(stmt)


def resolve_gap(
    db: Session,
    *,
    period_key: str,
    document_type: str,
    billing_source: str,
    paging: str,
    position: str,
    now: datetime,
) -> bool:
    """Marks the gap at `position` resolved after a successful read of it.

    Returns True only when an open gap was resolved: an already resolved gap
    keeps its first resolution time and an unknown position is a no-op. The
    caller commits.
    """
    table = MlBillingSweepGap.__table__
    result = db.execute(
        update(table)
        .where(
            table.c.period_key == period_key,
            table.c.document_type == document_type,
            table.c.billing_source == billing_source,
            table.c.paging == paging,
            table.c.position == str(position),
            table.c.resolved_at.is_(None),
        )
        .values(resolved_at=now)
    )
    return result.rowcount > 0


def open_gaps(db: Session, period_key: str, document_type: Optional[str] = None) -> list[MlBillingSweepGap]:
    """Unresolved gaps of a period, ordered by position (numerically)."""
    query = select(MlBillingSweepGap).where(
        MlBillingSweepGap.period_key == period_key,
        MlBillingSweepGap.resolved_at.is_(None),
    )
    if document_type is not None:
        query = query.where(MlBillingSweepGap.document_type == document_type)
    gaps = list(db.execute(query).scalars())
    # Positions are strings: sort numerically so 9 comes before 10.
    return sorted(gaps, key=lambda gap: (gap.document_type, int(gap.position) if gap.position.isdigit() else -1))
