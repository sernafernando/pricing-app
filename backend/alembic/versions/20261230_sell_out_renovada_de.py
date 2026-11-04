"""sell out: a campaign names the campaign it renews (sell_out_campanas.renovada_de_id)

Revision ID: 20261230_sell_out_renovada_de
Revises: 20261229_ml_ads_contribution_channel
Create Date: 2026-11-04

Renovar programa (S4). The orchestrator's decision: "add `renovada_de_id` (nullable FK to sell_out_campanas, ON DELETE
SET NULL), set by BOTH the per-campaign Renovar and Renovar programa. A campaign counts as already renewed when another
non-voided campaign has renovada_de_id = its id. No name/date heuristics (a renamed copy would be renewed twice). [...]
No backfill of existing campaigns."

- `sell_out_campanas.renovada_de_id BIGINT NULL`, FK `fk_sell_out_campanas_renovada_de_id` to `sell_out_campanas (id)`
  ON DELETE SET NULL, indexed (`ix_sell_out_campanas_renovada_de_id`: "is this campaign already renewed" looks it up).
  Every existing campaign stays NULL.

It is metadata only: no allocator or money path reads it, and no sell-out trigger watches campaign columns (the only
trigger on `sell_out_campanas` is `sell_out_campanas_updated_at`), so setting it queues nothing in `sell_out_dirty`.

DOWNGRADE refuses (RAISE, nothing changed) while a campaign has `renovada_de_id`: dropping it would silently lose
which campaigns were renewed, and Renovar programa would renew them again. Otherwise it drops the column.

LOCK NOTE: ADD COLUMN (nullable, no default: no rewrite) and the self-referencing FK take an ACCESS EXCLUSIVE lock on
`sell_out_campanas` (the FK validates the existing rows, all NULL, so it is quick), which the `sell_out.drain` worker
reads; CREATE INDEX (not CONCURRENTLY: it runs inside the migration transaction) blocks writes on it while it builds
over a few thousand rows. Upgrade and downgrade run with `lock_timeout = '5s'` and the deploy is retried; the previous
value is saved and restored because `env.py` runs every pending revision in ONE transaction (same pattern as
20261225). Every step is idempotent.
"""

from typing import List, Sequence, Union

from alembic import op

revision: str = "20261230_sell_out_renovada_de"
down_revision: Union[str, Sequence[str], None] = "20261229_ml_ads_contribution_channel"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

LOCK_TIMEOUT = "5s"

UPGRADE = [
    "ALTER TABLE sell_out_campanas ADD COLUMN IF NOT EXISTS renovada_de_id BIGINT",
    "ALTER TABLE sell_out_campanas DROP CONSTRAINT IF EXISTS fk_sell_out_campanas_renovada_de_id",
    "ALTER TABLE sell_out_campanas ADD CONSTRAINT fk_sell_out_campanas_renovada_de_id "
    "FOREIGN KEY (renovada_de_id) REFERENCES sell_out_campanas (id) ON DELETE SET NULL",
    "CREATE INDEX IF NOT EXISTS ix_sell_out_campanas_renovada_de_id ON sell_out_campanas (renovada_de_id)",
]

DOWNGRADE_GUARD = f"""
DO $$
BEGIN
  IF EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_schema = current_schema() AND table_name = 'sell_out_campanas' AND column_name = 'renovada_de_id'
  ) THEN
    IF EXISTS (SELECT 1 FROM sell_out_campanas WHERE renovada_de_id IS NOT NULL) THEN
      RAISE EXCEPTION 'downgrade of {revision} refused: sell-out campaigns name the campaign they renew (renewal links)';
    END IF;
  END IF;
END $$
"""

DOWNGRADE = [
    DOWNGRADE_GUARD,
    "DROP INDEX IF EXISTS ix_sell_out_campanas_renovada_de_id",
    "ALTER TABLE sell_out_campanas DROP CONSTRAINT IF EXISTS fk_sell_out_campanas_renovada_de_id",
    "ALTER TABLE sell_out_campanas DROP COLUMN IF EXISTS renovada_de_id",
]


def _run(statements: List[str]) -> None:
    # Plain SQL (works in offline `--sql` mode); restores the caller's lock_timeout.
    op.execute("SELECT set_config('sell_out_renovada_de.lock_timeout_previo', current_setting('lock_timeout'), true)")
    op.execute(f"SELECT set_config('lock_timeout', '{LOCK_TIMEOUT}', true)")
    for statement in statements:
        op.execute(statement)
    op.execute("SELECT set_config('lock_timeout', current_setting('sell_out_renovada_de.lock_timeout_previo'), true)")


def upgrade() -> None:
    _run(UPGRADE)


def downgrade() -> None:
    _run(DOWNGRADE)
