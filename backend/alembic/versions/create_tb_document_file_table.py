"""create tb_document_file table

Revision ID: create_tb_document_file
Revises: create_tb_salesman
Create Date: 2025-12-03

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'create_tb_document_file'
down_revision = 'create_tb_salesman'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'tb_document_file',
        # Primary Keys
        sa.Column('comp_id', sa.Integer(), nullable=False),
        sa.Column('bra_id', sa.Integer(), nullable=False),
        sa.Column('df_id', sa.Integer(), nullable=False),

        # Datos básicos
        sa.Column('df_desc', sa.String(255), nullable=True),
        sa.Column('df_pointofsale', sa.Integer(), nullable=True),
        sa.Column('df_number', sa.Integer(), nullable=True),
        sa.Column('df_tonumber', sa.Integer(), nullable=True),

        # Estado
        sa.Column('df_disabled', sa.Boolean(), nullable=True),
        sa.Column('df_iselectronicinvoice', sa.Boolean(), nullable=True),

        # Auditoría local
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),

        sa.PrimaryKeyConstraint('comp_id', 'bra_id', 'df_id')
    )

    op.create_index('ix_tb_document_file_df_id', 'tb_document_file', ['df_id'], unique=False)


def downgrade():
    op.drop_index('ix_tb_document_file_df_id', table_name='tb_document_file')
    op.drop_table('tb_document_file')
