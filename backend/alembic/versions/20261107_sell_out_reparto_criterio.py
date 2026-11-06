"""sell out: how a monto_total campaign is split (sell_out_campanas.reparto_criterio)

Revision ID: 20261107_sell_out_reparto_criterio
Revises: 20261106_combo_consumos_item
Create Date: 2026-11-06

Tactical monto total (S2). The orchestrator's decision: "sell_out_campanas.reparto_criterio VARCHAR(16) NULL + CHECK,
NULL=manual, only for monto_total: iguales|unidades|costo, no backfill, downgrade drops it".

- `sell_out_campanas.reparto_criterio VARCHAR(16) NULL`; every existing campaign stays NULL (split by hand, today's
  behavior).
- CHECK `ck_sell_out_campanas_reparto_criterio`: NULL, or a `monto_total` campaign with `iguales`, `unidades` or
  `costo`.

`iguales` and `costo` store fixed shares in `sell_out_campana_items` like a manual split; `unidades` stores none and the
allocator spreads the total over every unit sold in the dates (`app.services.sell_out.reparto`). Setting it from the app
queues the campaign in `sell_out_dirty` like any split change; the migration itself queues nothing (every row stays
NULL).

DOWNGRADE drops the column: the campaigns split `iguales` / `costo` keep their stored shares and read as manual; a
`unidades` one is left with no shares, so its total reads "Sin asignar" until it is split again.

LOCK NOTE: ADD COLUMN (nullable, no default: no rewrite) and the CHECK (validated over a few thousand rows, all NULL)
take an ACCESS EXCLUSIVE lock on `sell_out_campanas`, which the `sell_out.drain` worker reads. Upgrade and downgrade
run with `lock_timeout = '5s'` and the deploy is retried; the previous value is saved and restored because `env.py`
runs every pending revision in ONE transaction (same pattern as 20261230_sell_out_renovada_de). Every step is
idempotent.
"""

from typing import List, Sequence, Union

from alembic import op

revision: str = "20261107_sell_out_reparto_criterio"
down_revision: Union[str, Sequence[str], None] = "20261106_combo_consumos_item"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

LOCK_TIMEOUT = "5s"

UPGRADE = [
    "ALTER TABLE sell_out_campanas ADD COLUMN IF NOT EXISTS reparto_criterio VARCHAR(16)",
    "ALTER TABLE sell_out_campanas DROP CONSTRAINT IF EXISTS ck_sell_out_campanas_reparto_criterio",
    "ALTER TABLE sell_out_campanas ADD CONSTRAINT ck_sell_out_campanas_reparto_criterio CHECK ("
    "reparto_criterio IS NULL OR (tipo = 'monto_total' AND reparto_criterio IN ('iguales', 'unidades', 'costo')))",
]

DOWNGRADE = [
    "ALTER TABLE sell_out_campanas DROP CONSTRAINT IF EXISTS ck_sell_out_campanas_reparto_criterio",
    "ALTER TABLE sell_out_campanas DROP COLUMN IF EXISTS reparto_criterio",
]


def _run(statements: List[str]) -> None:
    # Plain SQL (works in offline `--sql` mode); restores the caller's lock_timeout.
    op.execute(
        "SELECT set_config('sell_out_reparto_criterio.lock_timeout_previo', current_setting('lock_timeout'), true)"
    )
    op.execute(f"SELECT set_config('lock_timeout', '{LOCK_TIMEOUT}', true)")
    for statement in statements:
        op.execute(statement)
    op.execute(
        "SELECT set_config('lock_timeout', current_setting('sell_out_reparto_criterio.lock_timeout_previo'), true)"
    )


def upgrade() -> None:
    _run(UPGRADE)


def downgrade() -> None:
    _run(DOWNGRADE)
