"""sell_in_bonos_marca: one cap shared by every product a bonus reaches (units and/or money)

Revision ID: 20261211_sell_in_bono_tope
Revises: 20261210_sell_in_bono_items_montos
Create Date: 2026-10-28

sell-in-sell-out T24a. Owner: "muchos rebates aplican a un tope conjunto por ejemplo, tablets y notebooks lenovo que
aplica hasta 3000 USD entre los dos". A bonus may carry `tope_unidades` (invoiced units, INTEGER > 0) and/or
`tope_monto` (in the bonus's own currency, NUMERIC(18, 2) > 0), shared by every product and operation it reaches;
NULL is no cap, as before. The reconcile (`app.services.sell_in.bonos`) allocates them like sell out's cap
(`sell_out.tope`).

The bonus update trigger queues the bonus when one of the fields the reconcile reads changes; the caps join that list
(the rest of its definition is 20261115's, unchanged). The downgrade puts 20261115's trigger back and drops both
columns (and with them the CHECKs).

LOCK NOTE: ADD COLUMN (nullable, no default: no rewrite), the CHECKs (validated against the few existing rows, all
NULL) and DROP/CREATE TRIGGER take an ACCESS EXCLUSIVE lock on `sell_in_bonos_marca`, which the `sell_in.bono` worker
reads. Upgrade and downgrade run with `lock_timeout = '5s'` and the deploy is retried; the previous value is saved and
restored because `env.py` runs every pending revision in ONE transaction (same pattern as 20261210). Every step is
idempotent.
"""

from typing import List, Sequence, Union

from alembic import op

revision: str = "20261211_sell_in_bono_tope"
down_revision: Union[str, None] = "20261210_sell_in_bono_items_montos"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

LOCK_TIMEOUT = "5s"

ADD_COLUMNS = """
ALTER TABLE sell_in_bonos_marca
  ADD COLUMN IF NOT EXISTS tope_unidades INTEGER,
  ADD COLUMN IF NOT EXISTS tope_monto NUMERIC(18, 2),
  DROP CONSTRAINT IF EXISTS ck_sell_in_bonos_marca_tope_unidades,
  DROP CONSTRAINT IF EXISTS ck_sell_in_bonos_marca_tope_monto,
  ADD CONSTRAINT ck_sell_in_bonos_marca_tope_unidades CHECK (tope_unidades IS NULL OR tope_unidades > 0),
  ADD CONSTRAINT ck_sell_in_bonos_marca_tope_monto CHECK (tope_monto IS NULL OR tope_monto > 0)
"""

DROP_COLUMNS = """
ALTER TABLE sell_in_bonos_marca
  DROP CONSTRAINT IF EXISTS ck_sell_in_bonos_marca_tope_monto,
  DROP CONSTRAINT IF EXISTS ck_sell_in_bonos_marca_tope_unidades,
  DROP COLUMN IF EXISTS tope_monto,
  DROP COLUMN IF EXISTS tope_unidades
"""

_CAMPOS = (
    "alcance, {r}.marca, {r}.categoria, {r}.pedido_id, {r}.tipo, {r}.monto_unit, {r}.porcentaje, {r}.moneda,\n"
    "     {r}.fecha_desde, {r}.fecha_hasta, {r}.estado, {r}.usuario_id"
)


def _trigger(con_tope: bool) -> str:
    extra = ", {r}.tope_unidades, {r}.tope_monto" if con_tope else ""
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


DROP_TRIGGER = "DROP TRIGGER IF EXISTS trg_sell_in_bono_bonos_update ON sell_in_bonos_marca"


def _run(statements: List[str]) -> None:
    # Plain SQL (works in offline `--sql` mode); restores the caller's lock_timeout.
    op.execute("SELECT set_config('bono_tope.lock_timeout_previo', current_setting('lock_timeout'), true)")
    op.execute(f"SELECT set_config('lock_timeout', '{LOCK_TIMEOUT}', true)")
    for statement in statements:
        op.execute(statement)
    op.execute("SELECT set_config('lock_timeout', current_setting('bono_tope.lock_timeout_previo'), true)")


def upgrade() -> None:
    _run([ADD_COLUMNS, DROP_TRIGGER, _trigger(con_tope=True)])


def downgrade() -> None:
    _run([DROP_TRIGGER, _trigger(con_tope=False), DROP_COLUMNS])
