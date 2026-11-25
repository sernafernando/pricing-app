"""sell in: a voided USD cost bonus may lose its tactical (a tactical with a USD sell in line can be edited again)

Revision ID: 20261125_sell_in_bono_usd_anulado
Revises: 20261122_tacticals_aprobacion
Create Date: 2026-11-25

Prod 2026-11-25: PUT /api/tacticals/54 answered 500 four times (CheckViolation `ck_sell_in_bonos_marca_costo_venta`).
A full edit (`tacticals.reemplazar` -> `_reemplazar_hijos`) voids the old children and detaches them
(`tactical_id`/`tactical_linea` NULL); a USD cost bonus without a tactical broke the CHECK, so no tactical with a USD
sell in line could be edited.

- `ck_sell_in_bonos_marca_costo_venta`: a USD cost bonus needs a tactical while it is alive; a voided one ('anulada')
  may be detached. A live USD cost bonus without a tactical is still refused, and a USD total still is.

No post-deploy command: no existing row changes (every existing USD cost bonus has its tactical, the CHECK held).

LOCK NOTE: ADD CONSTRAINT CHECK takes ACCESS EXCLUSIVE briefly and scans `sell_in_bonos_marca` (small table). Run with
`lock_timeout = '5s'`, restored with `set_config`. Idempotent. DOWNGRADE refuses (RAISE, nothing changed) while a
detached voided USD cost bonus exists: the older CHECK cannot hold it.
"""

from typing import List, Sequence, Union

from alembic import op

revision: str = "20261125_sell_in_bono_usd_anulado"
down_revision: Union[str, None] = "20261122_tacticals_aprobacion"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

LOCK_TIMEOUT = "5s"

# Also declared by `app.models.sell_in.SellInBonoMarca` (the migration test compares them).
COSTO_VENTA_USD_ANULADO = (
    "(base = 'factura' AND NOT incluye_iva) "
    "OR (base = 'costo_venta' AND alcance IN ('marca', 'categoria', 'modelos') AND (moneda = 'ARS' "
    "OR (moneda = 'USD' AND (tactical_id IS NOT NULL OR estado = 'anulada') AND tipo <> 'monto_total')))"
)
# What `20261120_tactical_sell_in_usd` left: a USD cost bonus always has its tactical.
COSTO_VENTA_USD = (
    "(base = 'factura' AND NOT incluye_iva) "
    "OR (base = 'costo_venta' AND alcance IN ('marca', 'categoria', 'modelos') AND (moneda = 'ARS' "
    "OR (moneda = 'USD' AND tactical_id IS NOT NULL AND tipo <> 'monto_total')))"
)


def _check_costo_venta(expresion: str) -> str:
    return f"""ALTER TABLE sell_in_bonos_marca
  DROP CONSTRAINT IF EXISTS ck_sell_in_bonos_marca_costo_venta,
  ADD CONSTRAINT ck_sell_in_bonos_marca_costo_venta CHECK ({expresion})"""


UPGRADE = [_check_costo_venta(COSTO_VENTA_USD_ANULADO)]

DOWNGRADE = [
    f"""DO $$
BEGIN
  IF EXISTS (
    SELECT 1 FROM sell_in_bonos_marca WHERE base = 'costo_venta' AND moneda = 'USD' AND tactical_id IS NULL
  ) THEN
    RAISE EXCEPTION 'downgrade of {revision} refused: detached voided USD cost bonuses exist';
  END IF;
END $$""",
    _check_costo_venta(COSTO_VENTA_USD),
]


def _run(statements: List[str]) -> None:
    # Plain SQL (works in offline `--sql` mode); restores the caller's lock_timeout, as `20261120_tactical_sell_in_usd`.
    op.execute(
        "SELECT set_config('sell_in_bono_usd_anulado.lock_timeout_previo', current_setting('lock_timeout'), true)"
    )
    op.execute(f"SELECT set_config('lock_timeout', '{LOCK_TIMEOUT}', true)")
    for statement in statements:
        op.execute(statement)
    op.execute(
        "SELECT set_config('lock_timeout', current_setting('sell_in_bono_usd_anulado.lock_timeout_previo'), true)"
    )


def upgrade() -> None:
    _run(UPGRADE)


def downgrade() -> None:
    _run(DOWNGRADE)
