"""ML billing / cost-breakdown schema (corte 1 of ml-ventas-desglose-costos).

Additive tables sourced from the ML billing API (via the ml-webhook proxy),
independent of GBP. Nothing writes to these tables yet -- no reader, writer,
mapper, or client -- that is intentional for this cut, exactly like the
ml_orders_ops slice-1 precedent.

Design decisions:
- `ml_billing_charges.detail_id` is the ML natural key (a string, not an
  integer) for a single billing detail line.
- `ml_billing_charge_orders` is the bridge table that lets a single billing
  detail settle across multiple orders -- the shipping charge for a pack is
  reported once by ML but must be attributed to every order in that pack.
- `ml_billing_period_stats` tracks reconciliation totals per billing period.
  Corte 1 shipped it WITHOUT a uniqueness constraint on `period_key`
  because it had no writer yet; corte 3 (the daily billing sweep) added
  one, since the sweep upserts one stat row per period and would
  otherwise accumulate duplicate rows on every daily re-run.
"""

from __future__ import annotations

from sqlalchemy import (
    BigInteger,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.core.database import Base


class MlBillingCharge(Base):
    """One row per ML billing detail line. Writer of record: billing sweep
    service (a later cut)."""

    __tablename__ = "ml_billing_charges"

    detail_id = Column(String(60), primary_key=True)

    period_key = Column(String(10), nullable=True, index=True)
    detail_type = Column(String(60), nullable=True, index=True)
    detail_sub_type = Column(String(60), nullable=True)
    amount = Column(Numeric(14, 2), nullable=True)
    document_id = Column(String(60), nullable=True)

    raw_detail = Column(JSONB, nullable=True)

    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class MlBillingChargeOrder(Base):
    """Bridge table: a single billing `detail_id` can link to multiple
    `order_id`s (e.g. a pack's shipping charge attributed to every order in
    the pack)."""

    __tablename__ = "ml_billing_charge_orders"

    id = Column(Integer, primary_key=True)
    detail_id = Column(String(60), ForeignKey("ml_billing_charges.detail_id"), nullable=False)
    # BigInteger, NO Integer: un order_id de ML es del orden de
    # 2000018265495500, muy por encima del máximo de un INTEGER de Postgres
    # (2.147.483.647). SQLite no distingue anchos de enteros, así que los
    # tests pasan igual y el desborde recién aparece en el primer INSERT
    # real. Todos los `order_id` de `ml_orders_ops.py` ya son BigInteger.
    order_id = Column(BigInteger, nullable=False)

    charge = relationship("MlBillingCharge")

    __table_args__ = (
        UniqueConstraint("detail_id", "order_id", name="uq_ml_billing_charge_orders_detail_order"),
        Index("ix_ml_billing_charge_orders_order_id", "order_id"),
    )


class MlBillingPeriodStat(Base):
    """Reconciliation totals per ML billing period. Written by the daily
    billing sweep (corte 3), which upserts one row per `period_key`."""

    __tablename__ = "ml_billing_period_stats"

    id = Column(Integer, primary_key=True)
    period_key = Column(String(10), nullable=False, index=True)
    reported_total = Column(Numeric(14, 2), nullable=True)
    stored_total = Column(Numeric(14, 2), nullable=True)
    documents_count_details = Column(Integer, nullable=True)
    swept_at = Column(DateTime(timezone=True), nullable=True)

    __table_args__ = (UniqueConstraint("period_key", name="uq_ml_billing_period_stats_period_key"),)
