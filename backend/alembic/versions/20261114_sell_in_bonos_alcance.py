"""sell_in_bonos_marca: scope (alcance) and kind (tipo); sell_in_bono_items

Revision ID: 20261114_sell_in_bonos_alcance
Revises: 20261113_ml_ads_campaign_contributions
Create Date: 2026-10-22

sell-in-sell-out T3e-1 (M2a). A bonus no longer reaches only a brand, and it may
pay a percentage instead of an amount per invoiced unit. The table keeps its name
(no rename):

- `alcance` VARCHAR(16) NOT NULL DEFAULT 'marca': 'marca' (`marca`), 'categoria'
  (`categoria`, `productos_erp.categoria` exact), 'modelos' (its rows in
  `sell_in_bono_items`) or 'factura' (one Compras operation, `pedido_id`). Each
  scope carries only its own field; `marca` becomes nullable.
- `pedido_id` BIGINT, FK `pedidos_compra` ON DELETE SET NULL (like a generated
  purchase's `bono_pedido_id`): deleting the operation keeps the bonus, whose
  generated purchases the worker voids. So a 'factura' bonus may hold NULL; the
  API requires it on create.
- `tipo` VARCHAR(16) NOT NULL DEFAULT 'por_unidad' (sell-out vocabulary):
  'por_unidad' needs `monto_unit` > 0, 'porcentaje' needs `porcentaje` in
  (0, 100] (of the invoiced net); the other one is NULL. `monto_unit` becomes
  nullable; `ck_sell_in_bonos_marca_monto_positivo` is replaced by
  `ck_sell_in_bonos_marca_monto_segun_tipo`.
- `sell_in_bono_items` (bono_id, item_id): the models of a 'modelos' bonus,
  unique per bonus, CASCADE with it. `item_id` has no FK to `productos_erp`
  (like the invoiced lines: the ERP may hold an item the catalog lacks).

Every existing bonus becomes 'marca' / 'por_unidad': nothing changes for them.
Inert: the worker, the API and the queue's triggers do not read the new
columns yet (the scope-aware gate is M2b).

LOCK NOTE: ADD COLUMN with constant defaults is metadata-only on PG 11+; the
statements take ACCESS EXCLUSIVE on `sell_in_bonos_marca` (a handful of rows)
and, for the new FK, SHARE ROW EXCLUSIVE on `pedidos_compra`. Upgrade and
downgrade run with `lock_timeout = '5s'` and the deploy is retried; the previous
value is saved and restored because `env.py` runs every pending revision in ONE
transaction (same pattern as 20261112_sell_in_compras_porcentaje).

The downgrade refuses (raises) while a bonus that only this schema can hold
exists (another scope, a percentage, or a model list): dropping the columns
would turn it into a different bonus. Otherwise it restores the brand-bonus
table exactly; it is idempotent.
"""

from typing import List, Sequence, Union

from alembic import op

revision: str = "20261114_sell_in_bonos_alcance"
down_revision: Union[str, None] = "20261113_ml_ads_campaign_contributions"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

LOCK_TIMEOUT = "5s"

ALTER_BONOS = """
ALTER TABLE sell_in_bonos_marca
  ADD COLUMN alcance VARCHAR(16) NOT NULL DEFAULT 'marca',
  ADD COLUMN categoria VARCHAR(100),
  ADD COLUMN pedido_id BIGINT,
  ADD COLUMN tipo VARCHAR(16) NOT NULL DEFAULT 'por_unidad',
  ADD COLUMN porcentaje NUMERIC(7, 4),
  ALTER COLUMN marca DROP NOT NULL,
  ALTER COLUMN monto_unit DROP NOT NULL,
  DROP CONSTRAINT IF EXISTS ck_sell_in_bonos_marca_monto_positivo,
  ADD CONSTRAINT fk_sell_in_bonos_marca_pedido_id
    FOREIGN KEY (pedido_id) REFERENCES pedidos_compra (id) ON DELETE SET NULL,
  ADD CONSTRAINT ck_sell_in_bonos_marca_alcance
    CHECK (alcance IN ('marca', 'categoria', 'modelos', 'factura')),
  ADD CONSTRAINT ck_sell_in_bonos_marca_campos_segun_alcance CHECK (
    (alcance = 'marca' AND marca IS NOT NULL AND categoria IS NULL AND pedido_id IS NULL)
    OR (alcance = 'categoria' AND categoria IS NOT NULL AND marca IS NULL AND pedido_id IS NULL)
    OR (alcance = 'modelos' AND marca IS NULL AND categoria IS NULL AND pedido_id IS NULL)
    OR (alcance = 'factura' AND marca IS NULL AND categoria IS NULL)
  ),
  ADD CONSTRAINT ck_sell_in_bonos_marca_tipo CHECK (tipo IN ('por_unidad', 'porcentaje')),
  ADD CONSTRAINT ck_sell_in_bonos_marca_monto_segun_tipo CHECK (
    (tipo = 'por_unidad' AND monto_unit IS NOT NULL AND monto_unit > 0 AND porcentaje IS NULL)
    OR (tipo = 'porcentaje' AND porcentaje IS NOT NULL AND porcentaje > 0 AND porcentaje <= 100
        AND monto_unit IS NULL)
  )
"""

