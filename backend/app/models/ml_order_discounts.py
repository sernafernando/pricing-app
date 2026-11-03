"""Per-sale discounts as ML reports them (ml-ads-cupones-display T3a): `GET /orders/{order_id}/discounts`.

`ml_order_discounts` keeps one row per order: the body exactly as ML sent it and the outcome of the fetch.
`ml_order_discount_lines` is derived from that body when it is written (one row per detail and item), so the
Cupones tab can sum per coupon campaign and per funder without reading JSON. `ml_order_discounts_state` is
the single back-off row of the ingestion (repeated 429s).

Sales carry no coupon id anywhere else (`raw_order.coupon.id` is always null, payment charges have no id).
"""

from __future__ import annotations

from sqlalchemy import BigInteger, Column, DateTime, Index, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.sql import func

from app.core.database import Base
from app.models.ml_payments import MlPaymentOps


class MlOrderDiscounts(Base):
    """One fetch of an order's discounts. `status`: `ok` (a body with `details`), `none` (ML's 404 "Discount not
    found": the sale has no discounts) or `error` (retried up to the ingestion's attempt limit)."""

    __tablename__ = "ml_order_discounts"

    order_id = Column(BigInteger, primary_key=True)
    status = Column(String(10), nullable=False)
    http_status = Column(Integer, nullable=True)  # ML's own status: the body's `status` when it carries one
    body = Column(JSONB, nullable=True)
    attempts = Column(Integer, nullable=False, server_default="0", default=0)
    fetched_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class MlOrderDiscountLine(Base):
    """One item of one `details[]` entry. `type` is ML's (`coupon`, `discount`, ...); the coupon and supplier
    fields are null when ML does not send them. `amount_seller` is what the seller funds of `amount_total`."""

    __tablename__ = "ml_order_discount_lines"
    __table_args__ = (UniqueConstraint("order_id", "detail_index", "item_index", name="uq_ml_order_discount_lines"),)

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    order_id = Column(BigInteger, nullable=False, index=True)
    detail_index = Column(Integer, nullable=False)
    item_index = Column(Integer, nullable=False)
    type = Column(String(40), nullable=True)
    coupon_id = Column(BigInteger, nullable=True, index=True)
    campaign_id = Column(BigInteger, nullable=True)
    meli_campaign = Column(Text, nullable=True)
    offer_id = Column(Text, nullable=True)
    funding_mode = Column(String(40), nullable=True)
    item_id = Column(String(40), nullable=True)
    element_id = Column(Integer, nullable=True)
    quantity = Column(Integer, nullable=True)
    amount_seller = Column(Numeric(14, 2), nullable=True)
    amount_total = Column(Numeric(14, 2), nullable=True)


class MlOrderDiscountsState(Base):
    """The ingestion's back-off (single row, `id` 1): consecutive 429 runs and the instant before which no run
    calls ML. Reset by a run answered with no 429."""

    __tablename__ = "ml_order_discounts_state"

    id = Column(Integer, primary_key=True)
    consecutive_429 = Column(Integer, nullable=False, server_default="0", default=0)
    backoff_until = Column(DateTime(timezone=True), nullable=True)


# The ingestion's pending query reads only the payments with a coupon (a small part of `ml_payments_ops`), every
# few seconds: a partial index keeps it cheap as the table grows. Declared here, next to its only reader.
Index(
    "ix_ml_payments_ops_coupon_order_id",
    MlPaymentOps.order_id,
    postgresql_where=MlPaymentOps.coupon_amount > 0,
)
