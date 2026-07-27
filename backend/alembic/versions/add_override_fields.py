"""Add more override fields to ventas override tables

Revision ID: add_override_fields
Revises: create_ventas_override_tables
Create Date: 2025-12-11

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'add_override_fields'
down_revision = 'create_ventas_override_tables'
branch_labels = None
depends_on = None


def upgrade():
    # Agregar campos a ventas_tienda_nube_override
    op.add_column('ventas_tienda_nube_override', sa.Column('codigo', sa.String(100), nullable=True))
    op.add_column('ventas_tienda_nube_override', sa.Column('descripcion', sa.Text(), nullable=True))
    op.add_column('ventas_tienda_nube_override', sa.Column('cliente', sa.String(255), nullable=True))
    op.add_column('ventas_tienda_nube_override', sa.Column('cantidad', sa.Numeric(18, 4), nullable=True))
    op.add_column('ventas_tienda_nube_override', sa.Column('precio_unitario', sa.Numeric(18, 2), nullable=True))
    op.add_column('ventas_tienda_nube_override', sa.Column('costo_unitario', sa.Numeric(18, 6), nullable=True))

    # Agregar campos a ventas_fuera_ml_override
    op.add_column('ventas_fuera_ml_override', sa.Column('codigo', sa.String(100), nullable=True))
    op.add_column('ventas_fuera_ml_override', sa.Column('descripcion', sa.Text(), nullable=True))
    op.add_column('ventas_fuera_ml_override', sa.Column('cliente', sa.String(255), nullable=True))
    op.add_column('ventas_fuera_ml_override', sa.Column('cantidad', sa.Numeric(18, 4), nullable=True))
    op.add_column('ventas_fuera_ml_override', sa.Column('precio_unitario', sa.Numeric(18, 2), nullable=True))
    op.add_column('ventas_fuera_ml_override', sa.Column('costo_unitario', sa.Numeric(18, 6), nullable=True))


def downgrade():
    # Eliminar campos de ventas_tienda_nube_override
    op.drop_column('ventas_tienda_nube_override', 'costo_unitario')
    op.drop_column('ventas_tienda_nube_override', 'precio_unitario')
    op.drop_column('ventas_tienda_nube_override', 'cantidad')
    op.drop_column('ventas_tienda_nube_override', 'cliente')
    op.drop_column('ventas_tienda_nube_override', 'descripcion')
    op.drop_column('ventas_tienda_nube_override', 'codigo')

    # Eliminar campos de ventas_fuera_ml_override
    op.drop_column('ventas_fuera_ml_override', 'costo_unitario')
    op.drop_column('ventas_fuera_ml_override', 'precio_unitario')
    op.drop_column('ventas_fuera_ml_override', 'cantidad')
    op.drop_column('ventas_fuera_ml_override', 'cliente')
    op.drop_column('ventas_fuera_ml_override', 'descripcion')
    op.drop_column('ventas_fuera_ml_override', 'codigo')
