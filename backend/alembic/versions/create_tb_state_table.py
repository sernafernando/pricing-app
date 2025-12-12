"""create tb_state table

Revision ID: create_tb_state
Revises: create_tb_tax_number_type
Create Date: 2025-12-03

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'create_tb_state'
down_revision = 'create_tb_tax_number_type'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'tb_state',
        # Primary Keys
        sa.Column('country_id', sa.Integer(), nullable=False),
        sa.Column('state_id', sa.Integer(), nullable=False),

        # Datos básicos
        sa.Column('state_desc', sa.String(255), nullable=True),
        sa.Column('state_afip', sa.Integer(), nullable=True),
        sa.Column('state_jurisdiccion', sa.Integer(), nullable=True),
        sa.Column('state_arba_cot', sa.String(10), nullable=True),
        sa.Column('state_visatodopago', sa.String(50), nullable=True),
        sa.Column('country_visatodopago', sa.String(50), nullable=True),
        sa.Column('mlstatedescription', sa.String(255), nullable=True),
        sa.Column('state_enviopackid', sa.String(50), nullable=True),

        # Auditoría local
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),

        sa.PrimaryKeyConstraint('country_id', 'state_id')
    )

    op.create_index('ix_tb_state_state_id', 'tb_state', ['state_id'], unique=False)


def downgrade():
    op.drop_index('ix_tb_state_state_id', table_name='tb_state')
    op.drop_table('tb_state')
