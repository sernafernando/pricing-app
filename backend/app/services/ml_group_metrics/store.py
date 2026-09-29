"""The single writer of group-level Gauss metrics (ventas-ml-rediseno
PR20.T9/T10, design D7). Mirrors `order_metrics.store.store_order_metrics`'s
contract exactly: upserts `ml_group_metrics` via a real
`INSERT ... ON CONFLICT DO UPDATE` (same last-write-wins-under-concurrency
rationale as the per-order writer), NEVER commits -- the caller controls
the transaction.
"""

from __future__ import annotations

from typing import Dict

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql, sqlite
from sqlalchemy.orm import Session

from app.models.ml_group_metrics import MlGroupMetrics
from app.services.ml_group_metrics.compute import GroupMetrics


def _insert(db: Session, table):
    if db.get_bind().dialect.name == "postgresql":
        return postgresql.insert(table)
    return sqlite.insert(table)


def store_group_metrics(db: Session, group_metrics_by_key: Dict[str, GroupMetrics]) -> None:
    """Store-only upsert of `ml_group_metrics`, one row per group. NEVER
    commits -- same contract as `order_metrics.store.store_order_metrics`,
    so a caller can compose it inside the same short transaction as the
    per-order store (PR20.T11/T12)."""
    if not group_metrics_by_key:
        return

    rows = [
        {
            "group_key": metrics.group_key,
            "neto": metrics.neto,
            "neto_sin_iva": metrics.neto_sin_iva,
            "costo_mercaderia": metrics.costo_mercaderia,
            "total_gauss": metrics.total_gauss,
            "markup_pct": metrics.markup_pct,
            "gauss_status": metrics.gauss_status,
            "gross_amount": metrics.gross_amount,
            "currency_id": metrics.currency_id,
            "member_order_ids": list(metrics.member_order_ids),
            "group_date": metrics.group_date,
            "formula_version": metrics.formula_version,
            "computed_at": metrics.computed_at,
        }
        for metrics in group_metrics_by_key.values()
    ]

    stmt = _insert(db, MlGroupMetrics.__table__)
    if db.get_bind().dialect.name == "postgresql":
        # `member_order_ids`'s bind type must be forced explicitly here,
        # NEVER inferred from `MlGroupMetrics.__table__.c.member_order_ids
        # .type` at execute time: several `@pytest.mark.postgres` test
        # fixtures (`tests/conftest.py`) share ONE mutable `Base.metadata`
        # across the whole test session and monkey-patch every
        # `postgresql.ARRAY`/`JSONB`/`UUID` column's `.type` to a
        # SQLite-compatible stand-in (JSON) right after their own DDL runs,
        # so the SAME `Column` object this statement would otherwise infer
        # its bind type from can be JSON by the time this INSERT executes
        # against a REAL Postgres connection later in the same session --
        # JSON-encoding a Python list produces a string Postgres's array
        # parser then rejects ("Missing \"=\" after array dimensions").
        # An explicit `bindparam` type pins the correct wire type
        # regardless of what the shared metadata looks like at this
        # moment.
        stmt = stmt.values(member_order_ids=sa.bindparam("member_order_ids", type_=postgresql.ARRAY(sa.BigInteger)))
    stmt = stmt.on_conflict_do_update(
        index_elements=["group_key"],
        set_={
            "neto": stmt.excluded.neto,
            "neto_sin_iva": stmt.excluded.neto_sin_iva,
            "costo_mercaderia": stmt.excluded.costo_mercaderia,
            "total_gauss": stmt.excluded.total_gauss,
            "markup_pct": stmt.excluded.markup_pct,
            "gauss_status": stmt.excluded.gauss_status,
            # Both lists have to know: a field listed only on the INSERT path
            # round-trips once and then goes stale on every later recompute.
            "gross_amount": stmt.excluded.gross_amount,
            "currency_id": stmt.excluded.currency_id,
            "member_order_ids": stmt.excluded.member_order_ids,
            "group_date": stmt.excluded.group_date,
            "formula_version": stmt.excluded.formula_version,
            "computed_at": stmt.excluded.computed_at,
        },
    )
    db.execute(stmt, rows)
