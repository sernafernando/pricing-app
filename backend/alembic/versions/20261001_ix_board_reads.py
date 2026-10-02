"""indexes for the Métricas ML board's per-request reads (CONCURRENTLY)

Revision ID: 20261001_ix_board_reads
Revises: 20261001_ml_metricas_permisos
Create Date: 2026-10-01

ODD `metricas-ml-tablero` (performance round). Two reads every board request
makes that were sequential scans:

- `ml_group_metrics.group_date >= now() - 24h` -- the orders behind the
  rolling 24h window (~77k groups in production, growing);
- `MAX(ml_product_daily_metrics.updated_at)` -- the "actualizado hace" line.

Both become index range/edge reads. `CONCURRENTLY` (outside the transaction)
so the metrics worker keeps writing while they build -- same precedent as
`20260427_add_idx_mlp_official_store_id.py`.
"""

from typing import Sequence, Union

from alembic import op

revision: str = "20261001_ix_board_reads"
down_revision: Union[str, None] = "20261001_ml_metricas_permisos"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

INDEXES = {
    "ix_ml_group_metrics_group_date": ("ml_group_metrics", "group_date"),
    "ix_ml_product_daily_metrics_updated_at": ("ml_product_daily_metrics", "updated_at"),
}


def upgrade() -> None:
    with op.get_context().autocommit_block():
        for name, (table, column) in INDEXES.items():
            op.execute(f"CREATE INDEX CONCURRENTLY IF NOT EXISTS {name} ON {table} ({column})")


def downgrade() -> None:
    with op.get_context().autocommit_block():
        for name in INDEXES:
            op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {name}")
