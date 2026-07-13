"""Add index on tb_mercadolibre_orders_header.mlo_cd (CONCURRENTLY)

SDD change tplink-metricas-dual-key-dedup (design D2): the shared TP-Link
metrics aggregation core (`app.scripts._tplink_metricas_core`) filters
BOTH the backfill and the 5-minute incremental job on `mlo_cd` (the
date-window column, half-open `>= :from_ts AND < :to_ts`). This column was
previously unindexed — `ml_date_created` is indexed but is semantically
different (see design decision D2) — so every incremental run and the full
rebuild backfill currently sequential-scan `tb_mercadolibre_orders_header`.

`tb_mercadolibre_orders_header` is written every 5 minutes by the ML sync
jobs, so a plain (non-concurrent) `CREATE INDEX` would take an ACCESS
EXCLUSIVE lock on a hot table for the duration of the build (JD-002
CRITICAL, review ledger sdd/tplink-metricas-dual-key-dedup/review-ledger-slice2).
Mirrors the existing project precedent in
`20260427_add_idx_mlp_official_store_id.py`: `CREATE INDEX CONCURRENTLY`
wrapped in `op.get_context().autocommit_block()` — `CONCURRENTLY` cannot run
inside a transaction.

Additive, read-only benefit; safe for the shared ML table (ML jobs are
unaffected — they do not filter on this index).

Revision ID: 20260710_add_index_mlo_cd
Revises: 20260708_ml_bot_roster
Create Date: 2026-07-10
"""

from typing import Sequence, Union

from alembic import op

revision: str = "20260710_add_index_mlo_cd"
down_revision: Union[str, None] = "20260708_ml_bot_roster"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute(
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS "
            "idx_mercadolibre_orders_header_mlo_cd "
            "ON tb_mercadolibre_orders_header (mlo_cd)"
        )


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS idx_mercadolibre_orders_header_mlo_cd")