INDEX_PEDIDO = "CREATE INDEX IF NOT EXISTS ix_sell_in_bonos_marca_pedido_id ON sell_in_bonos_marca (pedido_id)"

CREATE_ITEMS = """
CREATE TABLE sell_in_bono_items (
  id BIGSERIAL PRIMARY KEY,
  bono_id BIGINT NOT NULL REFERENCES sell_in_bonos_marca (id) ON DELETE CASCADE,
  item_id INTEGER NOT NULL,
  CONSTRAINT uq_sell_in_bono_items_bono_item UNIQUE (bono_id, item_id)
)
"""

INDEX_ITEMS = "CREATE INDEX ix_sell_in_bono_items_item_id ON sell_in_bono_items (item_id)"

# Fails the downgrade (and its transaction) while a bonus the old table cannot hold exists.
GUARD_DOWNGRADE = """
DO $guard$
BEGIN
  -- Nested: PL/pgSQL prepares a query only when it runs, so a missing table or column is never read.
  IF to_regclass('sell_in_bono_items') IS NOT NULL THEN
    IF EXISTS (SELECT 1 FROM sell_in_bono_items) THEN
      RAISE EXCEPTION 'sell_in_bonos_marca: a bonus lists models in sell_in_bono_items; void and remove it first';
    END IF;
  END IF;
  IF EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_schema = current_schema() AND table_name = 'sell_in_bonos_marca' AND column_name = 'alcance'
  ) THEN
    IF EXISTS (SELECT 1 FROM sell_in_bonos_marca WHERE alcance <> 'marca' OR tipo <> 'por_unidad') THEN
      RAISE EXCEPTION 'sell_in_bonos_marca: a bonus is not by brand and per unit; it cannot be downgraded';
    END IF;
  END IF;
END
$guard$
"""

DROP_ITEMS = "DROP TABLE IF EXISTS sell_in_bono_items"

RESTORE_BONOS = """
ALTER TABLE sell_in_bonos_marca
  DROP CONSTRAINT IF EXISTS ck_sell_in_bonos_marca_monto_segun_tipo,
  DROP CONSTRAINT IF EXISTS ck_sell_in_bonos_marca_tipo,
  DROP CONSTRAINT IF EXISTS ck_sell_in_bonos_marca_campos_segun_alcance,
  DROP CONSTRAINT IF EXISTS ck_sell_in_bonos_marca_alcance,
  DROP CONSTRAINT IF EXISTS fk_sell_in_bonos_marca_pedido_id,
  DROP COLUMN IF EXISTS porcentaje,
  DROP COLUMN IF EXISTS tipo,
  DROP COLUMN IF EXISTS pedido_id,
  DROP COLUMN IF EXISTS categoria,
  DROP COLUMN IF EXISTS alcance,
  ALTER COLUMN marca SET NOT NULL,
  ALTER COLUMN monto_unit SET NOT NULL,
  DROP CONSTRAINT IF EXISTS ck_sell_in_bonos_marca_monto_positivo,
  ADD CONSTRAINT ck_sell_in_bonos_marca_monto_positivo CHECK (monto_unit > 0)
"""


def _run(statements: List[str]) -> None:
    # Plain SQL (works in offline `--sql` mode); restores the caller's lock_timeout.
    op.execute("SELECT set_config('bonos_alcance.lock_timeout_previo', current_setting('lock_timeout'), true)")
    op.execute(f"SELECT set_config('lock_timeout', '{LOCK_TIMEOUT}', true)")
    for statement in statements:
        op.execute(statement)
    op.execute("SELECT set_config('lock_timeout', current_setting('bonos_alcance.lock_timeout_previo'), true)")


def upgrade() -> None:
    _run([ALTER_BONOS, INDEX_PEDIDO, CREATE_ITEMS, INDEX_ITEMS])


def downgrade() -> None:
    _run([GUARD_DOWNGRADE, DROP_ITEMS, "DROP INDEX IF EXISTS ix_sell_in_bonos_marca_pedido_id", RESTORE_BONOS])
