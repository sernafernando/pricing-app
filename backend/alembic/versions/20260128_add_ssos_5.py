"""add_ssos_5_pendiente_verificar

Revision ID: 20260128_add_ssos_5
Revises: 20260128_sale_order_status
Create Date: 2026-01-28

Agrega estado ssos_id = 5 (Pedidos Pendientes de Verificar)
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '20260128_add_ssos_5'
down_revision = '20260128_sale_order_status'
branch_labels = None
depends_on = None


def upgrade():
    """Agregar estado 5"""
    op.execute("""
        INSERT INTO tb_sale_order_status (ssos_id, ssos_name, ssos_category, ssos_color, ssos_order) VALUES
        (5, 'eCommerce GBP: Pedidos Pendientes de Verificar', 'pendiente_verificacion', '#FF9800', 0)
    """)


def downgrade():
    """Eliminar estado 5"""
    op.execute("DELETE FROM tb_sale_order_status WHERE ssos_id = 5")
