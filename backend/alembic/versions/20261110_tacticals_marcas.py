"""tacticals: several brands per tactical header

Revision ID: 20261110_tacticals_marcas
Revises: 20261107_tacticals_tiendas
Create Date: 2026-11-10

Owner, 2026-11-10: "lo mismo las marcas que se usan para el filtro hay que hacer un selector multiple".

- `tactical_marcas (tactical_id, marca)`: one row per brand, CASCADE with the header, unique per tactical, indexed by
  `marca` for the list filter (`EXISTS`). The unique constraint's index leads with `tactical_id`, so no separate one.
- `tacticals.marca` is unchanged: the service keeps the first brand there, so a reader of one brand keeps working.
- Backfill, only on the run that creates the table: every existing tactical gets its single `marca` as its only row.

LOCK NOTE: CREATE TABLE with an FK takes SHARE ROW EXCLUSIVE on `tacticals` until commit; the backfill reads it.
Run with `lock_timeout = '5s'`, restored with `set_config` (same pattern as `20261107_tacticals_tiendas`). Idempotent.
DOWNGRADE refuses (RAISE, nothing changed) while a tactical has more than one brand: the code before this revision
keeps only one, so the others would be lost.
"""

from typing import List, Sequence, Union

from alembic import op

revision: str = "20261110_tacticals_marcas"
down_revision: Union[str, None] = "20261107_tacticals_tiendas"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

LOCK_TIMEOUT = "5s"

UPGRADE = [
    # Table and backfill together, only when the table does not exist yet (in SQL, so offline `--sql` works too).
    """DO $$
BEGIN
  IF to_regclass('tactical_marcas') IS NULL THEN
    CREATE TABLE tactical_marcas (
      id BIGSERIAL PRIMARY KEY,
      tactical_id BIGINT NOT NULL REFERENCES tacticals (id) ON DELETE CASCADE,
      marca VARCHAR(100) NOT NULL,
      CONSTRAINT uq_tactical_marcas UNIQUE (tactical_id, marca)
    );
    INSERT INTO tactical_marcas (tactical_id, marca) SELECT id, marca FROM tacticals ORDER BY id;
  END IF;
END $$""",
    "CREATE INDEX IF NOT EXISTS ix_tactical_marcas_marca ON tactical_marcas (marca)",
]

DOWNGRADE = [
    """DO $$
BEGIN
  IF to_regclass('tactical_marcas') IS NOT NULL AND EXISTS (
    SELECT 1 FROM tactical_marcas GROUP BY tactical_id HAVING count(*) > 1
  ) THEN
    RAISE EXCEPTION 'downgrade of 20261110_tacticals_marcas refused: tacticals with more than one brand exist';
  END IF;
END $$""",
    "DROP INDEX IF EXISTS ix_tactical_marcas_marca",
    "DROP TABLE IF EXISTS tactical_marcas",
]


def _run(statements: List[str]) -> None:
    # Plain SQL (works in offline `--sql` mode); restores the caller's lock_timeout, as `20261107_tacticals_tiendas`.
    op.execute("SELECT set_config('tacticals_marcas.lock_timeout_previo', current_setting('lock_timeout'), true)")
    op.execute(f"SELECT set_config('lock_timeout', '{LOCK_TIMEOUT}', true)")
    for statement in statements:
        op.execute(statement)
    op.execute("SELECT set_config('lock_timeout', current_setting('tacticals_marcas.lock_timeout_previo'), true)")


def upgrade() -> None:
    _run(UPGRADE)


def downgrade() -> None:
    _run(DOWNGRADE)
