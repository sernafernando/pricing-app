"""pedido_compra_lineas_facturadas: importe_neto + moneda (net invoiced amount)

Revision ID: 20261110_pedido_lineas_facturadas_importe
Revises: 20261109_sell_out_triggers
Create Date: 2026-10-21

sell-in-sell-out T3g-1 (M1). A % sell in is a percentage of the invoiced cost
without VAT (owner 2026-10-21: "Costo facturado sin IVA"), so each snapshot row
also keeps the net amount of its units and that amount's currency. Inert: no
reader yet. From now on `erp_matching_service.reconciliar_lineas_facturadas`
writes both; this upgrade fills them for the rows already there.

- importe_neto = ROUND(SUM(it_qty * it_price * sd_plusorminus), 2) over the
  invoice and its credit notes (the same documents as `cantidad`), clamped at 0.
  `it_price` is already net of the line discounts (measured on the dev-DB mirror 2026-10-21).
- moneda = the lines' own currency (`tb_item_transactions.curr_id`, 1=ARS,
  2=USD), not the invoice header's: an ARS-header invoice can carry USD-priced
  lines. Mixed currencies, a line without price, or an unknown currency → both
  NULL. CHECKs: importe_neto >= 0, moneda IN ('ARS', 'USD').
- Nothing is queued for the sell-in bonus (a per-unit amount). The backfill
  UPDATE sets only these two columns, outside the trigger's
  `AFTER UPDATE OF pedido_id, item_id, cantidad` list. The live reconcile's
  upsert does SET cantidad, so for it the guard is the trigger's WHEN clause
  (`(OLD.pedido_id, OLD.item_id, OLD.cantidad) IS DISTINCT FROM (NEW...)`):
  an amount/currency-only change does not queue the pedido, a quantity change
  does (tests/services/erp_matching/test_bono_queue_postgres.py).

LOCK NOTE: ADD COLUMN/ADD CONSTRAINT take an ACCESS EXCLUSIVE lock on the
table (nullable columns without default: no rewrite; the CHECKs scan the small
snapshot once). The ERP sync rewrites the snapshot inside its own transaction,
so behind it the ALTER would queue and block every reader; upgrade and
downgrade run with `lock_timeout = '5s'` and the deploy is retried. `env.py`
runs all pending revisions in ONE transaction, so the previous value is saved
and restored (same pattern as 20261109_sell_out_triggers).

The downgrade drops both columns; the ERP mirror still holds every line.
"""

from typing import List, Sequence, Union

from alembic import op

revision: str = "20261110_pedido_lineas_facturadas_importe"
down_revision: Union[str, None] = "20261109_sell_out_triggers"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

LOCK_TIMEOUT = "5s"

ADD_COLUMNS = """
ALTER TABLE pedido_compra_lineas_facturadas
  ADD COLUMN importe_neto NUMERIC(18, 2),
  ADD COLUMN moneda VARCHAR(3),
  ADD CONSTRAINT ck_pedido_compra_lineas_facturadas_importe_no_negativo
    CHECK (importe_neto IS NULL OR importe_neto >= 0),
  ADD CONSTRAINT ck_pedido_compra_lineas_facturadas_moneda CHECK (moneda IN ('ARS', 'USD'))
"""

DROP_COLUMNS = """
ALTER TABLE pedido_compra_lineas_facturadas
  DROP CONSTRAINT IF EXISTS ck_pedido_compra_lineas_facturadas_moneda,
  DROP CONSTRAINT IF EXISTS ck_pedido_compra_lineas_facturadas_importe_no_negativo,
  DROP COLUMN IF EXISTS moneda,
  DROP COLUMN IF EXISTS importe_neto
"""

