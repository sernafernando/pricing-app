"""create asignaciones table and permissions for assignment system

Revision ID: 20260210_asignaciones
Revises: 20260206_marcas_pm_cat
Create Date: 2026-02-10 10:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB


# revision identifiers, used by Alembic.
revision = '20260210_asignaciones'
down_revision = '20260206_marcas_pm_cat'
branch_labels = None
depends_on = None


def upgrade():
    # 1. Create asignaciones table
    op.create_table(
        'asignaciones',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('tracking_id', UUID(as_uuid=True), nullable=False, unique=True),
        sa.Column('tipo', sa.String(50), nullable=False),
        sa.Column('referencia_id', sa.Integer(), nullable=False),
        sa.Column('subtipo', sa.String(100), nullable=True),
        sa.Column('usuario_id', sa.Integer(), sa.ForeignKey('usuarios.id'), nullable=False),
        sa.Column('estado', sa.String(20), nullable=False, server_default='pendiente'),
        sa.Column('metadata_asignacion', JSONB(), nullable=True),
        sa.Column('origen', sa.String(20), nullable=False, server_default='manual'),
        sa.Column('fecha_asignacion', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('fecha_resolucion', sa.DateTime(timezone=True), nullable=True),
        sa.Column('notas', sa.Text(), nullable=True),
    )

    # 2. Create indexes
    op.create_index('idx_asignacion_tracking_id', 'asignaciones', ['tracking_id'])
    op.create_index('idx_asignacion_tipo', 'asignaciones', ['tipo'])
    op.create_index('idx_asignacion_referencia_id', 'asignaciones', ['referencia_id'])
    op.create_index('idx_asignacion_subtipo', 'asignaciones', ['subtipo'])
    op.create_index('idx_asignacion_usuario_id', 'asignaciones', ['usuario_id'])
    op.create_index('idx_asignacion_estado', 'asignaciones', ['estado'])
    op.create_index('idx_asignacion_tipo_ref', 'asignaciones', ['tipo', 'referencia_id'])
    op.create_index('idx_asignacion_tipo_ref_subtipo', 'asignaciones', ['tipo', 'referencia_id', 'subtipo'])
    op.create_index('idx_asignacion_usuario_estado', 'asignaciones', ['usuario_id', 'estado'])
    op.create_index('idx_asignacion_tipo_estado', 'asignaciones', ['tipo', 'estado'])

    # 3. Insert new permissions
    op.execute("""
        INSERT INTO permisos (codigo, nombre, descripcion, categoria, orden, es_critico, created_at)
        VALUES
            ('admin.asignar_items_sin_mla', 'Asignarse items sin MLA', 'Auto-asignarse items sin MLA para trabajar en sus publicaciones faltantes', 'administracion', 63, false, NOW()),
            ('admin.gestionar_asignaciones', 'Gestionar asignaciones', 'Asignar/desasignar items sin MLA a cualquier usuario (no solo a uno mismo)', 'administracion', 64, true, NOW())
        ON CONFLICT (codigo) DO NOTHING;
    """)

    # 4. Reorder produccion.marcar_prearmado to make room
    op.execute("""
        UPDATE permisos SET orden = 65 WHERE codigo = 'produccion.marcar_prearmado';
    """)

    # 5. Assign permissions to ADMIN role
    op.execute("""
        INSERT INTO roles_permisos_base (rol_id, permiso_id)
        SELECT r.id, p.id
        FROM roles r
        CROSS JOIN permisos p
        WHERE r.codigo = 'ADMIN'
        AND p.codigo IN ('admin.asignar_items_sin_mla', 'admin.gestionar_asignaciones')
        ON CONFLICT DO NOTHING;
    """)

    # 6. Assign self-assign permission to GERENTE role
    op.execute("""
        INSERT INTO roles_permisos_base (rol_id, permiso_id)
        SELECT r.id, p.id
        FROM roles r
        CROSS JOIN permisos p
        WHERE r.codigo = 'GERENTE'
        AND p.codigo = 'admin.asignar_items_sin_mla'
        ON CONFLICT DO NOTHING;
    """)


def downgrade():
    # Remove role assignments
    op.execute("""
        DELETE FROM roles_permisos_base
        WHERE permiso_id IN (
            SELECT id FROM permisos WHERE codigo IN ('admin.asignar_items_sin_mla', 'admin.gestionar_asignaciones')
        );
    """)

    # Remove permissions
    op.execute("""
        DELETE FROM permisos WHERE codigo IN ('admin.asignar_items_sin_mla', 'admin.gestionar_asignaciones');
    """)

    # Restore produccion.marcar_prearmado order
    op.execute("""
        UPDATE permisos SET orden = 63 WHERE codigo = 'produccion.marcar_prearmado';
    """)

    # Drop indexes
    op.drop_index('idx_asignacion_tipo_estado', table_name='asignaciones')
    op.drop_index('idx_asignacion_usuario_estado', table_name='asignaciones')
    op.drop_index('idx_asignacion_tipo_ref_subtipo', table_name='asignaciones')
    op.drop_index('idx_asignacion_tipo_ref', table_name='asignaciones')
    op.drop_index('idx_asignacion_estado', table_name='asignaciones')
    op.drop_index('idx_asignacion_usuario_id', table_name='asignaciones')
    op.drop_index('idx_asignacion_subtipo', table_name='asignaciones')
    op.drop_index('idx_asignacion_referencia_id', table_name='asignaciones')
    op.drop_index('idx_asignacion_tipo', table_name='asignaciones')
    op.drop_index('idx_asignacion_tracking_id', table_name='asignaciones')

    # Drop table
    op.drop_table('asignaciones')
