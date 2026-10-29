"""sell_in_compras: drop the legacy pedido_compra_id column

Revision ID: 20261217_drop_sell_in_compras_pedido_compra_id
Revises: 20261216_sell_out_repartir_permiso
Create Date: 2026-10-29

T28. A purchase's Compras operations live in `sell_in_compra_pedidos` (20261102, which copied this column into it);
since #1809 nothing reads or writes `sell_in_compras.pedido_compra_id`, and the owner authorized the drop once #1809
was deployed. Dropping the column drops its foreign key to `pedidos_compra` with it.

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
    _run([DROP_COLUMN])


def downgrade() -> None:
    _run([ADD_COLUMN])
