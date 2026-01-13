"""add cust_gbpcomunityid to tb_customer

Revision ID: 20250113_add_cust_guid
Revises: 20250113_add_byprocess
Create Date: 2025-01-13 01:00:00

Agrega columna cust_gbpcomunityid (GUID) a tb_customer.
Permite enfoque híbrido: filtrar por timestamp y comparar con GUID.
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '20250113_add_cust_guid'
down_revision = '20250113_add_byprocess'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Agregar columna cust_gbpcomunityid
    op.add_column(
        'tb_customer',
        sa.Column('cust_gbpcomunityid', sa.String(length=100), nullable=True)
    )
    
    # Crear índice para mejorar queries de sync
    op.create_index(
        'idx_tb_customer_gbpcomunityid',
        'tb_customer',
        ['cust_gbpcomunityid'],
        unique=False
    )
    
    # Agregar comentario
    op.execute(
        "COMMENT ON COLUMN tb_customer.cust_gbpcomunityid IS "
        "'GUID del cliente para detectar cambios con precisión en sync híbrido'"
    )


def downgrade() -> None:
    # Eliminar índice
    op.drop_index('idx_tb_customer_gbpcomunityid', table_name='tb_customer')
    
    # Eliminar columna
    op.drop_column('tb_customer', 'cust_gbpcomunityid')
