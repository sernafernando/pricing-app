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
`lock_timeout = '5s'` and restore the previous value (same pattern as `20261105_tacticals`).
Idempotent.
"""

from typing import Sequence, Union

from alembic import op

revision: str = "20261107_tacticals_tiendas"
down_revision: Union[str, None] = "20261108_sell_in_bono_monto_total"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

LOCK_TIMEOUT = "5s"

TIENDA_TIPO = "tipo IN ('oficial', 'fuera', 'tienda_nube')"
TIENDA_STORE = "(tipo = 'oficial' AND store_id IS NOT NULL) OR (tipo IN ('fuera', 'tienda_nube') AND store_id IS NULL)"

UPGRADE = f"""
ALTER TABLE tacticals ADD COLUMN IF NOT EXISTS todas_tiendas BOOLEAN NOT NULL DEFAULT true;
ALTER TABLE tacticals ADD COLUMN IF NOT EXISTS tope_compartido BOOLEAN NOT NULL DEFAULT false;

CREATE TABLE IF NOT EXISTS tactical_tiendas (
  id BIGSERIAL PRIMARY KEY,
  tactical_id BIGINT NOT NULL REFERENCES tacticals (id) ON DELETE CASCADE,
  tipo VARCHAR(16) NOT NULL,
  store_id BIGINT REFERENCES ml_tiendas_oficiales (store_id) ON DELETE RESTRICT,
  CONSTRAINT ck_tactical_tiendas_tipo CHECK ({TIENDA_TIPO}),
  CONSTRAINT ck_tactical_tiendas_store CHECK ({TIENDA_STORE})
);
CREATE INDEX IF NOT EXISTS ix_tactical_tiendas_tactical_id ON tactical_tiendas (tactical_id);
CREATE INDEX IF NOT EXISTS ix_tactical_tiendas_store_id ON tactical_tiendas (store_id);
CREATE UNIQUE INDEX IF NOT EXISTS uq_tactical_tiendas_oficial
  ON tactical_tiendas (tactical_id, store_id) WHERE tipo = 'oficial';
CREATE UNIQUE INDEX IF NOT EXISTS uq_tactical_tiendas_canal
  ON tactical_tiendas (tactical_id, tipo) WHERE tipo IN ('fuera', 'tienda_nube')
"""

# Run once, right after the columns are added (an existing tactical = one that predates them).
BACKFILL = """
UPDATE tacticals SET tope_compartido = true;
INSERT INTO tactical_tiendas (tactical_id, tipo) SELECT id, 'fuera' FROM tacticals;
INSERT INTO tactical_tiendas (tactical_id, tipo) SELECT id, 'tienda_nube' FROM tacticals
"""

DOWNGRADE = """
DROP INDEX IF EXISTS uq_tactical_tiendas_canal;
DROP INDEX IF EXISTS uq_tactical_tiendas_oficial;
DROP INDEX IF EXISTS ix_tactical_tiendas_store_id;
DROP INDEX IF EXISTS ix_tactical_tiendas_tactical_id;
DROP TABLE IF EXISTS tactical_tiendas;
ALTER TABLE tacticals DROP COLUMN IF EXISTS tope_compartido;
ALTER TABLE tacticals DROP COLUMN IF EXISTS todas_tiendas
"""


def _con_lock_timeout(sql: str) -> None:
    previo = op.get_bind().exec_driver_sql("SHOW lock_timeout").scalar()
    op.execute(f"SET lock_timeout = '{LOCK_TIMEOUT}'")
    try:
        for statement in sql.strip().split(";"):
            statement = statement.strip()
            if statement:
                op.execute(statement)
    finally:
        op.execute(f"SET lock_timeout = '{previo}'")


def upgrade() -> None:
    columnas_previas = (
        op.get_bind()
        .exec_driver_sql(
            "SELECT 1 FROM information_schema.columns WHERE table_schema = current_schema() "
            "AND table_name = 'tacticals' AND column_name = 'tope_compartido'"
        )
        .first()
    )
    _con_lock_timeout(UPGRADE if columnas_previas else UPGRADE + ";" + BACKFILL)


def downgrade() -> None:
    _con_lock_timeout(DOWNGRADE)
