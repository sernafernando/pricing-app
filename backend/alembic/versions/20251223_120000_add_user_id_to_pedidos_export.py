"""add user_id to pedidos_export

Revision ID: 20251223_120000
Revises: 20251223_115500
Create Date: 2025-12-23 12:00:00

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '20251223_120000'
down_revision = '20251223_115500'
branch_labels = None
depends_on = None


def upgrade():
    """Agrega campo user_id a tb_pedidos_export"""
    op.add_column('tb_pedidos_export', sa.Column('user_id', sa.Integer(), nullable=True, comment='userID del ERP (50021=TN, 50006=ML)'))
    op.create_index('idx_pedidos_export_user_id', 'tb_pedidos_export', ['user_id'])


def downgrade():
    """Remueve campo user_id"""
    op.drop_index('idx_pedidos_export_user_id', table_name='tb_pedidos_export')
    op.drop_column('tb_pedidos_export', 'user_id')
