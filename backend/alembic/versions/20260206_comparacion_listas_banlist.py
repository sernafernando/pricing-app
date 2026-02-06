"""create comparacion_listas_banlist table and permission

Revision ID: 20260206_comp_banlist
Revises: 20260203_duracion_alertas
Create Date: 2026-02-06 10:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '20260206_comp_banlist'
down_revision = '20260203_duracion_alertas'
branch_labels = None
depends_on = None


def upgrade():
    # Crear tabla comparacion_listas_banlist
    op.create_table(
        'comparacion_listas_banlist',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('mla_id', sa.String(50), nullable=False, unique=True, index=True),
        sa.Column('motivo', sa.Text(), nullable=True),
        sa.Column('usuario_id', sa.Integer(), sa.ForeignKey('usuarios.id'), nullable=False),
        sa.Column('fecha_creacion', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # Insertar permiso para gestionar la banlist de comparación
    op.execute("""
        INSERT INTO permisos (codigo, nombre, descripcion, categoria, orden, es_critico, created_at)
        VALUES
            ('admin.gestionar_comparacion_banlist', 'Gestionar banlist de comparación', 'Agregar y quitar items de la banlist de comparación de listas', 'administracion', 62, false, NOW())
        ON CONFLICT (codigo) DO NOTHING;
    """)

    # Mover produccion.marcar_prearmado al orden 63
    op.execute("""
        UPDATE permisos SET orden = 63 WHERE codigo = 'produccion.marcar_prearmado';
    """)

    # Asignar permiso a rol ADMIN
    op.execute("""
        INSERT INTO roles_permisos_base (rol_id, permiso_id)
        SELECT r.id, p.id
        FROM roles r
        CROSS JOIN permisos p
        WHERE r.codigo = 'ADMIN'
        AND p.codigo = 'admin.gestionar_comparacion_banlist'
        ON CONFLICT DO NOTHING;
    """)


def downgrade():
    # Eliminar permiso de roles
    op.execute("""
        DELETE FROM roles_permisos_base
        WHERE permiso_id IN (
            SELECT id FROM permisos
            WHERE codigo = 'admin.gestionar_comparacion_banlist'
        );
    """)

    # Eliminar permiso
    op.execute("""
        DELETE FROM permisos
        WHERE codigo = 'admin.gestionar_comparacion_banlist';
    """)

    # Restaurar orden de produccion.marcar_prearmado
    op.execute("""
        UPDATE permisos SET orden = 62 WHERE codigo = 'produccion.marcar_prearmado';
    """)

    # Eliminar tabla
    op.drop_table('comparacion_listas_banlist')
