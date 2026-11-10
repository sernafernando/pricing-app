"""tacticals: official-store / channel scope and shared-cap flag

Revision ID: 20261107_tacticals_tiendas
Revises: 20261108_sell_in_bono_monto_total
Create Date: 2026-11-07

Tacticals-tienda slice 1. Owner: tacticals choose which official stores (or all) they apply to,
plus synthetic channels Fuera / Tienda Nube; cap mode is independent (per-target vs shared pool).

- `tacticals.todas_tiendas BOOLEAN NOT NULL DEFAULT true`: existing rows keep today's global behaviour.
- `tacticals.tope_compartido BOOLEAN NOT NULL DEFAULT false`: same cap value; false = one counter per
  target, true = one pool over the selection.
- Backfill, only on the run that adds the columns: every tactical that already exists keeps exactly what it
  credits today, so it gets `tope_compartido = true` (one cap, as before) plus the `fuera` and `tienda_nube`
  rows (it credited those channels before). `todas_tiendas = true` already covers every ML sale, with or
  without an official store. Tacticals created later keep the per-target default.
- `tactical_tiendas`: rows for `oficial` (+ `store_id` → `ml_tiendas_oficiales`) and channels
  `fuera` / `tienda_nube` (no store_id). CASCADE with the header. Partial unique indexes because
  channel rows have NULL `store_id` (a plain UNIQUE would not collapse them in Postgres).

LOCK NOTE: ADD COLUMN with constant default does not rewrite; CREATE TABLE takes SHARE ROW EXCLUSIVE
on `tacticals` / `ml_tiendas_oficiales` until commit. Indexes are small (new empty table). Run with
`lock_timeout = '5s'` and restore the previous value with `set_config` (same pattern as `20261105_tacticals`).
Idempotent. DOWNGRADE refuses (RAISE, nothing changed) while a tactical has a store scope other than the one the
backfill gives (all stores, both channels, one shared cap): the code before this revision would widen it.
"""

from typing import List, Sequence, Union

from alembic import op

revision: str = "20261107_tacticals_tiendas"
down_revision: Union[str, None] = "20261108_sell_in_bono_monto_total"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

LOCK_TIMEOUT = "5s"

TIENDA_TIPO = "tipo IN ('oficial', 'fuera', 'tienda_nube')"
TIENDA_STORE = "(tipo = 'oficial' AND store_id IS NOT NULL) OR (tipo IN ('fuera', 'tienda_nube') AND store_id IS NULL)"

UPGRADE = [
    f"""CREATE TABLE IF NOT EXISTS tactical_tiendas (
  id BIGSERIAL PRIMARY KEY,
  tactical_id BIGINT NOT NULL REFERENCES tacticals (id) ON DELETE CASCADE,
  tipo VARCHAR(16) NOT NULL,
  store_id BIGINT REFERENCES ml_tiendas_oficiales (store_id) ON DELETE RESTRICT,
  CONSTRAINT ck_tactical_tiendas_tipo CHECK ({TIENDA_TIPO}),
  CONSTRAINT ck_tactical_tiendas_store CHECK ({TIENDA_STORE})
)""",
    "CREATE INDEX IF NOT EXISTS ix_tactical_tiendas_tactical_id ON tactical_tiendas (tactical_id)",
    "CREATE INDEX IF NOT EXISTS ix_tactical_tiendas_store_id ON tactical_tiendas (store_id)",
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_tactical_tiendas_oficial "
    "ON tactical_tiendas (tactical_id, store_id) WHERE tipo = 'oficial'",
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_tactical_tiendas_canal "
    "ON tactical_tiendas (tactical_id, tipo) WHERE tipo IN ('fuera', 'tienda_nube')",
    # The columns and the backfill, only on the run that adds them (an existing tactical = one that predates them).
    # In SQL, so it also works in offline `--sql` mode.
    """DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_schema = current_schema() AND table_name = 'tacticals' AND column_name = 'tope_compartido'
  ) THEN
    ALTER TABLE tacticals ADD COLUMN IF NOT EXISTS todas_tiendas BOOLEAN NOT NULL DEFAULT true;
    ALTER TABLE tacticals ADD COLUMN tope_compartido BOOLEAN NOT NULL DEFAULT false;
    UPDATE tacticals SET tope_compartido = true;
    INSERT INTO tactical_tiendas (tactical_id, tipo) SELECT id, 'fuera' FROM tacticals;
    INSERT INTO tactical_tiendas (tactical_id, tipo) SELECT id, 'tienda_nube' FROM tacticals;
  END IF;
END $$""",
]

DOWNGRADE = [
    # Refused (RAISE, nothing changed) while a tactical has a store scope the code before this revision cannot hold:
    # dropping it would silently widen that tactical to every store and channel, and its caps to one pool.
    """DO $$
BEGIN
  IF to_regclass('tactical_tiendas') IS NOT NULL AND EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_schema = current_schema() AND table_name = 'tacticals' AND column_name = 'tope_compartido'
  ) AND EXISTS (
    SELECT 1 FROM tacticals t
    WHERE NOT t.todas_tiendas OR NOT t.tope_compartido
      OR EXISTS (SELECT 1 FROM tactical_tiendas s WHERE s.tactical_id = t.id AND s.tipo = 'oficial')
      OR NOT EXISTS (SELECT 1 FROM tactical_tiendas s WHERE s.tactical_id = t.id AND s.tipo = 'fuera')
      OR NOT EXISTS (SELECT 1 FROM tactical_tiendas s WHERE s.tactical_id = t.id AND s.tipo = 'tienda_nube')
  ) THEN
    RAISE EXCEPTION 'downgrade of 20261107_tacticals_tiendas refused: tacticals with a store scope exist';
  END IF;
END $$""",
    "DROP INDEX IF EXISTS uq_tactical_tiendas_canal",
    "DROP INDEX IF EXISTS uq_tactical_tiendas_oficial",
    "DROP INDEX IF EXISTS ix_tactical_tiendas_store_id",
    "DROP INDEX IF EXISTS ix_tactical_tiendas_tactical_id",
    "DROP TABLE IF EXISTS tactical_tiendas",
    "ALTER TABLE tacticals DROP COLUMN IF EXISTS tope_compartido",
    "ALTER TABLE tacticals DROP COLUMN IF EXISTS todas_tiendas",
]


def _run(statements: List[str]) -> None:
    # Plain SQL (works in offline `--sql` mode); restores the caller's lock_timeout, as `20261105_tacticals`.
    op.execute("SELECT set_config('tacticals_tiendas.lock_timeout_previo', current_setting('lock_timeout'), true)")
    op.execute(f"SELECT set_config('lock_timeout', '{LOCK_TIMEOUT}', true)")
    for statement in statements:
        op.execute(statement)
    op.execute("SELECT set_config('lock_timeout', current_setting('tacticals_tiendas.lock_timeout_previo'), true)")


def upgrade() -> None:
    _run(UPGRADE)


def downgrade() -> None:
    _run(DOWNGRADE)
