"""Add producto_precio_origen table (promo-price-propagation slice 2)

Tracks which mechanism (manual edit vs promo) last wrote each price column
of a product, one row per (item_id, column_key). Used for last-write-wins
arbitration once promos start writing prices (slice 3/4).

Revision ID: 20260715_add_producto_precio_origen
Revises: 20260713_merge_heads
Create Date: 2026-07-15

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers
revision: str = "20260715_add_producto_precio_origen"
down_revision: Union[str, None] = "20260713_merge_heads"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "producto_precio_origen",
        sa.Column("id", sa.Integer(), primary_key=True, index=True),
        sa.Column(
            "item_id",
            sa.Integer(),
            sa.ForeignKey("productos_erp.item_id"),
            nullable=False,
        ),
        sa.Column("column_key", sa.String(length=50), nullable=False),
        sa.Column("origen", sa.String(length=20), nullable=False),
        sa.Column("promo_id", sa.String(length=50), nullable=True),
        sa.Column("mla", sa.String(length=50), nullable=True),
        sa.Column("fecha", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("item_id", "column_key", name="uq_producto_precio_origen_item_column"),
    )
    op.create_index(
        "idx_producto_precio_origen_item_id",
        "producto_precio_origen",
        ["item_id"],
    )


def downgrade() -> None:
    op.drop_index("idx_producto_precio_origen_item_id", table_name="producto_precio_origen")
    op.drop_table("producto_precio_origen")
