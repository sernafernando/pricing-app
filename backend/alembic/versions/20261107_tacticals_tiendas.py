"""tacticals: official-store / channel scope and shared-cap flag

Revision ID: 20261107_tacticals_tiendas
Revises: 20261106_combo_consumos_item
Create Date: 2026-11-07

Tacticals-tienda slice 1. Owner: tacticals choose which official stores (or all) they apply to,
plus synthetic channels Fuera / Tienda Nube; cap mode is independent (per-target vs shared pool).

- `tacticals.todas_tiendas BOOLEAN NOT NULL DEFAULT true`: existing rows keep today's global behaviour.
- `tacticals.tope_compartido BOOLEAN NOT NULL DEFAULT false`: same cap value; false = one counter per
  target, true = one pool over the selection.
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
down_revision: Union[str, None] = "20261106_combo_consumos_item"
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
    _con_lock_timeout(UPGRADE)


def downgrade() -> None:
    _con_lock_timeout(DOWNGRADE)
