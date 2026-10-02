"""ml_product_daily_metrics: daily per-product/per-publication sales rollup

Revision ID: 20261001_ml_product_daily_metrics
Revises: 20261001_ix_mlp_publicationid
Create Date: 2026-10-01

ODD `metricas-ml-tablero` T2: the read model behind the Métricas ML board --
one row per (product, MLA, accreditation day) with SUMS only (units, gross,
Total Gauss, cost, orders, unresolved orders, last sale). Written in the
same transaction as `ml_order_metrics` by `store_order_metrics`; historical
rows come from `app/scripts/backfill_ml_daily_metrics.py`.

A new, empty table: creating it locks nothing anyone else uses.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20261001_ml_product_daily_metrics"
down_revision: Union[str, None] = "20261001_ix_mlp_publicationid"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLE = "ml_product_daily_metrics"


def upgrade() -> None:
    op.create_table(
        TABLE,
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("product_item_id", sa.Integer(), nullable=False),
        sa.Column("mla", sa.String(20), nullable=False),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("units", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("gross_ars", sa.Numeric(16, 2), nullable=False, server_default="0"),
        sa.Column("total_gauss", sa.Numeric(16, 2), nullable=False, server_default="0"),
        sa.Column("costo", sa.Numeric(16, 2), nullable=False, server_default="0"),
        sa.Column("orders", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("unresolved_orders", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_sale_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("product_item_id", "mla", "day", name="uq_ml_product_daily_metrics_key"),
    )
    op.create_index("ix_ml_product_daily_metrics_day", TABLE, ["day"])
    op.create_index("ix_ml_product_daily_metrics_mla_day", TABLE, ["mla", "day"])


def downgrade() -> None:
    op.drop_index("ix_ml_product_daily_metrics_mla_day", table_name=TABLE)
    op.drop_index("ix_ml_product_daily_metrics_day", table_name=TABLE)
    op.drop_table(TABLE)
