"""create tb_tax_number_type table

Revision ID: create_tb_tax_number_type
Revises: create_tb_fiscal_class
Create Date: 2025-12-03

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'create_tb_tax_number_type'
down_revision = 'create_tb_fiscal_class'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'tb_tax_number_type',
        # Primary Key
        sa.Column('tnt_id', sa.Integer(), nullable=False),

        # Datos básicos
        sa.Column('tnt_desc', sa.String(255), nullable=True),
        sa.Column('tnt_afip', sa.Integer(), nullable=True),

        # Auditoría local
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),

        sa.PrimaryKeyConstraint('tnt_id')
    )

    op.create_index('ix_tb_tax_number_type_tnt_id', 'tb_tax_number_type', ['tnt_id'], unique=False)


def downgrade():
    op.drop_index('ix_tb_tax_number_type_tnt_id', table_name='tb_tax_number_type')
    op.drop_table('tb_tax_number_type')
