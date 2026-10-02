"""drop ml_product_daily_metrics: the Métricas ML board reads the orders

Revision ID: 20261002_drop_ml_product_daily_metrics
Revises: 20261002_autovacuum_tablas_calientes
Create Date: 2026-10-02

ODD `metricas-ml-tablero`, "Sin tabla resumen" (user decision, final): the
board is computed from the tables we already have (orders, items, frozen
costs, stored metrics, group accreditation day), so the daily rollup, its
worker hook and its backfill are gone. Its indexes
(`ix_ml_product_daily_metrics_day`, `_mla_day`, `_updated_at`) and unique
key go with the table. `IF EXISTS`: a database that never had it is fine.

`lock_timeout`: the drop needs an ACCESS EXCLUSIVE lock on the table; if a
worker still running the previous release is writing it, the deploy fails
fast instead of queueing every reader behind it.

Downgrade recreates the empty table and its indexes (the previous code
would need its backfill to fill it again).
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20261002_drop_ml_product_daily_metrics"
down_revision: Union[str, None] = "20261002_autovacuum_tablas_calientes"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLE = "ml_product_daily_metrics"


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '10s'")
    op.execute(f"DROP TABLE IF EXISTS {TABLE}")
    # SET LOCAL lasts until the transaction ends, and Alembic may run the next
    # revisions in this same transaction: give them back the default.
    op.execute("SET LOCAL lock_timeout = DEFAULT")


def downgrade() -> None:
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
    op.create_index("ix_ml_product_daily_metrics_updated_at", TABLE, ["updated_at"])
