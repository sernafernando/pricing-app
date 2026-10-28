"""sell_in_bono_items: a model's own monto_unit or porcentaje inside a 'modelos' bonus

Revision ID: 20261210_sell_in_bono_items_montos
Revises: 20261207_sell_out_campana_items
Create Date: 2026-10-28

sell-in-sell-out T23a. Owner: "sell in y sell out deberían permitir agrupados, así que si no lo está permitiendo es
un error nuestro". A legacy grouped offset gives each product ITS OWN amount (or %). A model of a 'modelos' bonus may
now carry its own `monto_unit` (a 'por_unidad' bonus) or `porcentaje` (a 'porcentaje' bonus), with the same types
and bounds as the bonus's own fields (NUMERIC(18, 2) > 0; NUMERIC(7, 4) in (0, 100]) and at most one of them. A model
with neither gets the bonus's value, as before. The reconcile (`app.services.sell_in.bonos`) reads them; the API
checks the value matches the bonus kind.

LOCK NOTE: ADD COLUMN (nullable, no default: no rewrite) and the CHECKs (validated against the few existing rows,
all NULL) take an ACCESS EXCLUSIVE lock on `sell_in_bono_items`, which the `sell_in.bono` worker reads. Upgrade and
downgrade run with `lock_timeout = '5s'` and the deploy is retried; the previous value is saved and restored because
`env.py` runs every pending revision in ONE transaction (same pattern as 20261111_sell_out_offset_origen).

The downgrade drops both columns (and with them the CHECKs); both steps are idempotent.
"""

from typing import List, Sequence, Union

from alembic import op

revision: str = "20261210_sell_in_bono_items_montos"
down_revision: Union[str, None] = "20261207_sell_out_campana_items"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

LOCK_TIMEOUT = "5s"

ADD_COLUMNS = """
ALTER TABLE sell_in_bono_items
  ADD COLUMN IF NOT EXISTS monto_unit NUMERIC(18, 2),
  ADD COLUMN IF NOT EXISTS porcentaje NUMERIC(7, 4),
  DROP CONSTRAINT IF EXISTS ck_sell_in_bono_items_monto_positivo,
  DROP CONSTRAINT IF EXISTS ck_sell_in_bono_items_porcentaje_rango,
  DROP CONSTRAINT IF EXISTS ck_sell_in_bono_items_un_valor,
  ADD CONSTRAINT ck_sell_in_bono_items_monto_positivo CHECK (monto_unit IS NULL OR monto_unit > 0),
  ADD CONSTRAINT ck_sell_in_bono_items_porcentaje_rango
    CHECK (porcentaje IS NULL OR (porcentaje > 0 AND porcentaje <= 100)),
  ADD CONSTRAINT ck_sell_in_bono_items_un_valor CHECK (monto_unit IS NULL OR porcentaje IS NULL)
"""

DROP_COLUMNS = """
ALTER TABLE sell_in_bono_items
  DROP CONSTRAINT IF EXISTS ck_sell_in_bono_items_un_valor,
  DROP CONSTRAINT IF EXISTS ck_sell_in_bono_items_porcentaje_rango,
  DROP CONSTRAINT IF EXISTS ck_sell_in_bono_items_monto_positivo,
  DROP COLUMN IF EXISTS porcentaje,
  DROP COLUMN IF EXISTS monto_unit
"""


def _run(statements: List[str]) -> None:
    # Plain SQL (works in offline `--sql` mode); restores the caller's lock_timeout.
    op.execute("SELECT set_config('bono_items_montos.lock_timeout_previo', current_setting('lock_timeout'), true)")
    op.execute(f"SELECT set_config('lock_timeout', '{LOCK_TIMEOUT}', true)")
    for statement in statements:
        op.execute(statement)
    op.execute("SELECT set_config('lock_timeout', current_setting('bono_items_montos.lock_timeout_previo'), true)")


def upgrade() -> None:
    _run([ADD_COLUMNS])


def downgrade() -> None:
    _run([DROP_COLUMNS])
