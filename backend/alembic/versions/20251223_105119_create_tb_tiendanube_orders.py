"""create_tb_tiendanube_orders

Revision ID: 20251223_105119
Revises: 20251223_100905
Create Date: 2025-12-23 10:51:19

Crea tabla tb_tiendanube_orders para almacenar órdenes de TiendaNube desde el ERP.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '20251223_105119'
down_revision = '20251223_100905'
branch_labels = None
depends_on = None


def upgrade():
    """Crea tabla tb_tiendanube_orders"""
    op.create_table(
        'tb_tiendanube_orders',
        sa.Column('comp_id', sa.Integer, nullable=False),
        sa.Column('tno_id', sa.BigInteger, nullable=False),
        sa.Column('tno_cd', sa.DateTime),
        sa.Column('tn_id', sa.Integer),
        sa.Column('tno_orderID', sa.Integer),
        sa.Column('tno_JSon', sa.Text),
        sa.Column('bra_id', sa.Integer),
        sa.Column('soh_id', sa.BigInteger),
        sa.Column('cust_id', sa.Integer),
        sa.Column('tno_isCancelled', sa.Boolean),
        sa.Column('created_at', sa.DateTime, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime, server_default=sa.func.now(), onupdate=sa.func.now()),
        sa.PrimaryKeyConstraint('comp_id', 'tno_id')
    )
    
    # Índices
    op.create_index('ix_tb_tiendanube_orders_comp_id', 'tb_tiendanube_orders', ['comp_id'])
    op.create_index('ix_tb_tiendanube_orders_tno_id', 'tb_tiendanube_orders', ['tno_id'])
    op.create_index('ix_tb_tiendanube_orders_tno_orderID', 'tb_tiendanube_orders', ['tno_orderID'])
    op.create_index('ix_tb_tiendanube_orders_bra_id', 'tb_tiendanube_orders', ['bra_id'])
    op.create_index('ix_tb_tiendanube_orders_soh_id', 'tb_tiendanube_orders', ['soh_id'])


def downgrade():
    """Revierte la creación de la tabla"""
    op.drop_index('ix_tb_tiendanube_orders_soh_id', 'tb_tiendanube_orders')
    op.drop_index('ix_tb_tiendanube_orders_bra_id', 'tb_tiendanube_orders')
    op.drop_index('ix_tb_tiendanube_orders_tno_orderID', 'tb_tiendanube_orders')
    op.drop_index('ix_tb_tiendanube_orders_tno_id', 'tb_tiendanube_orders')
    op.create_index('ix_tb_tiendanube_orders_comp_id', 'tb_tiendanube_orders')
    op.drop_table('tb_tiendanube_orders')
