"""add rol_id FK to usuarios and roles_permisos_base

Revision ID: 20251216_roles_02
Revises: 20251216_roles_01
Create Date: 2025-12-16

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '20251216_roles_02'
down_revision = '20251216_roles_01'
branch_labels = None
depends_on = None


def upgrade():
    # 1. Agregar columna rol_id a usuarios (nullable temporalmente)
    op.add_column('usuarios', sa.Column('rol_id', sa.Integer(), nullable=True))

    # 2. Migrar datos: convertir enum rol a rol_id
    op.execute("""
        UPDATE usuarios u
        SET rol_id = r.id
        FROM roles r
        WHERE u.rol::text = r.codigo
    """)

    # 3. Hacer rol_id NOT NULL y agregar FK
    op.alter_column('usuarios', 'rol_id', nullable=False)
    op.create_foreign_key(
        'fk_usuarios_rol_id',
        'usuarios', 'roles',
        ['rol_id'], ['id']
    )
    op.create_index(op.f('ix_usuarios_rol_id'), 'usuarios', ['rol_id'], unique=False)

    # 4. Agregar columna rol_id a roles_permisos_base (nullable temporalmente)
    op.add_column('roles_permisos_base', sa.Column('rol_id', sa.Integer(), nullable=True))

    # 5. Migrar datos: convertir string rol a rol_id
    op.execute("""
        UPDATE roles_permisos_base rpb
        SET rol_id = r.id
        FROM roles r
        WHERE rpb.rol = r.codigo
    """)

    # 6. Hacer rol_id NOT NULL y agregar FK
    op.alter_column('roles_permisos_base', 'rol_id', nullable=False)
    op.create_foreign_key(
        'fk_roles_permisos_base_rol_id',
        'roles_permisos_base', 'roles',
        ['rol_id'], ['id'],
        ondelete='CASCADE'
    )
    op.create_index(op.f('ix_roles_permisos_base_rol_id'), 'roles_permisos_base', ['rol_id'], unique=False)

    # 7. Eliminar columna rol antigua de roles_permisos_base
    op.drop_index('ix_roles_permisos_base_rol', table_name='roles_permisos_base')
    op.drop_column('roles_permisos_base', 'rol')

    # Nota: NO eliminamos la columna 'rol' de usuarios aún para mantener compatibilidad
    # Se puede eliminar en una migración futura


def downgrade():
    # Restaurar columna rol en roles_permisos_base
    op.add_column('roles_permisos_base', sa.Column('rol', sa.String(50), nullable=True))

    # Migrar datos de vuelta
    op.execute("""
        UPDATE roles_permisos_base rpb
        SET rol = r.codigo
        FROM roles r
        WHERE rpb.rol_id = r.id
    """)

    op.alter_column('roles_permisos_base', 'rol', nullable=False)
    op.create_index('ix_roles_permisos_base_rol', 'roles_permisos_base', ['rol'], unique=False)

    # Eliminar FK y columna rol_id de roles_permisos_base
    op.drop_index(op.f('ix_roles_permisos_base_rol_id'), table_name='roles_permisos_base')
    op.drop_constraint('fk_roles_permisos_base_rol_id', 'roles_permisos_base', type_='foreignkey')
    op.drop_column('roles_permisos_base', 'rol_id')

    # Eliminar FK y columna rol_id de usuarios
    op.drop_index(op.f('ix_usuarios_rol_id'), table_name='usuarios')
    op.drop_constraint('fk_usuarios_rol_id', 'usuarios', type_='foreignkey')
    op.drop_column('usuarios', 'rol_id')
