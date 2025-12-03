"""create tb_branch table

Revision ID: create_tb_branch
Revises: create_tb_customer
Create Date: 2025-12-03

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'create_tb_branch'
down_revision = 'create_tb_customer'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'tb_branch',
        # Primary Keys
        sa.Column('comp_id', sa.Integer(), nullable=False),
        sa.Column('bra_id', sa.Integer(), nullable=False),

        # Datos básicos
        sa.Column('bra_desc', sa.String(255), nullable=True),
        sa.Column('bra_maindesc', sa.String(255), nullable=True),
        sa.Column('country_id', sa.Integer(), nullable=True),
        sa.Column('state_id', sa.Integer(), nullable=True),

        # Dirección
        sa.Column('bra_address', sa.String(500), nullable=True),
        sa.Column('bra_phone', sa.String(100), nullable=True),
        sa.Column('bra_taxnumber', sa.String(50), nullable=True),

        # Estado
        sa.Column('bra_disabled', sa.Boolean(), nullable=True),

        # Auditoría local
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),

        sa.PrimaryKeyConstraint('comp_id', 'bra_id')
    )

    op.create_index('ix_tb_branch_bra_id', 'tb_branch', ['bra_id'], unique=False)


def downgrade():
    op.drop_index('ix_tb_branch_bra_id', table_name='tb_branch')
    op.drop_table('tb_branch')
