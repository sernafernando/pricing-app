"""create tb_salesman table

Revision ID: create_tb_salesman
Revises: create_tb_branch
Create Date: 2025-12-03

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'create_tb_salesman'
down_revision = 'create_tb_branch'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'tb_salesman',
        # Primary Keys
        sa.Column('comp_id', sa.Integer(), nullable=False),
        sa.Column('sm_id', sa.Integer(), nullable=False),

        # Datos básicos
        sa.Column('sm_name', sa.String(255), nullable=True),
        sa.Column('sm_email', sa.String(255), nullable=True),
        sa.Column('bra_id', sa.Integer(), nullable=True),

        # Comisiones
        sa.Column('sm_commission_bysale', sa.Numeric(10, 4), nullable=True),
        sa.Column('sm_commission_byreceive', sa.Numeric(10, 4), nullable=True),

        # Estado
        sa.Column('sm_disabled', sa.Boolean(), nullable=True),

        # Auditoría local
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),

        sa.PrimaryKeyConstraint('comp_id', 'sm_id')
    )

    op.create_index('ix_tb_salesman_sm_id', 'tb_salesman', ['sm_id'], unique=False)


def downgrade():
    op.drop_index('ix_tb_salesman_sm_id', table_name='tb_salesman')
    op.drop_table('tb_salesman')
