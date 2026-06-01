"""Crear tabla stock_por_deposito para stock disponible por depósito vía ERP

Revision ID: 20260601_01_stock_por_deposito
Revises: 20260529_02_consultas_tit_indexes
Create Date: 2026-06-01

Tabla canónica de stock disponible por ítem/depósito, sincronizada desde el ERP
mediante ``ItemStorage_funGetXMLData`` (mismo endpoint que usa erp_sync para
``productos_erp.stock``). Reemplaza el uso de ``tb_item_storage.itst_cant`` en los
endpoints de consultas (ranking, resumen, kpis), que era stock espejo potencialmente
desactualizado.

Índice en (stor_id, item_id) para el LATERAL JOIN de los endpoints de consultas.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20260601_01_stock_por_deposito"
down_revision: Union[str, None] = "20260529_02_consultas_tit_indexes"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "stock_por_deposito",
        sa.Column("item_id", sa.Integer(), nullable=False),
        sa.Column("stor_id", sa.Integer(), nullable=False),
        sa.Column("stock", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.PrimaryKeyConstraint("item_id", "stor_id", name="pk_stock_por_deposito"),
    )
    op.create_index(
        "ix_stock_por_deposito_stor_item",
        "stock_por_deposito",
        ["stor_id", "item_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_stock_por_deposito_stor_item", table_name="stock_por_deposito")
    op.drop_table("stock_por_deposito")
