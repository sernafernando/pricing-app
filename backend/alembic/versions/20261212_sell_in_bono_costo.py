"""sell_in_bonos_marca: a % of the sale's cost with no purchase or invoice; sell_in_bono_consumos

Revision ID: 20261212_sell_in_bono_costo
Revises: 20261208_ml_sale_lines_tg_unknown
Create Date: 2026-10-29

sell-in-sell-out T25a. Owner: "agregá el de sell in, es para operaciones viejas que no tienen la factura cargada, así
no tenemos que cargar facturas viejas y que en el medio del proceso se olviden alguna".

- `base`: 'factura' (every bonus so far: it applies to the invoiced purchases by invoice date) or 'costo_venta' (a %
  of the cost recorded on each sale in the bonus's dates, no purchase or invoice). A cost bonus is a percentage, in
  pesos (the sale's cost is ARS), over a brand, a category or some models; never one invoice.
- `incluye_iva` (S33): the loaded % includes VAT, so the reconcile divides it by (1 + each product's VAT rate); only a
  cost bonus may carry it.
- `offset_origen_id`: the legacy offset (`offsets_ganancia.id`) the bonus was migrated from, one bonus per offset.
  Provenance only, no FK: the sell-in tables do not depend on the legacy offsets table.
- `sell_in_bono_consumos`: the ARS discount each sale got from a cost bonus, one row per (bonus, channel, sale). Same
  sale reference as `sell_in_consumos` (`ml_sale_lines.item_row_id` or the fuera/TN `it_transaction`, no FK). A cost
  bonus has no purchase line, so it cannot live in `sell_in_consumos` (`compra_item_id` NOT NULL). Bonuses are voided,
  never deleted; the FK cascades anyway.

The bonus update trigger also queues a bonus when `base` or `incluye_iva` changes (the rest of its definition is
20261211's, unchanged); `offset_origen_id` is provenance only. The downgrade puts 20261211's trigger back and drops
the table and the columns (and with them the CHECKs).

LOCK NOTE: ADD COLUMN with a constant default (no rewrite since PG 11), the CHECKs (validated against the few existing
rows) and DROP/CREATE TRIGGER take an ACCESS EXCLUSIVE lock on `sell_in_bonos_marca`, which the `sell_in.bono` worker
reads. Upgrade and downgrade run with `lock_timeout = '5s'` and the deploy is retried; the previous value is saved and
restored because `env.py` runs every pending revision in ONE transaction (same pattern as 20261211). Every step is
idempotent.
"""

from typing import List, Sequence, Union

from alembic import op

revision: str = "20261212_sell_in_bono_costo"
down_revision: Union[str, None] = "20261208_ml_sale_lines_tg_unknown"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

LOCK_TIMEOUT = "5s"

ADD_COLUMNS = """
ALTER TABLE sell_in_bonos_marca
  ADD COLUMN IF NOT EXISTS base VARCHAR(16) NOT NULL DEFAULT 'factura',
  ADD COLUMN IF NOT EXISTS incluye_iva BOOLEAN NOT NULL DEFAULT false,
  ADD COLUMN IF NOT EXISTS offset_origen_id INTEGER,
  DROP CONSTRAINT IF EXISTS ck_sell_in_bonos_marca_base,
  DROP CONSTRAINT IF EXISTS ck_sell_in_bonos_marca_costo_venta,
  DROP CONSTRAINT IF EXISTS uq_sell_in_bonos_marca_offset_origen_id,
  ADD CONSTRAINT ck_sell_in_bonos_marca_base CHECK (base IN ('factura', 'costo_venta')),
  ADD CONSTRAINT ck_sell_in_bonos_marca_costo_venta CHECK (
    (base = 'factura' AND NOT incluye_iva)
    OR (base = 'costo_venta' AND tipo = 'porcentaje' AND moneda = 'ARS' AND alcance IN ('marca', 'categoria', 'modelos'))
  ),
  ADD CONSTRAINT uq_sell_in_bonos_marca_offset_origen_id UNIQUE (offset_origen_id)
"""

CREATE_CONSUMOS = """
CREATE TABLE IF NOT EXISTS sell_in_bono_consumos (
  id BIGSERIAL PRIMARY KEY,
  bono_id BIGINT NOT NULL
    CONSTRAINT fk_sell_in_bono_consumos_bono_id REFERENCES sell_in_bonos_marca (id) ON DELETE CASCADE,
  canal VARCHAR(8) NOT NULL,
  venta_ref BIGINT NOT NULL,
  item_id INTEGER NOT NULL,
  fecha_venta DATE NOT NULL,
  unidades INTEGER NOT NULL,
  descuento_ars NUMERIC(18, 2) NOT NULL,
  CONSTRAINT uq_sell_in_bono_consumos_bono_canal_venta UNIQUE (bono_id, canal, venta_ref),
  CONSTRAINT ck_sell_in_bono_consumos_canal CHECK (canal IN ('ml', 'fuera', 'tn')),
  CONSTRAINT ck_sell_in_bono_consumos_unidades_positivas CHECK (unidades > 0),
  CONSTRAINT ck_sell_in_bono_consumos_descuento_no_negativo CHECK (descuento_ars >= 0)
)
"""

CREATE_INDEXES = [
    "CREATE INDEX IF NOT EXISTS ix_sell_in_bono_consumos_canal_venta ON sell_in_bono_consumos (canal, venta_ref)",
    "CREATE INDEX IF NOT EXISTS ix_sell_in_bono_consumos_item_fecha ON sell_in_bono_consumos (item_id, fecha_venta)",
]

DROP_CONSUMOS = "DROP TABLE IF EXISTS sell_in_bono_consumos"

DROP_COLUMNS = """
ALTER TABLE sell_in_bonos_marca
  DROP CONSTRAINT IF EXISTS uq_sell_in_bonos_marca_offset_origen_id,
  DROP CONSTRAINT IF EXISTS ck_sell_in_bonos_marca_costo_venta,
  DROP CONSTRAINT IF EXISTS ck_sell_in_bonos_marca_base,
  DROP COLUMN IF EXISTS offset_origen_id,
  DROP COLUMN IF EXISTS incluye_iva,
  DROP COLUMN IF EXISTS base
"""

# 20261211's field list, frozen here.
_CAMPOS = (
    "alcance, {r}.marca, {r}.categoria, {r}.pedido_id, {r}.tipo, {r}.monto_unit, {r}.porcentaje, {r}.moneda,\n"
    "     {r}.fecha_desde, {r}.fecha_hasta, {r}.estado, {r}.usuario_id, {r}.tope_unidades, {r}.tope_monto"
)


def _trigger(con_costo: bool) -> str:
    extra = ",\n     {r}.base, {r}.incluye_iva" if con_costo else ""
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
    op.execute("SELECT set_config('bono_costo.lock_timeout_previo', current_setting('lock_timeout'), true)")
    op.execute(f"SELECT set_config('lock_timeout', '{LOCK_TIMEOUT}', true)")
    for statement in statements:
        op.execute(statement)
    op.execute("SELECT set_config('lock_timeout', current_setting('bono_costo.lock_timeout_previo'), true)")


def upgrade() -> None:
    _run([ADD_COLUMNS, CREATE_CONSUMOS, *CREATE_INDEXES, DROP_TRIGGER, _trigger(con_costo=True)])


def downgrade() -> None:
    _run([DROP_TRIGGER, _trigger(con_costo=False), DROP_CONSUMOS, DROP_COLUMNS])
