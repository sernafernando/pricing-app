"""sell_in_compras: drop the legacy pedido_compra_id column

Revision ID: 20261217_drop_sell_in_compras_pedido_compra_id
Revises: 20261216_sell_out_repartir_permiso
Create Date: 2026-10-29

T28. A purchase's Compras operations live in `sell_in_compra_pedidos` (20261102, which copied this column into it);
since #1809 nothing reads or writes `sell_in_compras.pedido_compra_id`, and the owner authorized the drop once #1809
was deployed. Dropping the column drops its foreign key to `pedidos_compra` with it.

Before the drop, any operation still found only in the column gets its link (the promise #1809's tests made: "the
release that drops it first recreates any link it lacks"); a link that already exists is left alone.

The downgrade puts the column back as it was (BIGINT, nullable, `REFERENCES pedidos_compra(id) ON DELETE SET NULL`)
but EMPTY: its values are lost. Nothing reads it any more; the operations are still in `sell_in_compra_pedidos`.

LOCK NOTE: DROP COLUMN / ADD COLUMN (nullable, no default: no rewrite) take an ACCESS EXCLUSIVE lock on
`sell_in_compras`, which the sell-in worker and the Compras screens read. Upgrade and downgrade run with
`lock_timeout = '5s'` and the deploy is retried; the previous value is saved and restored because `env.py` runs every
pending revision in ONE transaction (same pattern as 20261215). Every step is idempotent.
"""

from typing import List, Sequence, Union

from alembic import op

revision: str = "20261217_drop_sell_in_compras_pedido_compra_id"
down_revision: Union[str, None] = "20261216_sell_out_repartir_permiso"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

LOCK_TIMEOUT = "5s"

# Guarded so a re-run after the column is gone is a no-op (and so is a schema without the link table).
BACKFILL_LINKS = """
DO $$
BEGIN
    IF to_regclass('sell_in_compra_pedidos') IS NOT NULL AND EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = current_schema() AND table_name = 'sell_in_compras' AND column_name = 'pedido_compra_id'
    ) THEN
        INSERT INTO sell_in_compra_pedidos (compra_id, pedido_compra_id)
        SELECT id, pedido_compra_id FROM sell_in_compras
        WHERE pedido_compra_id IS NOT NULL
        ON CONFLICT (compra_id, pedido_compra_id) DO NOTHING;
    END IF;
END $$
"""

DROP_COLUMN = "ALTER TABLE sell_in_compras DROP COLUMN IF EXISTS pedido_compra_id"

ADD_COLUMN = (
    "ALTER TABLE sell_in_compras ADD COLUMN IF NOT EXISTS pedido_compra_id BIGINT "
    "REFERENCES pedidos_compra(id) ON DELETE SET NULL"
)


def _run(statements: List[str]) -> None:
    # Plain SQL (works in offline `--sql` mode); restores the caller's lock_timeout.
    op.execute("SELECT set_config('drop_pedido_compra.lock_timeout_previo', current_setting('lock_timeout'), true)")
    op.execute(f"SELECT set_config('lock_timeout', '{LOCK_TIMEOUT}', true)")
    for statement in statements:
        op.execute(statement)
    op.execute("SELECT set_config('lock_timeout', current_setting('drop_pedido_compra.lock_timeout_previo'), true)")


def upgrade() -> None:
    _run([BACKFILL_LINKS, DROP_COLUMN])


def downgrade() -> None:
    _run([ADD_COLUMN])
