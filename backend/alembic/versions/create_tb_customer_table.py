"""create tb_customer table

Revision ID: create_tb_customer
Revises: change_pm_string
Create Date: 2025-12-03

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'create_tb_customer'
down_revision = 'change_pm_string'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'tb_customer',
        # Primary Keys
        sa.Column('comp_id', sa.Integer(), nullable=False),
        sa.Column('cust_id', sa.Integer(), nullable=False),

        # Datos básicos
        sa.Column('bra_id', sa.Integer(), nullable=True),
        sa.Column('cust_name', sa.String(500), nullable=True),
        sa.Column('cust_name1', sa.String(500), nullable=True),
        sa.Column('fc_id', sa.Integer(), nullable=True),
        sa.Column('cust_taxnumber', sa.String(50), nullable=True),
        sa.Column('tnt_id', sa.Integer(), nullable=True),

        # Dirección
        sa.Column('cust_address', sa.String(500), nullable=True),
        sa.Column('cust_city', sa.String(255), nullable=True),
        sa.Column('cust_zip', sa.String(20), nullable=True),
        sa.Column('country_id', sa.Integer(), nullable=True),
        sa.Column('state_id', sa.Integer(), nullable=True),

        # Contacto
        sa.Column('cust_phone1', sa.String(100), nullable=True),
        sa.Column('cust_cellphone', sa.String(100), nullable=True),
        sa.Column('cust_email', sa.String(255), nullable=True),

        # Comercial
        sa.Column('sm_id', sa.Integer(), nullable=True),
        sa.Column('sm_id_2', sa.Integer(), nullable=True),
        sa.Column('cust_inactive', sa.Boolean(), nullable=True),
        sa.Column('prli_id', sa.Integer(), nullable=True),

        # MercadoLibre
        sa.Column('cust_mercadolibrenickname', sa.String(255), nullable=True),
        sa.Column('cust_mercadolibreid', sa.String(100), nullable=True),

        # Fechas de auditoría
        sa.Column('cust_cd', sa.DateTime(), nullable=True),
        sa.Column('cust_lastupdate', sa.DateTime(), nullable=True),

        # Auditoría local
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),

        sa.PrimaryKeyConstraint('comp_id', 'cust_id')
    )

    # Índices
    op.create_index('ix_tb_customer_cust_id', 'tb_customer', ['cust_id'], unique=False)
    op.create_index('ix_tb_customer_cust_taxnumber', 'tb_customer', ['cust_taxnumber'], unique=False)


def downgrade():
    op.drop_index('ix_tb_customer_cust_taxnumber', table_name='tb_customer')
    op.drop_index('ix_tb_customer_cust_id', table_name='tb_customer')
    op.drop_table('tb_customer')
