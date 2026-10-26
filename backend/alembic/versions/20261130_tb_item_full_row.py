"""tb_item keeps the whole ERP row (raw) + dimensions and website images

Revision ID: 20261130_tb_item_full_row
Revises: 20261129_ml_item_overrides
Create Date: 2026-10-26

The GBP `scriptItem` script now returns every tbItem column. The syncs used to keep 12 of them; `raw` stores the
whole row so nothing the ERP sends is dropped, and the dimensions and website image URLs get typed columns so they
can be queried. All columns are nullable: existing rows fill in on the next sync.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "20261130_tb_item_full_row"
down_revision: Union[str, None] = "20261129_ml_item_overrides"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

DIMENSION_COLUMNS = ("item_weight", "item_volume", "item_wide", "item_large", "item_higth")
IMAGE_COLUMNS = tuple(f"item_WebSite_url4Image{i}" for i in range(1, 11))


def upgrade() -> None:
    op.add_column("tb_item", sa.Column("raw", JSONB(), nullable=True))
    for name in DIMENSION_COLUMNS:
        op.add_column("tb_item", sa.Column(name, sa.Numeric(18, 9), nullable=True))
    for name in IMAGE_COLUMNS:
        op.add_column("tb_item", sa.Column(name, sa.Text(), nullable=True))


def downgrade() -> None:
    for name in reversed(IMAGE_COLUMNS):
        op.drop_column("tb_item", name)
    for name in reversed(DIMENSION_COLUMNS):
        op.drop_column("tb_item", name)
    op.drop_column("tb_item", "raw")
