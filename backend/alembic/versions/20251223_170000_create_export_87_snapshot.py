"""create export 87 snapshot table

Revision ID: 20251223_170000
Revises: 20251223_160000
Create Date: 2025-12-23 17:00:00

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


# revision identifiers, used by Alembic.
revision = '20251223_170000'
down_revision = '20251223_160000'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'tb_export_87_snapshot',
        sa.Column('snapshot_id', sa.Integer(), nullable=False, autoincrement=True),
        sa.Column('soh_id', sa.Integer(), nullable=False),
        sa.Column('bra_id', sa.Integer(), nullable=True),
        sa.Column('comp_id', sa.Integer(), nullable=True),
        sa.Column('user_id', sa.Integer(), nullable=True),
        sa.Column('order_id', sa.String(50), nullable=True),
        sa.Column('ssos_id', sa.Integer(), nullable=True),
        sa.Column('snapshot_date', sa.DateTime(), nullable=False, server_default=sa.text('NOW()')),
        sa.Column('export_id', sa.Integer(), nullable=False, server_default='87'),
        sa.Column('raw_data', JSONB, nullable=True),
        sa.PrimaryKeyConstraint('snapshot_id'),
        sa.UniqueConstraint('soh_id', 'snapshot_date', name='export_87_snapshot_soh_unique')
    )
    
    op.create_index('idx_export_87_soh_id', 'tb_export_87_snapshot', ['soh_id'])
    op.create_index('idx_export_87_snapshot_date', 'tb_export_87_snapshot', ['snapshot_date'], postgresql_using='btree', postgresql_ops={'snapshot_date': 'DESC'})
    op.create_index('idx_export_87_user_id', 'tb_export_87_snapshot', ['user_id'])
    op.create_index('idx_export_87_order_id', 'tb_export_87_snapshot', ['order_id'])


def downgrade():
    op.drop_index('idx_export_87_order_id', table_name='tb_export_87_snapshot')
    op.drop_index('idx_export_87_user_id', table_name='tb_export_87_snapshot')
    op.drop_index('idx_export_87_snapshot_date', table_name='tb_export_87_snapshot')
    op.drop_index('idx_export_87_soh_id', table_name='tb_export_87_snapshot')
    op.drop_table('tb_export_87_snapshot')
