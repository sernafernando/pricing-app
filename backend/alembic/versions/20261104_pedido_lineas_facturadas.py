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

- One row per (pedido, item): SUM(it_qty) of the invoice's
  `tb_item_transactions` lines, item_id NOT NULL, combo components left out.
- Only invoices still in `v_facturas_compra_vigentes` count (an annulled one
  has no lines); rows whose net is below one unit are not stored.
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

BACKFILL = """
INSERT INTO pedido_compra_lineas_facturadas (pedido_id, item_id, cantidad)
SELECT p.id, it.item_id, CAST(SUM(it.it_qty) AS INTEGER)
FROM pedidos_compra p
JOIN v_facturas_compra_vigentes v ON v.ct_transaction = p.ct_transaction_id
JOIN tb_item_transactions it ON it.ct_transaction = p.ct_transaction_id
WHERE p.ct_transaction_id IS NOT NULL
  AND it.item_id IS NOT NULL
  AND NOT (
    COALESCE(it.it_isassociation, false) = true
    AND COALESCE(it.it_order, 1) <> 1
    AND it.it_isassociationgroup IS NOT NULL
  )
GROUP BY p.id, it.item_id
HAVING SUM(it.it_qty) >= 1
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
