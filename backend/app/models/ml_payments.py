"""Mercado Pago payment schema (ml-ventas-desglose-costos, corte 5).

Additive tables sourced from the ML/MP `payment` proxy resource, ingested
by the existing orders sweep (`ml_orders_ingestion/sweep_service.py`) --
no new cron, no new sweep. A payment is fetched per `order.payments[].id`
and refetched every time its order is re-ingested (a return moves the
order and can move the payment's own status/refund amounts with it).

Design decisions (measured live against 514 real payments, see obs #1960
and #1965):

- `ml_payments_ops.payment_id` is `BigInteger`, NOT `Integer`: ML/MP
  payment ids run ~2x10^15, well past a Postgres `INTEGER` (max
  ~2.1x10^9). SQLite does not distinguish integer widths, so this
  overflow is invisible in tests and only appears on the first real
  INSERT -- exactly the corte-1 `ml_billing_charge_orders.order_id`
  lesson, repeated here on purpose.

- `ml_payment_charges` stores EVERY charge line VERBATIM, unfiltered.
  The set of charge `name`s is NOT closed (a new one,
  `tax_withholding_sirtac_sobretasa-tierra_del_fuego`, showed up mid-
  investigation) and re-fetching payment history to backfill a charge
  this table dropped would be expensive. The seller-vs-buyer/coupon
  exclusion rule (obs #1960 §b) is applied ENTIRELY IN READS, never at
  write time -- a future reclassification of a charge type must never
  require re-ingesting anything.

- One order can have SEVERAL `approved` payments that split both the
  total AND the shipping amount between them (order 2000018322969636:
  two approved payments summing to the order total, with the
  `shipping_amount` carried by only one of the two). A payment's net is
  never "the" order's net -- a reader must SUM every `approved` payment
  for an order, never pick one.
"""

from __future__ import annotations

from sqlalchemy import BigInteger, Column, DateTime, ForeignKey, Numeric, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship

from app.core.database import Base


class MlPaymentOps(Base):
    """One row per Mercado Pago payment. A single order can have several
    of these (see module docstring) -- the sum of `approved` rows for an
    `order_id` is the order's net, never a single row's value."""

    __tablename__ = "ml_payments_ops"

    # BigInteger, NOT Integer -- see module docstring. ML/MP's own payment
    # ids are already past the INTEGER range in production.
    payment_id = Column(BigInteger, primary_key=True)

    order_id = Column(BigInteger, nullable=False, index=True)
    status = Column(String(30), nullable=False)

    transaction_amount = Column(Numeric(14, 2), nullable=True)
    shipping_amount = Column(Numeric(14, 2), nullable=True)
    coupon_amount = Column(Numeric(14, 2), nullable=True)
    total_paid_amount = Column(Numeric(14, 2), nullable=True)
    net_received_amount = Column(Numeric(14, 2), nullable=True)
    transaction_amount_refunded = Column(Numeric(14, 2), nullable=True)
    taxes_amount = Column(Numeric(14, 2), nullable=True)

    currency_id = Column(String(10), nullable=True)
    date_approved = Column(DateTime(timezone=True), nullable=True)
    synced_at = Column(DateTime(timezone=True), nullable=True)

    raw_payload = Column(JSONB, nullable=True)

    charges = relationship("MlPaymentCharge", back_populates="payment", cascade="all, delete-orphan")


class MlPaymentCharge(Base):
    """One row per charge line inside a payment's `charges_details[]`,
    stored VERBATIM and UNFILTERED -- see module docstring. The
    seller-vs-buyer exclusion rule is a read-time predicate, never applied
    here."""

    __tablename__ = "ml_payment_charges"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    payment_id = Column(BigInteger, ForeignKey("ml_payments_ops.payment_id"), nullable=False, index=True)

    name = Column(String(120), nullable=False)
    # Nullable because ML sends it null: order 4430760076 carries a
    # `meli_fee` charge with no type at all (older data). While this was
    # NOT NULL the mapper rejected the whole charge, `map_payment`
    # returned a MappingError, and the ENTIRE payment was dropped -- the
    # sale kept an empty net forever over one missing field on one line.
    type = Column(String(30), nullable=True)
    amount = Column(Numeric(14, 2), nullable=True)
    refunded = Column(Numeric(14, 2), nullable=True)

    payment = relationship("MlPaymentOps", back_populates="charges")

    __table_args__ = (UniqueConstraint("payment_id", "name", "type", name="uq_ml_payment_charges_payment_name_type"),)
