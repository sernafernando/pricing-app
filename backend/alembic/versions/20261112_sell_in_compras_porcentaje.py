"""sell_in_compras: tipo ('monto'|'porcentaje') and porcentaje

Revision ID: 20261112_sell_in_compras_porcentaje
Revises: 20261111_sell_out_offset_origen
Create Date: 2026-10-22

sell-in-sell-out T3g-2 (M1b). A sell-in purchase is either a fixed amount or a
percentage of the invoiced net of its operations (sell-out vocabulary):

- `tipo` VARCHAR(16) NOT NULL DEFAULT 'monto': every existing purchase is a
  fixed amount, so nothing changes for them;
- `porcentaje` NUMERIC(7,4), set only when `tipo = 'porcentaje'`, in (0, 100].

`monto_total` stays NOT NULL and server-computed for both kinds; the
percentage only says how it was computed. Inert: nothing reads or writes these
columns yet (T3g-3 adds the backend).

LOCK NOTE: ADD COLUMN with a constant default is metadata-only on PG 11+ (no
rewrite), but it and the CHECKs (which scan the table once) take an ACCESS
EXCLUSIVE lock on `sell_in_compras`. Upgrade and downgrade run with
`lock_timeout = '5s'` and the deploy is retried; the previous value is saved
and restored because `env.py` runs every pending revision in ONE transaction
(same pattern as 20261111_sell_out_offset_origen).

The downgrade drops both columns (and with them the constraints); it is
idempotent.
"""

from typing import List, Sequence, Union

from alembic import op

revision: str = "20261112_sell_in_compras_porcentaje"
down_revision: Union[str, None] = "20261111_sell_out_offset_origen"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

LOCK_TIMEOUT = "5s"

ADD_COLUMNS = """
ALTER TABLE sell_in_compras
  ADD COLUMN tipo VARCHAR(16) NOT NULL DEFAULT 'monto',
  ADD COLUMN porcentaje NUMERIC(7, 4),
  ADD CONSTRAINT ck_sell_in_compras_tipo CHECK (tipo IN ('monto', 'porcentaje')),
  ADD CONSTRAINT ck_sell_in_compras_porcentaje_segun_tipo CHECK (
    (tipo = 'monto' AND porcentaje IS NULL)
    OR (tipo = 'porcentaje' AND porcentaje IS NOT NULL AND porcentaje > 0 AND porcentaje <= 100)
  )
"""

DROP_COLUMNS = """
ALTER TABLE sell_in_compras
  DROP CONSTRAINT IF EXISTS ck_sell_in_compras_porcentaje_segun_tipo,
  DROP CONSTRAINT IF EXISTS ck_sell_in_compras_tipo,
  DROP COLUMN IF EXISTS porcentaje,
  DROP COLUMN IF EXISTS tipo
"""


def _run(statements: List[str]) -> None:
    # Plain SQL (works in offline `--sql` mode); restores the caller's lock_timeout.
    op.execute("SELECT set_config('compras_porcentaje.lock_timeout_previo', current_setting('lock_timeout'), true)")
    op.execute(f"SELECT set_config('lock_timeout', '{LOCK_TIMEOUT}', true)")
    for statement in statements:
        op.execute(statement)
    op.execute("SELECT set_config('lock_timeout', current_setting('compras_porcentaje.lock_timeout_previo'), true)")


def upgrade() -> None:
    _run([ADD_COLUMNS])


def downgrade() -> None:
    _run([DROP_COLUMNS])
