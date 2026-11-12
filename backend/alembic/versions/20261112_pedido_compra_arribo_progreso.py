"""pedido_compra_arribo_progreso: pre-control arribo/retiro batches.

Revision ID: 20261112_pedido_compra_arribo_progreso
Revises: 20261112_sell_in_bono_cubre_pedido
Create Date: 2026-11-12
"""

from __future__ import annotations

from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "20261112_pedido_compra_arribo_progreso"
down_revision: Union[str, None] = "20261112_sell_in_bono_cubre_pedido"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "pedido_compra_arribo_progreso",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "pedido_id",
            sa.BigInteger(),
            sa.ForeignKey("pedidos_compra.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("oc_comp_id", sa.Integer(), nullable=True),
        sa.Column("oc_bra_id", sa.Integer(), nullable=True),
        sa.Column("oc_poh_id", sa.BigInteger(), nullable=True),
        sa.Column("pod_id", sa.BigInteger(), nullable=False),
        sa.Column("item_id", sa.Integer(), nullable=True),
        sa.Column("cantidad", sa.Numeric(18, 6), nullable=False),
        sa.Column(
            "usuario_id",
            sa.Integer(),
            sa.ForeignKey("usuarios.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("observaciones", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.CheckConstraint("cantidad > 0", name="ck_pcap_cantidad_positiva"),
    )
    op.create_index("ix_pcap_pedido", "pedido_compra_arribo_progreso", ["pedido_id"])
    op.create_index(
        "ix_pcap_pedido_pod",
        "pedido_compra_arribo_progreso",
        ["pedido_id", "pod_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_pcap_pedido_pod", table_name="pedido_compra_arribo_progreso")
    op.drop_index("ix_pcap_pedido", table_name="pedido_compra_arribo_progreso")
    op.drop_table("pedido_compra_arribo_progreso")
