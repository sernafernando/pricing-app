"""Stored Gauss metrics + the versioned dirty queue that drives their async
recompute (ventas-ml-rediseno, design D1, D2, D3).

`MlOrderMetrics` is 1:1 with `ml_orders_ops`, owned by
`app/services/order_metrics/`, deliberately kept separate from the ingestion
mirror (design D1 rationale: mixing derived metrics into `ml_orders_ops`
couples ingestion upserts with metric writes and makes the upsert
trigger-recursive).

`MlOrderMetricsDirty` is the versioned queue a Postgres trigger (or a system
job) upserts into and the worker (`app/workers/`, PR2+) claims from with
`FOR UPDATE SKIP LOCKED` + a lease. PR1 ships the table alone, inert: no
trigger writes to it yet, no worker reads from it yet (design D3/D5, later
PRs).
"""

from __future__ import annotations

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    SmallInteger,
    String,
    Text,
    false,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func, literal_column

from app.core.database import Base


class MlOrderMetrics(Base):
    """The last-computed Gauss metrics for one order (design D2). Chain
    lines stay in `ml_venta_deducciones`, written by the same recompute --
    never a column here."""

    __tablename__ = "ml_order_metrics"
    __table_args__ = (
        CheckConstraint("gauss_status IN ('ok', 'provisional', 'unresolved')", name="ck_ml_order_metrics_status"),
        Index("ix_ml_order_metrics_status", "gauss_status"),
        # DESC, like the migration. The migration also adds NULLS LAST on
        # Postgres; SQLite rejects NULLS LAST in an index, so the ORM (used by
        # the SQLite test create_all) declares the portable part only.
        Index("ix_ml_order_metrics_total_gauss", literal_column("total_gauss").desc()),
    )

    order_id = Column(BigInteger, ForeignKey("ml_orders_ops.order_id", ondelete="CASCADE"), primary_key=True)

    neto = Column(Numeric(14, 2), nullable=True)
    neto_sin_iva = Column(Numeric(14, 2), nullable=True)
    iva_reconcilia = Column(Boolean, nullable=True)
    costo_mercaderia = Column(Numeric(14, 2), nullable=True)
    # NULL iff gauss_status='unresolved' (design D2) -- never a fabricated 0.
    total_gauss = Column(Numeric(14, 2), nullable=True)
    markup_pct = Column(Numeric(9, 2), nullable=True)
    gauss_status = Column(String(16), nullable=False)
    provisional_falta = Column(String(64), nullable=True)
    unresolved_reason = Column(String(64), nullable=True)
    # Bumped by `order_metrics.constants.CURRENT_FORMULA_VERSION` whenever
    # the formula changes -- `order_metrics.reconcile` (PR6) re-enqueues any
    # row with `formula_version < CURRENT_FORMULA_VERSION` (design D8/D10).
    formula_version = Column(SmallInteger, nullable=False)
    computed_at = Column(DateTime(timezone=True), nullable=False)


class MlOrderMetricsDirty(Base):
    """Versioned dirty queue (design D3). Two PL/pgSQL helpers write here
    with different conflict semantics (`order_metrics_enqueue` for input
    writes, `order_metrics_enqueue_system` for reconcile/divergence,
    PR4/PR6) -- this table's DDL alone ships in PR1, inert until then."""

    __tablename__ = "ml_order_metrics_dirty"
    __table_args__ = (Index("ix_ml_order_metrics_dirty_enqueued_at", "enqueued_at"),)

    order_id = Column(BigInteger, primary_key=True)
    version = Column(BigInteger, nullable=False, server_default=text("1"))
    reason = Column(String(32), nullable=False)
    enqueued_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    claimed_at = Column(DateTime(timezone=True), nullable=True)
    claimed_by = Column(String(64), nullable=True)
    claim_token = Column(UUID(as_uuid=True), nullable=True)
    attempts = Column(SmallInteger, nullable=False, server_default=text("0"))
    last_error = Column(Text, nullable=True)
    # `True` when a batch-timeout release put this order back in the queue
    # without charging an attempt (design D5) -- retried alone, never
    # re-enters a full batch, durable across worker restarts.
    suspect = Column(Boolean, nullable=False, server_default=false())
