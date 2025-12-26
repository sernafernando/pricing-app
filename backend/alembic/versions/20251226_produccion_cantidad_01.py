"""add cantidad to produccion prearmado

Revision ID: 20251226_produccion_02
Revises: 20251226_produccion_01
Create Date: 2025-12-26 18:30:00

Agrega campo 'cantidad' a la tabla produccion_prearmado para trackear
cuántas unidades se están pre-armando de cada producto.
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '20251226_produccion_02'
down_revision = '20251226_produccion_01'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Agregar columna cantidad con valor default 1
    op.add_column('produccion_prearmado', sa.Column('cantidad', sa.Integer(), nullable=False, server_default='1'))
    
    # Agregar columna fecha_actualizacion
    op.add_column('produccion_prearmado', sa.Column('fecha_actualizacion', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True))


def downgrade() -> None:
    op.drop_column('produccion_prearmado', 'fecha_actualizacion')
    op.drop_column('produccion_prearmado', 'cantidad')
