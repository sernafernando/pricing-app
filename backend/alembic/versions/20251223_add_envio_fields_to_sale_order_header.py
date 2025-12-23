"""add codigo_envio_interno and export_id to sale_order_header

Revision ID: add_envio_fields_soh
Revises: make_rol_nullable
Create Date: 2025-12-23

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'add_envio_fields_soh'
down_revision = 'make_rol_nullable'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Agregar codigo_envio_interno para generar QR en etiquetas
    op.add_column('tb_sale_order_header', 
        sa.Column('codigo_envio_interno', sa.String(length=100), nullable=True)
    )
    
    # Agregar export_id para relacionar con exports del ERP
    op.add_column('tb_sale_order_header', 
        sa.Column('export_id', sa.Integer, nullable=True, index=True)
    )
    
    # Crear índice en codigo_envio_interno para búsquedas rápidas
    op.create_index(
        op.f('ix_tb_sale_order_header_codigo_envio_interno'), 
        'tb_sale_order_header', 
        ['codigo_envio_interno'], 
        unique=False
    )


def downgrade() -> None:
    # Eliminar índice
    op.drop_index(
        op.f('ix_tb_sale_order_header_codigo_envio_interno'), 
        table_name='tb_sale_order_header'
    )
    
    # Eliminar columnas
    op.drop_column('tb_sale_order_header', 'export_id')
    op.drop_column('tb_sale_order_header', 'codigo_envio_interno')
