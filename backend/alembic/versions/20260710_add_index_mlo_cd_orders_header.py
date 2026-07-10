"""Add index on tb_mercadolibre_orders_header.mlo_cd

SDD change tplink-metricas-dual-key-dedup (design D2): the shared TP-Link
metrics aggregation core (`app.scripts._tplink_metricas_core`) filters
BOTH the backfill and the 5-minute incremental job on `mlo_cd` (the
date-window column, half-open `>= :from_ts AND < :to_ts`). This column was
previously unindexed — `ml_date_created` is indexed but is semantically
different (see design decision D2) — so every incremental run and the full
rebuild backfill currently sequential-scan `tb_mercadolibre_orders_header`.

Additive, read-only benefit; safe for the shared ML table (ML jobs are
unaffected — they do not filter on this index).

Revision ID: 20260710_add_index_mlo_cd
Revises: 20260708_ml_bot_roster
Create Date: 2026-07-10
"""

from alembic import op

revision = "20260710_add_index_mlo_cd"
down_revision = "20260708_ml_bot_roster"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_mercadolibre_orders_header_mlo_cd "
        "ON tb_mercadolibre_orders_header (mlo_cd)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_mercadolibre_orders_header_mlo_cd")
