"""Add promo_sync_watermark table (promo-price-propagation slice 4)

Persists the last-processed ml_item_promotions.updated_at watermark for the
periodic promo-price sync job (app/scripts/sync_promo_prices.py). One row
per job_name.

Revision ID: 20260715_add_promo_sync_watermark
Revises: 20260715_add_producto_precio_origen
Create Date: 2026-07-15

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers
revision: str = "20260715_add_promo_sync_watermark"
down_revision: Union[str, None] = "20260715_add_producto_precio_origen"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "promo_sync_watermark",
        sa.Column("id", sa.Integer(), primary_key=True, index=True),
        sa.Column("job_name", sa.String(length=100), nullable=False),
        sa.Column("last_updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("job_name", name="uq_promo_sync_watermark_job_name"),
    )


def downgrade() -> None:
    op.drop_table("promo_sync_watermark")
