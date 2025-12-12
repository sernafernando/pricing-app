"""Fix tipo_offset NULL values by inferring from porcentaje/monto

Revision ID: fix_tipo_offset_null
Revises: create_ventas_override_tables
Create Date: 2025-12-10

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'fix_tipo_offset_null'
down_revision = 'create_ventas_override_tables'
branch_labels = None
depends_on = None


def upgrade():
    # Actualizar offsets que tienen porcentaje pero tipo_offset NULL
    op.execute("""
        UPDATE offsets_ganancia
        SET tipo_offset = 'porcentaje_costo'
        WHERE tipo_offset IS NULL AND porcentaje IS NOT NULL
    """)

    # Actualizar offsets que tienen monto pero tipo_offset NULL
    op.execute("""
        UPDATE offsets_ganancia
        SET tipo_offset = 'monto_fijo'
        WHERE tipo_offset IS NULL AND monto IS NOT NULL
    """)

    # Cualquier otro caso, poner default
    op.execute("""
        UPDATE offsets_ganancia
        SET tipo_offset = 'monto_fijo'
        WHERE tipo_offset IS NULL
    """)


def downgrade():
    # No revertimos ya que esto es una corrección de datos
    pass
