"""add export_activo field to sale_order_header

Revision ID: add_export_activo
Revises: add_envio_fields_soh
Create Date: 2025-12-23

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'add_export_activo'
down_revision = 'add_envio_fields_soh'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Agregar campo export_activo para marcar pedidos activos/archivados del export
    op.add_column('tb_sale_order_header', 
        sa.Column('export_activo', sa.Boolean, nullable=True, default=True)
    )
    
    # Setear True por defecto en registros existentes que tienen export_id
    op.execute("""
        UPDATE tb_sale_order_header 
        SET export_activo = TRUE 
        WHERE export_id IS NOT NULL
    """)


def downgrade() -> None:
    op.drop_column('tb_sale_order_header', 'export_activo')
