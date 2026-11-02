"""sell out: programs group campaigns (sell_out_programas, sell_out_campanas.programa_id)

Revision ID: 20261225_sell_out_programas
Revises: 20261226_ml_ads_display_catalog
Create Date: 2026-11-02

Campaign system, slice A (S1). Owner: "hay que hacer un sistema de campañas, como ves hoy tenemos varias que se
llaman igual y con un número, y eso es por distintas cosas que aplican, habría que hacer un nivel superior para
agrupar todo eso y que cuando haya que renovar una campaña por el quarter no haya que hacer todo de 0".

- `sell_out_programas`: a program ("Programa" on screen) groups campaigns. `nombre` is unique ignoring case (unique
  index on `lower(nombre)`), `estado` is 'activo' or 'archivado', `usuario_id` is its author. Its `updated_at` is kept
  by a BEFORE UPDATE trigger on the existing `sell_out_set_updated_at()` function (20261105), like the campaigns'.
- `sell_out_campanas.programa_id BIGINT NULL`, FK `fk_sell_out_campanas_programa_id` ON DELETE RESTRICT (a program in
  use cannot be deleted), indexed. Every existing campaign stays NULL: campaigns are assigned by hand (with
  suggestions), never backfilled here.

It is metadata only: no allocator or money path reads `programa_id`. No sell-out trigger watches campaign columns
(the statement triggers of 20261109 watch group filters, products and sales only; the only trigger on
`sell_out_campanas` is `sell_out_campanas_updated_at`), so assigning a program queues nothing in `sell_out_dirty`.

DOWNGRADE refuses (RAISE, nothing changed) while a program exists or a campaign has `programa_id`: dropping them
would silently lose the operator's grouping. Otherwise it drops the column and the table.

LOCK NOTE: CREATE TABLE's foreign key to `usuarios` takes SHARE ROW EXCLUSIVE on `usuarios` until the deploy
transaction commits, so writes to `usuarios` wait while the steps below wait for their locks (bounded by
`lock_timeout`; a long write transaction on `usuarios` can make this first step time out, and a retry is safe).
ADD COLUMN (nullable, no default: no rewrite) and the FK take an ACCESS
EXCLUSIVE lock on `sell_out_campanas` (the FK validates against the existing rows, all NULL, so it is quick), which
the `sell_out.drain` worker reads; CREATE INDEX (not CONCURRENTLY: it runs inside the migration transaction) blocks
writes on it while it builds over a few thousand rows. Upgrade and downgrade run with `lock_timeout = '5s'` and the
deploy is retried; the previous value is saved and restored because `env.py` runs every pending revision in ONE
transaction (same pattern as 20261214). Every step is idempotent.
"""

from typing import List, Sequence, Union

from alembic import op

revision: str = "20261225_sell_out_programas"
down_revision: Union[str, None] = "20261226_ml_ads_display_catalog"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

LOCK_TIMEOUT = "5s"

# Also declared by `app.models.sell_out` (the schema parity test compares them).
ESTADO = "estado IN ('activo', 'archivado')"

UPGRADE_PROGRAMAS = f"""
CREATE TABLE IF NOT EXISTS sell_out_programas (
  id BIGSERIAL PRIMARY KEY,
  nombre VARCHAR(200) NOT NULL,
  descripcion TEXT,
  estado VARCHAR(16) NOT NULL DEFAULT 'activo',
  usuario_id INTEGER NOT NULL REFERENCES usuarios (id) ON DELETE RESTRICT,
  created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
  updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
  CONSTRAINT ck_sell_out_programas_estado CHECK ({ESTADO})
)
"""
UPGRADE_NOMBRE = (
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_sell_out_programas_nombre_lower ON sell_out_programas (lower(nombre))"
)
UPGRADE_TRIGGER = """
DROP TRIGGER IF EXISTS sell_out_programas_updated_at ON sell_out_programas;
CREATE TRIGGER sell_out_programas_updated_at
BEFORE UPDATE ON sell_out_programas
FOR EACH ROW EXECUTE FUNCTION sell_out_set_updated_at()
"""
UPGRADE_CAMPANAS = """
ALTER TABLE sell_out_campanas ADD COLUMN IF NOT EXISTS programa_id BIGINT;
ALTER TABLE sell_out_campanas DROP CONSTRAINT IF EXISTS fk_sell_out_campanas_programa_id;
ALTER TABLE sell_out_campanas ADD CONSTRAINT fk_sell_out_campanas_programa_id
  FOREIGN KEY (programa_id) REFERENCES sell_out_programas (id) ON DELETE RESTRICT
"""
UPGRADE_INDICE = "CREATE INDEX IF NOT EXISTS ix_sell_out_campanas_programa_id ON sell_out_campanas (programa_id)"

# Fails loudly rather than silently deleting the grouping. Runs only while the table exists (idempotent).
DOWNGRADE_GUARD = f"""
DO $guard$
BEGIN
  IF to_regclass('sell_out_programas') IS NOT NULL THEN
    IF EXISTS (SELECT 1 FROM sell_out_programas) THEN
      RAISE EXCEPTION 'downgrade of {revision} refused: sell-out programs exist';
    END IF;
  END IF;
  IF EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_schema = current_schema() AND table_name = 'sell_out_campanas' AND column_name = 'programa_id'
  ) THEN
    IF EXISTS (SELECT 1 FROM sell_out_campanas WHERE programa_id IS NOT NULL) THEN
      RAISE EXCEPTION 'downgrade of {revision} refused: sell-out campaigns are assigned to a program';
    END IF;
  END IF;
END
$guard$
"""
DOWNGRADE_CAMPANAS = """
DROP INDEX IF EXISTS ix_sell_out_campanas_programa_id;
ALTER TABLE sell_out_campanas DROP CONSTRAINT IF EXISTS fk_sell_out_campanas_programa_id;
ALTER TABLE sell_out_campanas DROP COLUMN IF EXISTS programa_id
"""
DOWNGRADE_PROGRAMAS = "DROP TABLE IF EXISTS sell_out_programas"  # its index and trigger go with it


def _run(statements: List[str]) -> None:
    # Plain SQL (works in offline `--sql` mode); restores the caller's lock_timeout.
    op.execute("SELECT set_config('sell_out_programas.lock_timeout_previo', current_setting('lock_timeout'), true)")
    op.execute(f"SELECT set_config('lock_timeout', '{LOCK_TIMEOUT}', true)")
    for statement in statements:
        op.execute(statement)
    op.execute("SELECT set_config('lock_timeout', current_setting('sell_out_programas.lock_timeout_previo'), true)")


def upgrade() -> None:
    _run([UPGRADE_PROGRAMAS, UPGRADE_NOMBRE, UPGRADE_TRIGGER, UPGRADE_CAMPANAS, UPGRADE_INDICE])


def downgrade() -> None:
    _run([DOWNGRADE_GUARD, DOWNGRADE_CAMPANAS, DOWNGRADE_PROGRAMAS])
