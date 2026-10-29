"""sell out: a fixed-total campaign (monto_total), its per-product shares and negative consumptions

Revision ID: 20261214_sell_out_monto_total
Revises: 20261213_sell_in_bono_costo_triggers
Create Date: 2026-10-29

sell-in-sell-out T26a (S34, S35), schema only: no allocator, no API yet. Owner: "Está bien que sume al total, lo de
la repartición lo pondría como un selecto de % o monto fijo por producto" and "lenovo era una deducción de las
ganancias por lo que debería ser un sell out negativo".

- `sell_out_campanas.tipo` accepts 'monto_total' besides 'por_unidad' / 'porcentaje'. New `monto_total
  NUMERIC(18, 2)` (campaign currency, `tc_modo` / `monto_incluye_iva` as today), set and <> 0 exactly on a
  monto_total campaign: positive = a credit, negative = a deduction from profit (S35). A monto_total campaign carries
  no `monto_unit` / `porcentaje` and no cap (`tope_unidades` / `tope_monto`): the total is its cap. The por_unidad and
  porcentaje branches of `ck_sell_out_campanas_monto_segun_tipo` keep exactly their rules (plus `monto_total IS
  NULL`, true for every existing row).
- `sell_out_campana_items` (T22b) holds a monto_total campaign's manual shares: new `reparto_porcentaje
  NUMERIC(7, 4)` (a % of the total, > 0 and <= 100) and `reparto_monto NUMERIC(18, 2)` (a fixed amount, <> 0);
  `monto_unit` becomes nullable and every row carries exactly one of the three (`ck_sell_out_campana_items_un_monto`).
  `ck_sell_out_campana_items_monto_positivo` (`monto_unit > 0`) is unchanged: a NULL passes it. Rules that need the
  campaign row are the service's (T26c), since a CHECK cannot see another table: a fixed share has the total's sign,
  shares only on a monto_total campaign and `monto_unit` only on a por_unidad one, |sum of shares| <= |total|.
- `sell_out_consumos.monto` may be negative: `ck_sell_out_consumos_monto_no_negativo` (monto >= 0) is DROPPED, since
  a CHECK cannot see the campaign's type. The allocators keep writing only non-negative amounts for por_unidad and
  porcentaje campaigns (pinned by T26b's tests); only a negative monto_total campaign writes negatives.

No sell-out trigger watches campaign or item columns: a campaign or share change queues `sell_out_dirty` through the
campaigns service (`app.services.sell_out.queue.enqueue`), and the statement triggers of 20261109 watch group
filters, products and sales only. The `sell_out_campanas_updated_at` BEFORE UPDATE trigger fires on any column, so
it already covers `monto_total`. Nothing to change there.

DOWNGRADE refuses (RAISE, nothing changed) while a monto_total campaign, a share row or a negative consumption
exists: dropping them would silently delete money rows. Otherwise it restores the previous CHECKs, drops the new
columns and puts `monto_unit NOT NULL` back.

LOCK NOTE: ADD COLUMN (nullable, no default: no rewrite), the CHECKs (validated against the existing rows) and the
DROP NOT NULL take an ACCESS EXCLUSIVE lock on `sell_out_campanas`, `sell_out_campana_items` and `sell_out_consumos`,
which the `sell_out.drain` worker reads and writes. Upgrade and downgrade run with `lock_timeout = '5s'` and the
deploy is retried; the previous value is saved and restored because `env.py` runs every pending revision in ONE
transaction (same pattern as 20261211-20261213). Every step is idempotent.
"""

from typing import List, Sequence, Union

from alembic import op

revision: str = "20261214_sell_out_monto_total"
down_revision: Union[str, None] = "20261213_sell_in_bono_costo_triggers"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

LOCK_TIMEOUT = "5s"

# The CHECK expressions, also declared by `app.models.sell_out` (the schema parity test compares them). Portable
# SQL (no `num_nonnulls`): the ORM metadata is also created on SQLite by the unit tests.
TIPO = "tipo IN ('por_unidad', 'porcentaje', 'monto_total')"
MONTO_SEGUN_TIPO = (
    "(tipo = 'por_unidad' AND monto_unit IS NOT NULL AND monto_unit > 0 AND porcentaje IS NULL "
    "AND monto_total IS NULL) OR "
    "(tipo = 'porcentaje' AND porcentaje IS NOT NULL AND porcentaje > 0 AND porcentaje <= 100 "
    "AND monto_unit IS NULL AND monto_total IS NULL) OR "
    "(tipo = 'monto_total' AND monto_total IS NOT NULL AND monto_total <> 0 AND monto_unit IS NULL "
    "AND porcentaje IS NULL AND tope_unidades IS NULL AND tope_monto IS NULL)"
)
ITEMS_UN_MONTO = (
    "(monto_unit IS NOT NULL AND reparto_porcentaje IS NULL AND reparto_monto IS NULL) OR "
    "(monto_unit IS NULL AND reparto_porcentaje IS NOT NULL AND reparto_monto IS NULL) OR "
    "(monto_unit IS NULL AND reparto_porcentaje IS NULL AND reparto_monto IS NOT NULL)"
)
ITEMS_REPARTO_PORCENTAJE = "reparto_porcentaje > 0 AND reparto_porcentaje <= 100"
ITEMS_REPARTO_MONTO = "reparto_monto <> 0"

# 20261105 / 20261108's definitions, frozen here for the downgrade.
_TIPO_PREVIO = "tipo IN ('por_unidad', 'porcentaje')"
_MONTO_SEGUN_TIPO_PREVIO = (
    "(tipo = 'por_unidad' AND monto_unit IS NOT NULL AND monto_unit > 0 AND porcentaje IS NULL) OR "
    "(tipo = 'porcentaje' AND porcentaje IS NOT NULL AND porcentaje > 0 AND porcentaje <= 100 "
    "AND monto_unit IS NULL)"
)
_CONSUMOS_NO_NEGATIVO_PREVIO = "monto >= 0"

