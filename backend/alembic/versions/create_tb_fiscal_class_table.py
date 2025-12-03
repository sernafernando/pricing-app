"""create tb_fiscal_class table

Revision ID: create_tb_fiscal_class
Revises: create_tb_document_file
Create Date: 2025-12-03

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'create_tb_fiscal_class'
down_revision = 'create_tb_document_file'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'tb_fiscal_class',
        # Primary Key
        sa.Column('fc_id', sa.Integer(), nullable=False),

        # Datos básicos
        sa.Column('fc_desc', sa.String(255), nullable=True),
        sa.Column('fc_kindof', sa.String(10), nullable=True),
        sa.Column('country_id', sa.Integer(), nullable=True),
        sa.Column('fc_legaltaxid', sa.Integer(), nullable=True),

        # Auditoría local
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),

        sa.PrimaryKeyConstraint('fc_id')
    )

    op.create_index('ix_tb_fiscal_class_fc_id', 'tb_fiscal_class', ['fc_id'], unique=False)


def downgrade():
    op.drop_index('ix_tb_fiscal_class_fc_id', table_name='tb_fiscal_class')
    op.drop_table('tb_fiscal_class')
