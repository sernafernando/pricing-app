"""pedido_compra_facturas M:N ERP invoice links

Revision ID: 20261110_pedido_compra_facturas
Revises: 20261110_tactical_cobranza
Create Date: 2026-11-10

Compras multi-factura: relation table is SoT for N CTs per pedido (and shared
CTs across pedidos). Header ct_transaction_id / fecha_factura stays first-link
cache — backfill one row per existing header link.

Unique (pedido_id, ct_transaction_id); indexes on pedido_id and ct_transaction_id.
No global unique on CT (M:N by design).
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20261110_pedido_compra_facturas"
down_revision: Union[str, None] = "20261110_tactical_cobranza"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("SELECT set_config('lock_timeout', '5s', false)")
    op.create_table(
        "pedido_compra_facturas",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("pedido_id", sa.BigInteger(), nullable=False),
        sa.Column("ct_transaction_id", sa.BigInteger(), nullable=False),
        sa.Column("fecha_factura", sa.Date(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["pedido_id"],
            ["pedidos_compra.id"],
            name="fk_pedido_compra_facturas_pedido_id",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "pedido_id",
            "ct_transaction_id",
            name="uq_pedido_compra_facturas_pedido_ct",
        ),
    )
    op.create_index("ix_pedido_compra_facturas_pedido_id", "pedido_compra_facturas", ["pedido_id"])
    op.create_index(
        "ix_pedido_compra_facturas_ct_transaction_id",
        "pedido_compra_facturas",
        ["ct_transaction_id"],
    )
    op.execute(
        """
        INSERT INTO pedido_compra_facturas
            (pedido_id, ct_transaction_id, fecha_factura, created_at)
        SELECT id, ct_transaction_id, fecha_factura, CURRENT_TIMESTAMP
        FROM pedidos_compra
        WHERE ct_transaction_id IS NOT NULL
        """
    )
    op.execute("SELECT set_config('lock_timeout', '0', false)")


def downgrade() -> None:
    op.drop_index(
        "ix_pedido_compra_facturas_ct_transaction_id",
        table_name="pedido_compra_facturas",
    )
    op.drop_index("ix_pedido_compra_facturas_pedido_id", table_name="pedido_compra_facturas")
    op.drop_table("pedido_compra_facturas")