UPGRADE_CAMPANAS = f"""
ALTER TABLE sell_out_campanas
  ADD COLUMN IF NOT EXISTS monto_total NUMERIC(18, 2),
  DROP CONSTRAINT IF EXISTS ck_sell_out_campanas_tipo,
  DROP CONSTRAINT IF EXISTS ck_sell_out_campanas_monto_segun_tipo,
  ADD CONSTRAINT ck_sell_out_campanas_tipo CHECK ({TIPO}),
  ADD CONSTRAINT ck_sell_out_campanas_monto_segun_tipo CHECK ({MONTO_SEGUN_TIPO})
"""
UPGRADE_ITEMS = f"""
ALTER TABLE sell_out_campana_items
  ADD COLUMN IF NOT EXISTS reparto_porcentaje NUMERIC(7, 4),
  ADD COLUMN IF NOT EXISTS reparto_monto NUMERIC(18, 2),
  ALTER COLUMN monto_unit DROP NOT NULL,
  DROP CONSTRAINT IF EXISTS ck_sell_out_campana_items_un_monto,
  DROP CONSTRAINT IF EXISTS ck_sell_out_campana_items_reparto_porcentaje,
  DROP CONSTRAINT IF EXISTS ck_sell_out_campana_items_reparto_monto,
  ADD CONSTRAINT ck_sell_out_campana_items_un_monto CHECK ({ITEMS_UN_MONTO}),
  ADD CONSTRAINT ck_sell_out_campana_items_reparto_porcentaje CHECK ({ITEMS_REPARTO_PORCENTAJE}),
  ADD CONSTRAINT ck_sell_out_campana_items_reparto_monto CHECK ({ITEMS_REPARTO_MONTO})
"""
UPGRADE_CONSUMOS = "ALTER TABLE sell_out_consumos DROP CONSTRAINT IF EXISTS ck_sell_out_consumos_monto_no_negativo"

# Fails loudly rather than silently deleting money rows. Runs only while the new columns exist (idempotent).
DOWNGRADE_GUARD = f"""
DO $guard$
BEGIN
  IF EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_schema = current_schema() AND table_name = 'sell_out_campanas' AND column_name = 'monto_total'
  ) THEN
    IF EXISTS (SELECT 1 FROM sell_out_campanas WHERE tipo = 'monto_total' OR monto_total IS NOT NULL) THEN
      RAISE EXCEPTION 'downgrade of {revision} refused: monto_total sell-out campaigns exist';
    END IF;
    IF EXISTS (
      SELECT 1 FROM sell_out_campana_items WHERE reparto_porcentaje IS NOT NULL OR reparto_monto IS NOT NULL
    ) THEN
      RAISE EXCEPTION 'downgrade of {revision} refused: sell-out campaign shares (reparto) exist';
    END IF;
  END IF;
  IF EXISTS (SELECT 1 FROM sell_out_consumos WHERE monto < 0) THEN
    RAISE EXCEPTION 'downgrade of {revision} refused: negative sell-out consumptions exist';
  END IF;
END
$guard$
"""
DOWNGRADE_CONSUMOS = f"""
ALTER TABLE sell_out_consumos
  DROP CONSTRAINT IF EXISTS ck_sell_out_consumos_monto_no_negativo,
  ADD CONSTRAINT ck_sell_out_consumos_monto_no_negativo CHECK ({_CONSUMOS_NO_NEGATIVO_PREVIO})
"""
DOWNGRADE_ITEMS = """
ALTER TABLE sell_out_campana_items
  DROP CONSTRAINT IF EXISTS ck_sell_out_campana_items_reparto_monto,
  DROP CONSTRAINT IF EXISTS ck_sell_out_campana_items_reparto_porcentaje,
  DROP CONSTRAINT IF EXISTS ck_sell_out_campana_items_un_monto,
  DROP COLUMN IF EXISTS reparto_monto,
  DROP COLUMN IF EXISTS reparto_porcentaje,
  ALTER COLUMN monto_unit SET NOT NULL
"""
DOWNGRADE_CAMPANAS = f"""
ALTER TABLE sell_out_campanas
  DROP CONSTRAINT IF EXISTS ck_sell_out_campanas_monto_segun_tipo,
  DROP CONSTRAINT IF EXISTS ck_sell_out_campanas_tipo,
  DROP COLUMN IF EXISTS monto_total,
  ADD CONSTRAINT ck_sell_out_campanas_tipo CHECK ({_TIPO_PREVIO}),
  ADD CONSTRAINT ck_sell_out_campanas_monto_segun_tipo CHECK ({_MONTO_SEGUN_TIPO_PREVIO})
"""


def _run(statements: List[str]) -> None:
    # Plain SQL (works in offline `--sql` mode); restores the caller's lock_timeout.
    op.execute("SELECT set_config('sell_out_monto_total.lock_timeout_previo', current_setting('lock_timeout'), true)")
    op.execute(f"SELECT set_config('lock_timeout', '{LOCK_TIMEOUT}', true)")
    for statement in statements:
        op.execute(statement)
    op.execute("SELECT set_config('lock_timeout', current_setting('sell_out_monto_total.lock_timeout_previo'), true)")


def upgrade() -> None:
    _run([UPGRADE_CAMPANAS, UPGRADE_ITEMS, UPGRADE_CONSUMOS])


def downgrade() -> None:
    _run([DOWNGRADE_GUARD, DOWNGRADE_CONSUMOS, DOWNGRADE_ITEMS, DOWNGRADE_CAMPANAS])
