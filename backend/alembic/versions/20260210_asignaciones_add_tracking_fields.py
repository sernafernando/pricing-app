"""add asignado_por_id and estado_hash to asignaciones for assignment tracking

Revision ID: 20260210_asig_tracking
Revises: 20260210_asignaciones
Create Date: 2026-02-10 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '20260210_asig_tracking'
down_revision = '20260210_asignaciones'
branch_labels = None
depends_on = None


def upgrade():
    # 1. Add asignado_por_id column (who created the assignment)
    op.add_column('asignaciones', sa.Column(
        'asignado_por_id',
        sa.Integer(),
        sa.ForeignKey('usuarios.id'),
        nullable=True  # Temporarily nullable for existing rows
    ))

    # 2. Add estado_hash column (fingerprint of state at assignment time)
    op.add_column('asignaciones', sa.Column(
        'estado_hash',
        sa.String(64),
        nullable=True
    ))

    # 3. Backfill: set asignado_por_id = usuario_id for existing rows (self-assigned)
    op.execute("""
        UPDATE asignaciones
        SET asignado_por_id = usuario_id
        WHERE asignado_por_id IS NULL;
    """)

    # 4. Make asignado_por_id NOT NULL after backfill
    op.alter_column('asignaciones', 'asignado_por_id', nullable=False)

    # 5. Create indexes
    op.create_index('idx_asignacion_asignado_por', 'asignaciones', ['asignado_por_id'])
    op.create_index('idx_asignacion_estado_hash', 'asignaciones', ['estado_hash'])


def downgrade():
    op.drop_index('idx_asignacion_estado_hash', table_name='asignaciones')
    op.drop_index('idx_asignacion_asignado_por', table_name='asignaciones')
    op.drop_column('asignaciones', 'estado_hash')
    op.drop_column('asignaciones', 'asignado_por_id')
