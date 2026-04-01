"""Add mlsubstatus column to tb_mercadolibre_orders_shipping

MercadoLibre devuelve un substatus junto con el status del envío que da
contexto adicional: out_for_delivery, waiting_for_withdrawal, claimed_me,
delivery_behind_schedule, etc. Hasta ahora lo extraíamos en el webhook
pero no lo persistíamos.

Revision ID: 20260401_mlsubstatus
Revises: 20260331_datos_bancarios
Create Date: 2026-04-01
"""

import sqlalchemy as sa
from alembic import op

revision = "20260401_mlsubstatus"
down_revision = "20260331_datos_bancarios"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "tb_mercadolibre_orders_shipping",
        sa.Column("mlsubstatus", sa.String(100), nullable=True),
    )
    op.create_index(
        "ix_ml_orders_shipping_mlsubstatus",
        "tb_mercadolibre_orders_shipping",
        ["mlsubstatus"],
    )


def downgrade() -> None:
    op.drop_index("ix_ml_orders_shipping_mlsubstatus", table_name="tb_mercadolibre_orders_shipping")
    op.drop_column("tb_mercadolibre_orders_shipping", "mlsubstatus")
