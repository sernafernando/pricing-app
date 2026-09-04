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
- `ml_iibb_aliquots` clones the `pricing_constants` fecha_desde/fecha_hasta
  validity-window pattern.
- `ml_billing_period_stats` tracks reconciliation totals per billing period;
  no writer yet, so no uniqueness constraint on `period_key` in this cut.
"""

from __future__ import annotations

from sqlalchemy import (
    CheckConstraint,
    Column,
    Date,
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
    order_id = Column(Integer, nullable=False)

    charge = relationship("MlBillingCharge")

    __table_args__ = (
        UniqueConstraint("detail_id", "order_id", name="uq_ml_billing_charge_orders_detail_order"),
        Index("ix_ml_billing_charge_orders_order_id", "order_id"),
    )


class MlIibbAliquot(Base):
    """IIBB (gross-receipts tax) aliquot with a validity window, cloning the
    `pricing_constants` fecha_desde/fecha_hasta pattern."""

    __tablename__ = "ml_iibb_aliquots"

    id = Column(Integer, primary_key=True, index=True)
    porcentaje = Column(Numeric(6, 4), nullable=False)
    fecha_desde = Column(Date, nullable=False)
    fecha_hasta = Column(Date, nullable=True)
    fecha_creacion = Column(DateTime, default=func.now())
    creado_por = Column(Integer, ForeignKey("usuarios.id"))

    usuario = relationship("Usuario")

    __table_args__ = (
        CheckConstraint("fecha_hasta IS NULL OR fecha_hasta >= fecha_desde", name="chk_ml_iibb_aliquots_fecha_hasta"),
    )


class MlBillingPeriodStat(Base):
    """Reconciliation totals per ML billing period. No writer yet, so no
    uniqueness constraint on `period_key` in this cut."""

    __tablename__ = "ml_billing_period_stats"

    id = Column(Integer, primary_key=True)
    period_key = Column(String(10), nullable=False, index=True)
    reported_total = Column(Numeric(14, 2), nullable=True)
    stored_total = Column(Numeric(14, 2), nullable=True)
    documents_count_details = Column(Integer, nullable=True)
    swept_at = Column(DateTime(timezone=True), nullable=True)
