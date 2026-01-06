"""add tipo_generacion to zonas_reparto

Revision ID: 20250106_add_tipo_generacion
Revises: 20250105_turbo_routing_01
Create Date: 2025-01-06 15:00:00

Agrega columna tipo_generacion a zonas_reparto para distinguir entre:
- 'manual': Zonas creadas manualmente por usuarios
- 'automatica': Zonas auto-generadas por K-Means clustering

Esto permite eliminar solo zonas automáticas al regenerar, 
conservando las zonas manuales.
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '20250106_add_tipo_generacion'
down_revision = '20250105_turbo_routing_01'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Agregar columna tipo_generacion
    op.add_column(
        'zonas_reparto',
        sa.Column(
            'tipo_generacion',
            sa.String(20),
            server_default='manual',
            nullable=False
        )
    )
    
    # Crear índice para búsquedas rápidas
    op.create_index(
        'idx_zonas_tipo_generacion',
        'zonas_reparto',
        ['tipo_generacion'],
        unique=False
    )
    
    # Marcar todas las zonas existentes como 'manual'
    op.execute("UPDATE zonas_reparto SET tipo_generacion = 'manual' WHERE tipo_generacion IS NULL")
    
    # Agregar comentario
    op.execute(
        "COMMENT ON COLUMN zonas_reparto.tipo_generacion IS "
        "'Tipo de generación: manual (creada por usuario) o automatica (K-Means)'"
    )


def downgrade() -> None:
    # Eliminar índice
    op.drop_index('idx_zonas_tipo_generacion', table_name='zonas_reparto')
    
    # Eliminar columna
    op.drop_column('zonas_reparto', 'tipo_generacion')
