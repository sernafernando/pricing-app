"""ml_order_discounts, ml_order_discount_lines, ml_order_discounts_state (ml-ads-cupones-display T3a)

Revision ID: 20261228_ml_order_discounts
Revises: 20261227_sell_in_modos_producto
Create Date: 2026-11-02

Per-sale discounts from `GET /orders/{order_id}/discounts`: the body as ML sent it per order, the lines derived
from it (one per detail and item: coupon id, campaign, funder amounts) and the single back-off row of the
ingestion. The partial index on `ml_payments_ops` for the pending query is the next revision,
20261228_ml_pay_ops_coupon_idx: a failed CONCURRENTLY build here would leave these tables committed and this
revision unrerunnable. No existing data changes; downgrade drops exactly these three tables.

down_revision must be the single alembic head of origin/main at merge; re-chain it if main advanced.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "20261228_ml_order_discounts"
down_revision: Union[str, None] = "20261227_sell_in_modos_producto"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "ml_order_discounts",
        sa.Column("order_id", sa.BigInteger(), nullable=False),
        sa.Column("status", sa.String(10), nullable=False),
        sa.Column("http_status", sa.Integer(), nullable=True),
        sa.Column("body", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("order_id"),
    )
    op.create_table(
        "ml_order_discount_lines",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("order_id", sa.BigInteger(), nullable=False),
        sa.Column("detail_index", sa.Integer(), nullable=False),
        sa.Column("item_index", sa.Integer(), nullable=False),
        sa.Column("type", sa.String(40), nullable=True),
        sa.Column("coupon_id", sa.BigInteger(), nullable=True),
        sa.Column("campaign_id", sa.BigInteger(), nullable=True),
        sa.Column("meli_campaign", sa.Text(), nullable=True),
        sa.Column("offer_id", sa.Text(), nullable=True),
        sa.Column("funding_mode", sa.String(40), nullable=True),
        sa.Column("item_id", sa.String(40), nullable=True),
        sa.Column("element_id", sa.Integer(), nullable=True),
        sa.Column("quantity", sa.Integer(), nullable=True),
        sa.Column("amount_seller", sa.Numeric(14, 2), nullable=True),
        sa.Column("amount_total", sa.Numeric(14, 2), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("order_id", "detail_index", "item_index", name="uq_ml_order_discount_lines"),
    )
    op.create_index("ix_ml_order_discount_lines_order_id", "ml_order_discount_lines", ["order_id"])
    op.create_index("ix_ml_order_discount_lines_coupon_id", "ml_order_discount_lines", ["coupon_id"])
    op.create_table(
        "ml_order_discounts_state",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("consecutive_429", sa.Integer(), server_default="0", nullable=False),
        sa.Column("backoff_until", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("ml_order_discounts_state")
    op.drop_index("ix_ml_order_discount_lines_coupon_id", table_name="ml_order_discount_lines")
    op.drop_index("ix_ml_order_discount_lines_order_id", table_name="ml_order_discount_lines")
    op.drop_table("ml_order_discount_lines")
    op.drop_table("ml_order_discounts")
