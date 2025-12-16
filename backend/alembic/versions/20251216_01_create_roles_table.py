"""create roles table

Revision ID: 20251216_roles_01
Revises: g1h2i3j4k5l6
Create Date: 2025-12-16

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '20251216_roles_01'
down_revision = 'g1h2i3j4k5l6'
branch_labels = None
depends_on = None


def upgrade():
    # Crear tabla roles
    op.create_table(
        'roles',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('codigo', sa.String(50), nullable=False),
        sa.Column('nombre', sa.String(100), nullable=False),
        sa.Column('descripcion', sa.Text(), nullable=True),
        sa.Column('es_sistema', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('orden', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('activo', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_roles_id'), 'roles', ['id'], unique=False)
    op.create_index(op.f('ix_roles_codigo'), 'roles', ['codigo'], unique=True)

    # Insertar roles existentes del enum
    op.execute("""
        INSERT INTO roles (codigo, nombre, descripcion, es_sistema, orden) VALUES
        ('SUPERADMIN', 'Super Administrador', 'Acceso completo al sistema', true, 1),
        ('ADMIN', 'Administrador', 'Administración general del sistema', true, 2),
        ('GERENTE', 'Gerente', 'Acceso a reportes y métricas', false, 3),
        ('PRICING', 'Pricing', 'Gestión de precios y productos', false, 4),
        ('VENTAS', 'Ventas', 'Acceso básico a consultas', false, 5)
    """)


def downgrade():
    op.drop_index(op.f('ix_roles_codigo'), table_name='roles')
    op.drop_index(op.f('ix_roles_id'), table_name='roles')
    op.drop_table('roles')
