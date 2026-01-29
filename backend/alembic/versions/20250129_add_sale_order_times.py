"""add sale order times table

Revision ID: 20250129_sale_order_times
Revises: merge_heads_20251222
Create Date: 2025-01-29

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import PrimaryKeyConstraint, Index


# revision identifiers, used by Alembic.
revision = '20250129_sale_order_times'
down_revision = 'merge_heads_20251222'
branch_labels = None
depends_on = None


def upgrade():
    # Crear tabla tb_sale_order_times
    op.create_table(
        'tb_sale_order_times',
        sa.Column('comp_id', sa.Integer(), nullable=False),
        sa.Column('bra_id', sa.Integer(), nullable=False),
        sa.Column('soh_id', sa.BigInteger(), nullable=False),
        sa.Column('sot_id', sa.BigInteger(), nullable=False),
        sa.Column('sot_cd', sa.DateTime(), nullable=True),
        sa.Column('ssot_id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=True),
        
        # Primary key compuesta
        PrimaryKeyConstraint('comp_id', 'bra_id', 'soh_id', 'sot_id'),
    )
    
    # Crear índices
    op.create_index(
        'ix_sale_order_times_soh', 
        'tb_sale_order_times', 
        ['comp_id', 'bra_id', 'soh_id']
    )
    op.create_index(
        'ix_sale_order_times_ssot', 
        'tb_sale_order_times', 
        ['ssot_id']
    )
    op.create_index(
        'ix_sale_order_times_cd', 
        'tb_sale_order_times', 
        ['sot_cd']
    )
    op.create_index(
        'ix_tb_sale_order_times_soh_id',
        'tb_sale_order_times',
        ['soh_id']
    )


def downgrade():
    op.drop_index('ix_tb_sale_order_times_soh_id', table_name='tb_sale_order_times')
    op.drop_index('ix_sale_order_times_cd', table_name='tb_sale_order_times')
    op.drop_index('ix_sale_order_times_ssot', table_name='tb_sale_order_times')
    op.drop_index('ix_sale_order_times_soh', table_name='tb_sale_order_times')
    op.drop_table('tb_sale_order_times')
