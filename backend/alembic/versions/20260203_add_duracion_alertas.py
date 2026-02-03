"""add duracion_segundos to alertas

Revision ID: 20260203_duracion_alertas
Revises: merge_heads_20251222
Create Date: 2026-02-03 09:00:00

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '20260203_duracion_alertas'
down_revision = 'db78d30e1d6d'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Agregar columna duracion_segundos a la tabla alertas
    op.add_column('alertas', sa.Column('duracion_segundos', sa.Integer(), nullable=False, server_default='5'))
    
    # Remover server_default después de agregar la columna (para que nuevas filas usen el default del modelo)
    op.alter_column('alertas', 'duracion_segundos', server_default=None)


def downgrade() -> None:
    # Remover columna duracion_segundos
    op.drop_column('alertas', 'duracion_segundos')
