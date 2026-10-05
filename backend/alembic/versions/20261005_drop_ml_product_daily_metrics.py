"""drop ml_product_daily_metrics (phase two of removing the daily rollup)

Revision ID: 20261005_drop_ml_product_daily_metrics
Revises: 20261002_autovacuum_tablas_calientes
Create Date: 2026-10-05

ODD `metricas-ml-tablero`, "Sin tabla resumen": the Métricas ML board reads
the orders directly and nothing writes or reads this table any more. The
release that removed its writer (PR #1380) is deployed and its workers
restarted, so dropping it can no longer break a metrics store of an old
worker -- the reason the drop did not ship with that release.

`lock_timeout` makes the deploy fail fast instead of queueing behind
something holding the table; it is reset so later revisions in the same
transaction do not inherit it. Downgrade recreates the empty table with its
original shape (its rows were a derived cache: nothing to restore).
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20261005_drop_ml_product_daily_metrics"
down_revision: Union[str, None] = "20261002_autovacuum_tablas_calientes"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLE = "ml_product_daily_metrics"


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '10s'")
    # Its indexes and unique constraint go with it.
    op.execute(f"DROP TABLE IF EXISTS {TABLE}")
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
