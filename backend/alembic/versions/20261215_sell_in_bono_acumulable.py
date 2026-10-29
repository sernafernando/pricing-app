"""sell_in_bonos_marca: an `acumulable` flag, like sell out's, on every bonus (invoice and % of cost)

Revision ID: 20261215_sell_in_bono_acumulable
Revises: 20261214_sell_out_monto_total
Create Date: 2026-10-29

sell-in-sell-out T27a (S36), schema only: the allocators read it from T27b. Owner, on how overlapping bonuses tell
which must count twice: "agregaselo".

- `acumulable BOOLEAN NOT NULL DEFAULT true`, the same meaning as `sell_out_campanas.acumulable`: bonuses on the same
  product and dates stack unless one of them is not acumulable. Every existing bonus gets true, so nothing it
  generated changes.

The bonus update trigger also queues a bonus when `acumulable` changes (the rest of its definition is 20261212's,
unchanged). The downgrade puts 20261212's trigger back and drops the column. It refuses (RAISE, nothing changed)
while a bonus is not acumulable: dropping the column would silently make it stack again.

LOCK NOTE: ADD COLUMN with a constant default (no rewrite since PG 11) and DROP/CREATE TRIGGER take an ACCESS
EXCLUSIVE lock on `sell_in_bonos_marca`, which the `sell_in.bono` worker reads. Upgrade and downgrade run with
`lock_timeout = '5s'` and the deploy is retried; the previous value is saved and restored because `env.py` runs every
pending revision in ONE transaction (same pattern as 20261212). Every step is idempotent.
"""

from typing import List, Sequence, Union

from alembic import op

revision: str = "20261215_sell_in_bono_acumulable"
down_revision: Union[str, None] = "20261214_sell_out_monto_total"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

LOCK_TIMEOUT = "5s"

ADD_COLUMN = "ALTER TABLE sell_in_bonos_marca ADD COLUMN IF NOT EXISTS acumulable BOOLEAN NOT NULL DEFAULT true"

DROP_COLUMN = "ALTER TABLE sell_in_bonos_marca DROP COLUMN IF EXISTS acumulable"

# 20261212's field list, frozen here.
_CAMPOS = (
    "alcance, {r}.marca, {r}.categoria, {r}.pedido_id, {r}.tipo, {r}.monto_unit, {r}.porcentaje, {r}.moneda,\n"
    "     {r}.fecha_desde, {r}.fecha_hasta, {r}.estado, {r}.usuario_id, {r}.tope_unidades, {r}.tope_monto,\n"
    "     {r}.base, {r}.incluye_iva"
)


def _trigger(con_acumulable: bool) -> str:
    extra = ", {r}.acumulable" if con_acumulable else ""
    campos = _CAMPOS + extra
    return f"""
CREATE TRIGGER trg_sell_in_bono_bonos_update
AFTER UPDATE ON sell_in_bonos_marca
FOR EACH ROW WHEN (
    (OLD.{campos.format(r="OLD")})
    IS DISTINCT FROM
    (NEW.{campos.format(r="NEW")})
)
EXECUTE FUNCTION sell_in_bono_enqueue_bono()
"""


DOWNGRADE_GUARD = f"""
DO $guard$
BEGIN
  IF EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_schema = current_schema() AND table_name = 'sell_in_bonos_marca' AND column_name = 'acumulable'
  ) THEN
    IF EXISTS (SELECT 1 FROM sell_in_bonos_marca WHERE NOT acumulable) THEN
      RAISE EXCEPTION 'downgrade of {revision} refused: sell-in bonuses that are not acumulable exist';
    END IF;
  END IF;
END
$guard$
"""

DROP_TRIGGER = "DROP TRIGGER IF EXISTS trg_sell_in_bono_bonos_update ON sell_in_bonos_marca"


def _run(statements: List[str]) -> None:
    # Plain SQL (works in offline `--sql` mode); restores the caller's lock_timeout.
    op.execute("SELECT set_config('bono_acumulable.lock_timeout_previo', current_setting('lock_timeout'), true)")
    op.execute(f"SELECT set_config('lock_timeout', '{LOCK_TIMEOUT}', true)")
    for statement in statements:
        op.execute(statement)
    op.execute("SELECT set_config('lock_timeout', current_setting('bono_acumulable.lock_timeout_previo'), true)")


def upgrade() -> None:
    _run([ADD_COLUMN, DROP_TRIGGER, _trigger(con_acumulable=True)])


def downgrade() -> None:
    _run([DOWNGRADE_GUARD, DROP_TRIGGER, _trigger(con_acumulable=False), DROP_COLUMN])
