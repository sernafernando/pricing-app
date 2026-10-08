"""merge the Ads, publications list index and replenishment heads

Revision ID: 20261012_merge_ads_pubml
Revises: 20261008_ml_ads_product_ads, 20261011_ml_items_last_trigger_index,
         20261011_ml_user_product_replenishment
Create Date: 2026-10-12

#1430, #1432 and #1428 each chained their migration after
20261010_ml_user_product_stock_locations and were merged in the same window, leaving three
heads. They touch unrelated tables (Ads tables, an ml_items index, the replenishment table),
so the merge has no operations of its own.
"""

from typing import Sequence, Union


# revision identifiers, used by Alembic.
revision: str = "20261012_merge_ads_pubml"
down_revision: Union[str, None] = (
    "20261008_ml_ads_product_ads",
    "20261011_ml_items_last_trigger_index",
    "20261011_ml_user_product_replenishment",
)
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
