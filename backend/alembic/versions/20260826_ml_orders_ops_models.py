"""ml-ventas-fuente-de-verdad slice 1: ML operations source-of-truth tables

Revision ID: 20260826_ml_orders_ops_models
Revises: 20260826_merge_heads
Create Date: 2026-08-26

Additive-only migration. Creates six new tables sourced directly from the
ML API (via the ml-webhook proxy), independent of GBP. No existing table is
altered. Nothing writes to these tables yet -- gated behind
`ML_ORDERS_OPS_ENABLED` (default OFF), wired in a later slice.

Tables:
- ml_orders_ops         one row per ML order, PK order_id (ML natural key)
- ml_order_items_ops    one row per (order_id, item_id, variation_id); ZERO
                        cost columns -- the cost seam for a later change
- ml_shipments_ops      one row per ML shipment, PK shipment_id
- ml_operation_links    link from a claim/question/message to its ML order
- ml_ops_sync_cursor    sweep/backfill checkpoint
- ml_ops_divergence     ML-vs-GBP divergence report; also reused (cross-slice
                        contract, obs #1828) by the out-of-window update
                        counter via kind='out_of_window_update'
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "20260826_ml_orders_ops_models"
down_revision: Union[str, None] = "20260826_merge_heads"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "ml_orders_ops",
        sa.Column("order_id", sa.BigInteger(), nullable=False),
        sa.Column("pack_id", sa.BigInteger(), nullable=True),
        sa.Column("status", sa.String(length=30), nullable=True),
        sa.Column("status_detail", sa.String(length=60), nullable=True),
        sa.Column("date_created", sa.DateTime(timezone=True), nullable=True),
        sa.Column("date_closed", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ml_last_updated", sa.DateTime(timezone=True), nullable=False),
        sa.Column("buyer_id", sa.BigInteger(), nullable=True),
        sa.Column("buyer_nickname", sa.String(length=120), nullable=True),
        sa.Column("seller_id", sa.BigInteger(), nullable=False),
        sa.Column("total_amount", sa.Numeric(14, 2), nullable=True),
        sa.Column("paid_amount", sa.Numeric(14, 2), nullable=True),
        sa.Column("currency_id", sa.String(length=5), nullable=True),
        sa.Column("shipping_id", sa.BigInteger(), nullable=True),
        sa.Column("tags", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("raw_order", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("ingest_error", sa.Text(), nullable=True),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("order_id"),
    )
    op.create_index("ix_ml_orders_ops_pack_id", "ml_orders_ops", ["pack_id"])
    op.create_index("ix_ml_orders_ops_status", "ml_orders_ops", ["status"])
    op.create_index("ix_ml_orders_ops_ml_last_updated", "ml_orders_ops", ["ml_last_updated"])
    op.create_index("ix_ml_orders_ops_buyer_id", "ml_orders_ops", ["buyer_id"])
    op.create_index("ix_ml_orders_ops_seller_id", "ml_orders_ops", ["seller_id"])
    op.create_index("ix_ml_orders_ops_shipping_id", "ml_orders_ops", ["shipping_id"])
    op.create_index("ix_ml_orders_ops_seller_id_ml_last_updated", "ml_orders_ops", ["seller_id", "ml_last_updated"])
    op.create_index("ix_ml_orders_ops_status_date_created", "ml_orders_ops", ["status", "date_created"])

    op.create_table(
        "ml_order_items_ops",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("order_id", sa.BigInteger(), nullable=False),
        sa.Column("item_id", sa.String(length=20), nullable=False),
        sa.Column("variation_id", sa.BigInteger(), nullable=True),
        sa.Column("seller_sku", sa.String(length=60), nullable=True),
        sa.Column("title", sa.String(length=255), nullable=True),
        sa.Column("quantity", sa.Integer(), nullable=True),
        sa.Column("unit_price", sa.Numeric(14, 2), nullable=True),
        sa.Column("full_unit_price", sa.Numeric(14, 2), nullable=True),
        sa.Column("sale_fee", sa.Numeric(14, 2), nullable=True),
        sa.Column("listing_type_id", sa.String(length=30), nullable=True),
        sa.Column("raw_item", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "order_id",
            "item_id",
            "variation_id",
            name="uq_ml_order_item_ops_order_item_variation",
            postgresql_nulls_not_distinct=True,
        ),
    )
    op.create_index("ix_ml_order_items_ops_order_id", "ml_order_items_ops", ["order_id"])
    op.create_index("ix_ml_order_items_ops_item_id", "ml_order_items_ops", ["item_id"])
    op.create_index("ix_ml_order_items_ops_seller_sku", "ml_order_items_ops", ["seller_sku"])

    op.create_table(
        "ml_shipments_ops",
        sa.Column("shipment_id", sa.BigInteger(), nullable=False),
        sa.Column("order_id", sa.BigInteger(), nullable=True),
        sa.Column("status", sa.String(length=30), nullable=True),
        sa.Column("substatus", sa.String(length=40), nullable=True),
        sa.Column("logistic_type", sa.String(length=30), nullable=True),
        sa.Column("tracking_number", sa.String(length=60), nullable=True),
        sa.Column("tracking_method", sa.String(length=40), nullable=True),
        sa.Column("date_created", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_updated", sa.DateTime(timezone=True), nullable=True),
        sa.Column("receiver_address", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("raw_shipment", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("shipment_id"),
    )
    op.create_index("ix_ml_shipments_ops_order_id", "ml_shipments_ops", ["order_id"])
    op.create_index("ix_ml_shipments_ops_status", "ml_shipments_ops", ["status"])
    op.create_index("ix_ml_shipments_ops_tracking_number", "ml_shipments_ops", ["tracking_number"])

    op.create_table(
        "ml_operation_links",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("order_id", sa.BigInteger(), nullable=False),
        sa.Column("entity_type", sa.String(length=20), nullable=False),
        sa.Column("entity_id", sa.BigInteger(), nullable=False),
        sa.Column("link_source", sa.String(length=20), nullable=False),
        sa.Column("link_confidence", sa.String(length=10), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("entity_type", "entity_id", "order_id", name="uq_ml_operation_links_entity_order"),
    )
    op.create_index("ix_ml_operation_links_order_id", "ml_operation_links", ["order_id"])
    op.create_index("ix_ml_operation_links_order_id_entity_type", "ml_operation_links", ["order_id", "entity_type"])

    op.create_table(
        "ml_ops_sync_cursor",
        sa.Column("name", sa.String(length=50), nullable=False),
        sa.Column("window_from", sa.DateTime(timezone=True), nullable=True),
        sa.Column("window_to", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_success_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("state", sa.String(length=20), nullable=False, server_default="idle"),
        sa.Column("detail", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("name"),
    )

    op.create_table(
        "ml_ops_divergence",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("order_id", sa.BigInteger(), nullable=False),
        sa.Column("detected_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("kind", sa.String(length=30), nullable=False),
        sa.Column("field", sa.String(length=40), nullable=True),
        sa.Column("ml_value", sa.Text(), nullable=True),
        sa.Column("gbp_value", sa.Text(), nullable=True),
        sa.Column("state", sa.String(length=20), nullable=False, server_default="open"),
        sa.Column("assigned_to_id", sa.Integer(), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["assigned_to_id"], ["usuarios.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "order_id",
            "kind",
            "field",
            name="uq_ml_ops_divergence_order_kind_field",
            postgresql_nulls_not_distinct=True,
        ),
    )
    op.create_index("ix_ml_ops_divergence_order_id", "ml_ops_divergence", ["order_id"])


def downgrade() -> None:
    op.drop_index("ix_ml_ops_divergence_order_id", table_name="ml_ops_divergence")
    op.drop_table("ml_ops_divergence")

    op.drop_table("ml_ops_sync_cursor")

    op.drop_index("ix_ml_operation_links_order_id_entity_type", table_name="ml_operation_links")
    op.drop_index("ix_ml_operation_links_order_id", table_name="ml_operation_links")
    op.drop_table("ml_operation_links")

    op.drop_index("ix_ml_shipments_ops_tracking_number", table_name="ml_shipments_ops")
    op.drop_index("ix_ml_shipments_ops_status", table_name="ml_shipments_ops")
    op.drop_index("ix_ml_shipments_ops_order_id", table_name="ml_shipments_ops")
    op.drop_table("ml_shipments_ops")

    op.drop_index("ix_ml_order_items_ops_seller_sku", table_name="ml_order_items_ops")
    op.drop_index("ix_ml_order_items_ops_item_id", table_name="ml_order_items_ops")
    op.drop_index("ix_ml_order_items_ops_order_id", table_name="ml_order_items_ops")
    op.drop_table("ml_order_items_ops")

    op.drop_index("ix_ml_orders_ops_status_date_created", table_name="ml_orders_ops")
    op.drop_index("ix_ml_orders_ops_seller_id_ml_last_updated", table_name="ml_orders_ops")
    op.drop_index("ix_ml_orders_ops_shipping_id", table_name="ml_orders_ops")
    op.drop_index("ix_ml_orders_ops_seller_id", table_name="ml_orders_ops")
    op.drop_index("ix_ml_orders_ops_buyer_id", table_name="ml_orders_ops")
    op.drop_index("ix_ml_orders_ops_ml_last_updated", table_name="ml_orders_ops")
    op.drop_index("ix_ml_orders_ops_status", table_name="ml_orders_ops")
    op.drop_index("ix_ml_orders_ops_pack_id", table_name="ml_orders_ops")
    op.drop_table("ml_orders_ops")
