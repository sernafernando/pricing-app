"""sell_out_campanas: offset_origen_id (the legacy offset a campaign was migrated from)

Revision ID: 20261111_sell_out_offset_origen
Revises: 20261110_pedido_lineas_facturadas_importe
Create Date: 2026-10-22

sell-in-sell-out T15. `app.scripts.migrar_offsets_a_sell_out` turns each active
per-unit legacy offset into one sell-out campaign and records the offset here:

- nullable: campaigns loaded by hand have no legacy offset;
- UNIQUE: one campaign per offset, so a re-run of the script finds the offset
  already migrated instead of creating a second campaign;
- FK to `offsets_ganancia` ON DELETE SET NULL: deleting a legacy offset keeps
  the campaign, which no longer depends on it.

LOCK NOTE: ADD COLUMN (nullable, no default: no rewrite) and the constraints
take an ACCESS EXCLUSIVE lock on `sell_out_campanas`, which the `sell_out.drain`
worker locks row by row while it rebuilds a campaign. Upgrade and downgrade run
with `lock_timeout = '5s'` and the deploy is retried; the previous value is
saved and restored because `env.py` runs every pending revision in ONE
transaction (same pattern as 20261110_pedido_lineas_facturadas_importe).

The downgrade drops the column (and with it the constraints); it is idempotent.
"""

from typing import List, Sequence, Union

from alembic import op

revision: str = "20261111_sell_out_offset_origen"
down_revision: Union[str, None] = "20261110_pedido_lineas_facturadas_importe"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

LOCK_TIMEOUT = "5s"

ADD_COLUMN = """
ALTER TABLE sell_out_campanas
  ADD COLUMN offset_origen_id INTEGER,
  ADD CONSTRAINT uq_sell_out_campanas_offset_origen_id UNIQUE (offset_origen_id),
  ADD CONSTRAINT fk_sell_out_campanas_offset_origen_id
    FOREIGN KEY (offset_origen_id) REFERENCES offsets_ganancia (id) ON DELETE SET NULL
"""

DROP_COLUMN = """
ALTER TABLE sell_out_campanas
  DROP CONSTRAINT IF EXISTS fk_sell_out_campanas_offset_origen_id,
  DROP CONSTRAINT IF EXISTS uq_sell_out_campanas_offset_origen_id,
  DROP COLUMN IF EXISTS offset_origen_id
"""


def _run(statements: List[str]) -> None:
    # Plain SQL (works in offline `--sql` mode); restores the caller's lock_timeout.
    op.execute("SELECT set_config('offset_origen.lock_timeout_previo', current_setting('lock_timeout'), true)")
    op.execute(f"SELECT set_config('lock_timeout', '{LOCK_TIMEOUT}', true)")
    for statement in statements:
        op.execute(statement)
    op.execute("SELECT set_config('lock_timeout', current_setting('offset_origen.lock_timeout_previo'), true)")


def upgrade() -> None:
    _run([ADD_COLUMN])


def downgrade() -> None:
    _run([DROP_COLUMN])