# Frozen copy of erp_matching_service._LINEAS_ORIGEN_SQL (all pedidos) so the
# migration does not import app code; it follows the corregido_desde_id chain
# for credit notes frozen on a corrected-from pedido (see the service).
_VALIDO = (
    "COUNT(DISTINCT it.curr_id) = 1 AND COUNT(it.curr_id) = COUNT(*) "
    "AND COUNT(it.it_price) = COUNT(*) AND MIN(it.curr_id) IN (1, 2)"
)
BACKFILL = f"""
UPDATE pedido_compra_lineas_facturadas AS l
SET importe_neto = s.importe_neto, moneda = s.moneda
FROM (
  SELECT d.pedido_id, it.item_id,
         CASE WHEN {_VALIDO} THEN
           CASE WHEN SUM(it.it_qty * it.it_price * v.sd_plusorminus) < 0 THEN 0
                ELSE ROUND(SUM(it.it_qty * it.it_price * v.sd_plusorminus), 2) END
         END AS importe_neto,
         CASE WHEN {_VALIDO} THEN CASE MIN(it.curr_id) WHEN 1 THEN 'ARS' ELSE 'USD' END END AS moneda
  FROM (
    SELECT p.id AS pedido_id, p.ct_transaction_id AS ct
    FROM pedidos_compra p
    WHERE p.ct_transaction_id IS NOT NULL
    UNION
    SELECT p.id, n.ct
    FROM pedidos_compra p
    JOIN (
      WITH RECURSIVE cadena(pedido_id, ancestro_id) AS (
        SELECT p.id, p.id FROM pedidos_compra p WHERE p.ct_transaction_id IS NOT NULL
        UNION
        SELECT c.pedido_id, a.corregido_desde_id
        FROM cadena c JOIN pedidos_compra a ON a.id = c.ancestro_id
        WHERE a.corregido_desde_id IS NOT NULL
      )
      SELECT pedido_id, ancestro_id FROM cadena
    ) cad ON cad.pedido_id = p.id
    JOIN (
      SELECT i.destino_tipo, i.destino_id,
             CASE WHEN i.origen_tipo = 'nota_credito_erp' THEN i.origen_id ELSE ncl.ct_transaction_id END AS ct
      FROM imputaciones i
      LEFT JOIN notas_credito_local ncl ON i.origen_tipo = 'nota_credito_local' AND ncl.id = i.origen_id
      WHERE i.origen_tipo IN ('nota_credito_erp', 'nota_credito_local')
        AND i.es_reversal = false
        AND NOT EXISTS (SELECT 1 FROM imputaciones r WHERE r.es_reversal = true AND r.reimputada_desde_id = i.id)
    ) n ON (n.destino_tipo = 'pedido_compra' AND n.destino_id = cad.ancestro_id)
        OR (n.destino_tipo = 'factura_erp' AND n.destino_id = p.ct_transaction_id)
    JOIN v_facturas_compra_vigentes vn ON vn.ct_transaction = n.ct AND vn.clasificacion = 'NC'
    WHERE p.ct_transaction_id IS NOT NULL
  ) d
  JOIN v_facturas_compra_vigentes v ON v.ct_transaction = d.ct
  JOIN tb_item_transactions it ON it.ct_transaction = d.ct
  WHERE it.item_id IS NOT NULL
    AND NOT (
      COALESCE(it.it_isassociation, false) = true
      AND COALESCE(it.it_order, 1) <> 1
      AND it.it_isassociationgroup IS NOT NULL
    )
  GROUP BY d.pedido_id, it.item_id
) s
WHERE s.pedido_id = l.pedido_id AND s.item_id = l.item_id
"""


def _run(statements: List[str]) -> None:
    # Plain SQL (works in offline `--sql` mode); restores the caller's lock_timeout.
    op.execute("SELECT set_config('lineas_importe.lock_timeout_previo', current_setting('lock_timeout'), true)")
    op.execute(f"SELECT set_config('lock_timeout', '{LOCK_TIMEOUT}', true)")
    for statement in statements:
        op.execute(statement)
    op.execute("SELECT set_config('lock_timeout', current_setting('lineas_importe.lock_timeout_previo'), true)")


def upgrade() -> None:
    _run([ADD_COLUMNS, BACKFILL])


def downgrade() -> None:
    _run([DROP_COLUMNS])
