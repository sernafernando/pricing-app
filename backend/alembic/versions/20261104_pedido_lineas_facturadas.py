"""pedido_compra_lineas_facturadas: app-side snapshot of invoiced units

Revision ID: 20261104_pedido_lineas_facturadas
Revises: 20261103_pedidos_fecha_factura
Create Date: 2026-10-19

sell-in-sell-out T3c-2. The brand sell in pays per invoiced unit and must read
only app tables, so each Compras operation keeps the units per item of its
linked supplier invoice. From now on
`erp_matching_service.reconciliar_lineas_facturadas` keeps it in step (on link
and unlink, and on every ERP sync); this upgrade fills it for the operations
already linked.

- One row per (pedido, item): net units of the invoice's `tb_item_transactions`
  lines minus those of the purchase credit notes with a vigente imputación to
  the pedido or its invoice (owner 2026-10-19: invoiced 100, returned 10 → 90).
  Sign = the document's sd_plusorminus; item_id NOT NULL; combo components out.
- Only documents still in `v_facturas_compra_vigentes` count (annulled → no
  lines); rows whose net is below one unit are not stored (clamp at 0).
- No FK on item_id: the ERP mirror may hold an item productos_erp lacks.
- BACKFILL runs unchanged on Postgres and on the SQLite test schema
  (tests/unit/test_erp_matching_service.py).

The downgrade drops the table; the ERP mirror still holds every line.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20261104_pedido_lineas_facturadas"
down_revision: Union[str, None] = "20261103_pedidos_fecha_factura"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Same query as erp_matching_service._LINEAS_ORIGEN_SQL (all pedidos), inlined
# so the migration does not import app code. It follows the corregido_desde_id
# chain for credit notes frozen on a corrected-from pedido (see the service).
# FLOOR, not a bare CAST: invoiced units pay a per-unit bonus, so a fractional
# net never rounds up (CAST(numeric AS INTEGER) rounds on PostgreSQL).
BACKFILL = """
INSERT INTO pedido_compra_lineas_facturadas (pedido_id, item_id, cantidad)
SELECT d.pedido_id, it.item_id, CAST(FLOOR(SUM(it.it_qty * v.sd_plusorminus)) AS INTEGER)
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
HAVING SUM(it.it_qty * v.sd_plusorminus) >= 1
"""


def upgrade() -> None:
    op.create_table(
        "pedido_compra_lineas_facturadas",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("pedido_id", sa.BigInteger(), nullable=False),
        sa.Column("item_id", sa.Integer(), nullable=False),
        sa.Column("cantidad", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["pedido_id"], ["pedidos_compra.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("pedido_id", "item_id", name="uq_pedido_compra_lineas_facturadas_pedido_item"),
        sa.CheckConstraint("cantidad > 0", name="ck_pedido_compra_lineas_facturadas_cantidad_positiva"),
    )
    op.create_index("ix_pedido_compra_lineas_facturadas_item_id", "pedido_compra_lineas_facturadas", ["item_id"])
    op.execute(BACKFILL)


def downgrade() -> None:
    op.drop_index("ix_pedido_compra_lineas_facturadas_item_id", table_name="pedido_compra_lineas_facturadas")
    op.drop_table("pedido_compra_lineas_facturadas")
