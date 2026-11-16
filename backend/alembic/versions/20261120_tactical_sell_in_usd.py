"""tacticals: a sell in cost bonus may be USD (per unit or capped), converted per sale by the tactical's rate type

Revision ID: 20261120_tactical_sell_in_usd
Revises: 20261119_vpf_offsets_sell_pdf
Create Date: 2026-11-16

Owner, 2026-11-16: "vos elegís un tipo de moneda para el sell in y un tipo de cambio qué importa en qué se cargó la
factura?" (P1 = C: fijo, día de venta and al cobro; P2 = A: the money cap counts USD; "Ponelo donde se carga el cobro").

- `ck_sell_in_bonos_marca_costo_venta`: a cost bonus may be USD when it is a tactical's line (`tactical_id`) and not a
  total (a total stays ARS, converted at save at the fixed rate). Every existing row is ARS: nothing to backfill.
- `sell_in_bono_consumos.monto_usd` NUMERIC(18, 2) and `tc_venta` NUMERIC(18, 6): both NULL (an ARS bonus's row, all
  existing rows) or both set (a USD bonus's row), the rate > 0.
- `tactical_cobranzas.tipo_cambio` NUMERIC(18, 6), NULL or > 0: the rate the brand paid at, what an `al_cobro` USD
  cost bonus converts at once loaded.

No post-deploy command: no existing row changes, and the new columns are NULL on every existing row.

LOCK NOTE: ADD COLUMN (nullable, no default) and ADD CONSTRAINT CHECK take ACCESS EXCLUSIVE briefly; the CHECKs scan
their table (small tables). Run with `lock_timeout = '5s'`, restored with `set_config`. Idempotent. DOWNGRADE refuses
(RAISE, nothing changed) while a USD cost bonus, a USD row or a collection rate exists: dropping them would lose money.
"""

from typing import List, Sequence, Union

from alembic import op

revision: str = "20261120_tactical_sell_in_usd"
down_revision: Union[str, None] = "20261119_vpf_offsets_sell_pdf"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

LOCK_TIMEOUT = "5s"

# Also declared by `app.models.sell_in.SellInBonoMarca` (the migration test compares them).
COSTO_VENTA_USD = (
    "(base = 'factura' AND NOT incluye_iva) "
    "OR (base = 'costo_venta' AND alcance IN ('marca', 'categoria', 'modelos') AND (moneda = 'ARS' "
    "OR (moneda = 'USD' AND tactical_id IS NOT NULL AND tipo <> 'monto_total')))"
)
# What `20261212_sell_in_bono_costo` / `20261105_tacticals` left: a cost bonus is ARS.
COSTO_VENTA_ARS = (
    "(base = 'factura' AND NOT incluye_iva) "
    "OR (base = 'costo_venta' AND moneda = 'ARS' AND alcance IN ('marca', 'categoria', 'modelos'))"
)


def _check_costo_venta(expresion: str) -> str:
    return f"""ALTER TABLE sell_in_bonos_marca
  DROP CONSTRAINT IF EXISTS ck_sell_in_bonos_marca_costo_venta,
  ADD CONSTRAINT ck_sell_in_bonos_marca_costo_venta CHECK ({expresion})"""


UPGRADE = [
    _check_costo_venta(COSTO_VENTA_USD),
    "ALTER TABLE sell_in_bono_consumos ADD COLUMN IF NOT EXISTS monto_usd NUMERIC(18, 2)",
    "ALTER TABLE sell_in_bono_consumos ADD COLUMN IF NOT EXISTS tc_venta NUMERIC(18, 6)",
    """ALTER TABLE sell_in_bono_consumos
  DROP CONSTRAINT IF EXISTS ck_sell_in_bono_consumos_usd,
  ADD CONSTRAINT ck_sell_in_bono_consumos_usd CHECK ((monto_usd IS NULL) = (tc_venta IS NULL)),
  DROP CONSTRAINT IF EXISTS ck_sell_in_bono_consumos_tc_positivo,
  ADD CONSTRAINT ck_sell_in_bono_consumos_tc_positivo CHECK (tc_venta IS NULL OR tc_venta > 0)""",
    "ALTER TABLE tactical_cobranzas ADD COLUMN IF NOT EXISTS tipo_cambio NUMERIC(18, 6)",
    """ALTER TABLE tactical_cobranzas
  DROP CONSTRAINT IF EXISTS ck_tactical_cobranzas_tc_positivo,
  ADD CONSTRAINT ck_tactical_cobranzas_tc_positivo CHECK (tipo_cambio IS NULL OR tipo_cambio > 0)""",
]

DOWNGRADE = [
    f"""DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM sell_in_bonos_marca WHERE base = 'costo_venta' AND moneda = 'USD') THEN
    RAISE EXCEPTION 'downgrade of {revision} refused: USD cost bonuses exist';
  END IF;
  IF EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_schema = current_schema() AND table_name = 'sell_in_bono_consumos' AND column_name = 'monto_usd'
  ) AND EXISTS (SELECT 1 FROM sell_in_bono_consumos WHERE monto_usd IS NOT NULL) THEN
    RAISE EXCEPTION 'downgrade of {revision} refused: USD cost bonus rows exist';
  END IF;
  IF EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_schema = current_schema() AND table_name = 'tactical_cobranzas' AND column_name = 'tipo_cambio'
  ) AND EXISTS (SELECT 1 FROM tactical_cobranzas WHERE tipo_cambio IS NOT NULL) THEN
    RAISE EXCEPTION 'downgrade of {revision} refused: collection rates exist';
  END IF;
END $$""",
    "ALTER TABLE tactical_cobranzas DROP CONSTRAINT IF EXISTS ck_tactical_cobranzas_tc_positivo",
    "ALTER TABLE tactical_cobranzas DROP COLUMN IF EXISTS tipo_cambio",
    """ALTER TABLE sell_in_bono_consumos
  DROP CONSTRAINT IF EXISTS ck_sell_in_bono_consumos_usd,
  DROP CONSTRAINT IF EXISTS ck_sell_in_bono_consumos_tc_positivo""",
    "ALTER TABLE sell_in_bono_consumos DROP COLUMN IF EXISTS tc_venta",
    "ALTER TABLE sell_in_bono_consumos DROP COLUMN IF EXISTS monto_usd",
    _check_costo_venta(COSTO_VENTA_ARS),
]


def _run(statements: List[str]) -> None:
    # Plain SQL (works in offline `--sql` mode); restores the caller's lock_timeout, as `20261110_tactical_cobranza`.
    op.execute("SELECT set_config('tactical_sell_in_usd.lock_timeout_previo', current_setting('lock_timeout'), true)")
    op.execute(f"SELECT set_config('lock_timeout', '{LOCK_TIMEOUT}', true)")
    for statement in statements:
        op.execute(statement)
    op.execute("SELECT set_config('lock_timeout', current_setting('tactical_sell_in_usd.lock_timeout_previo'), true)")


def upgrade() -> None:
    _run(UPGRADE)


def downgrade() -> None:
    _run(DOWNGRADE)
