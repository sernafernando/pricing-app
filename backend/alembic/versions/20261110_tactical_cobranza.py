"""tacticals: one collection record (cobranza) per tactical

Revision ID: 20261110_tactical_cobranza
Revises: 20261110_tacticals_marcas
Create Date: 2026-11-10

Owner, 2026-11-10: "Hay que hacerle un chequeo de cobranza a los tacticals ... fecha de cuando se cobro, si es Nota de
crédito (ahí número) o si es fondo en distribuidor (ahí un panel para aclarar el distri) u otro ... además un panel de
observaciones libre, que obligatorio sea la fecha no más."

- `tactical_cobranzas`: at most one row per tactical (unique `tactical_id`, CASCADE with the header). A tactical with
  a row is "Cobrado", without one "Pendiente". Only `fecha_cobro` is NOT NULL; `medio` is NULL or one of
  nota_credito | fondo_distribuidor | otro. `usuario_id` (RESTRICT) is the last user to save it; indexed (FK).
- No backfill: every existing tactical starts "Pendiente".

LOCK NOTE: CREATE TABLE with an FK takes SHARE ROW EXCLUSIVE on `tacticals` until commit. Run with
`lock_timeout = '5s'`, restored with `set_config` (same pattern as `20261110_tacticals_marcas`). Idempotent.
DOWNGRADE refuses (RAISE, nothing changed) while a collection record exists: dropping the table would lose them.
"""

from typing import List, Sequence, Union

from alembic import op

revision: str = "20261110_tactical_cobranza"
down_revision: Union[str, None] = "20261110_tacticals_marcas"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

LOCK_TIMEOUT = "5s"

UPGRADE = [
    """CREATE TABLE IF NOT EXISTS tactical_cobranzas (
  id BIGSERIAL PRIMARY KEY,
  tactical_id BIGINT NOT NULL REFERENCES tacticals (id) ON DELETE CASCADE,
  fecha_cobro DATE NOT NULL,
  medio VARCHAR(32),
  nc_numero VARCHAR(100),
  distribuidor VARCHAR(200),
  otro_detalle VARCHAR(500),
  observaciones TEXT,
  usuario_id INTEGER NOT NULL REFERENCES usuarios (id) ON DELETE RESTRICT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT uq_tactical_cobranzas_tactical UNIQUE (tactical_id),
  CONSTRAINT ck_tactical_cobranzas_medio CHECK (
    medio IS NULL OR medio IN ('nota_credito', 'fondo_distribuidor', 'otro')
  )
)""",
    "CREATE INDEX IF NOT EXISTS ix_tactical_cobranzas_usuario_id ON tactical_cobranzas (usuario_id)",
]

DOWNGRADE = [
    """DO $$
BEGIN
  IF to_regclass('tactical_cobranzas') IS NOT NULL AND EXISTS (SELECT 1 FROM tactical_cobranzas) THEN
    RAISE EXCEPTION 'downgrade of 20261110_tactical_cobranza refused: collection records exist';
  END IF;
END $$""",
    "DROP TABLE IF EXISTS tactical_cobranzas",
]


def _run(statements: List[str]) -> None:
    # Plain SQL (works in offline `--sql` mode); restores the caller's lock_timeout, as `20261110_tacticals_marcas`.
    op.execute("SELECT set_config('tactical_cobranza.lock_timeout_previo', current_setting('lock_timeout'), true)")
    op.execute(f"SELECT set_config('lock_timeout', '{LOCK_TIMEOUT}', true)")
    for statement in statements:
        op.execute(statement)
    op.execute("SELECT set_config('lock_timeout', current_setting('tactical_cobranza.lock_timeout_previo'), true)")


def upgrade() -> None:
    _run(UPGRADE)


def downgrade() -> None:
    _run(DOWNGRADE)
