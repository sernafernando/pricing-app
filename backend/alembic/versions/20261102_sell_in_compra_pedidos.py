"""sell_in_compra_pedidos: link a sell in to its Compras operations

Revision ID: 20261102_sell_in_compra_pedidos
Revises: 20261101_combo_componentes
Create Date: 2026-10-18

sell-in-sell-out T3b, first step. `sell_in_compra_pedidos`
(`SellInCompraPedido` in `app/models/sell_in.py`) links a sell-in purchase to
a Compras operation (`pedidos_compra`), so a later change can let one sell in
point to several operations. For now the service keeps it in step with the old
`sell_in_compras.pedido_compra_id` column, which stays.

- UNIQUE(compra_id, pedido_compra_id); no unique on `pedido_compra_id` alone:
  one operation may already serve several sell ins.
- Both foreign keys CASCADE. Deleting an operation today sets the old column to
  NULL; removing the link row is the same outcome.
- The upgrade fills one link per purchase whose old column is set.

The downgrade drops the table; the old column still holds every reference.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20261102_sell_in_compra_pedidos"
down_revision: Union[str, None] = "20261101_combo_componentes"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_BACKFILL = """
INSERT INTO sell_in_compra_pedidos (compra_id, pedido_compra_id)
SELECT id, pedido_compra_id FROM sell_in_compras
WHERE pedido_compra_id IS NOT NULL
"""


def upgrade() -> None:
    op.create_table(
        "sell_in_compra_pedidos",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("compra_id", sa.BigInteger(), nullable=False),
        sa.Column("pedido_compra_id", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["compra_id"], ["sell_in_compras.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["pedido_compra_id"], ["pedidos_compra.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("compra_id", "pedido_compra_id", name="uq_sell_in_compra_pedidos_compra_pedido"),
    )
    op.create_index("ix_sell_in_compra_pedidos_pedido_compra_id", "sell_in_compra_pedidos", ["pedido_compra_id"])
    op.execute(_BACKFILL)


def downgrade() -> None:
    op.drop_index("ix_sell_in_compra_pedidos_pedido_compra_id", table_name="sell_in_compra_pedidos")
    op.drop_table("sell_in_compra_pedidos")
