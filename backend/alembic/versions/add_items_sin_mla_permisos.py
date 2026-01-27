"""add items sin mla permisos

Revision ID: add_items_sin_mla_permisos
Revises: 20260123_exportar_pvp
Create Date: 2026-01-27 10:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'add_items_sin_mla_permisos'
down_revision = '20260123_exportar_pvp'
branch_labels = None
depends_on = None


def upgrade():
    # Insertar los 3 nuevos permisos
    op.execute("""
        INSERT INTO permisos (codigo, nombre, descripcion, categoria, orden, es_critico, created_at)
        VALUES 
            ('admin.ver_items_sin_mla', 'Ver items sin MLA', 'Ver listado de items que no tienen MLA asociado', 'administracion', 59, false, NOW()),
            ('admin.gestionar_items_sin_mla_banlist', 'Gestionar banlist de items sin MLA', 'Agregar y quitar items de la banlist de items sin MLA', 'administracion', 60, false, NOW()),
            ('admin.ver_comparacion_listas_ml', 'Ver comparación listas vs ML', 'Ver comparación entre listas de precios y publicaciones ML', 'administracion', 61, false, NOW())
        ON CONFLICT (codigo) DO NOTHING;
    """)
    
    # Actualizar orden de permisos existentes (produccion.marcar_prearmado)
    op.execute("""
        UPDATE permisos SET orden = 62 WHERE codigo = 'produccion.marcar_prearmado';
    """)
    
    # Actualizar orden de permisos de configuración
    op.execute("""
        UPDATE permisos SET orden = 70 WHERE codigo = 'config.ver_comisiones';
        UPDATE permisos SET orden = 71 WHERE codigo = 'config.editar_comisiones';
        UPDATE permisos SET orden = 72 WHERE codigo = 'config.ver_constantes';
        UPDATE permisos SET orden = 73 WHERE codigo = 'config.editar_constantes';
        UPDATE permisos SET orden = 74 WHERE codigo = 'config.ver_tipo_cambio';
    """)
    
    # Actualizar orden de permisos de clientes
    op.execute("""
        UPDATE permisos SET orden = 80 WHERE codigo = 'clientes.ver';
        UPDATE permisos SET orden = 81 WHERE codigo = 'clientes.exportar';
    """)
    
    # Asignar permisos a rol ADMIN
    op.execute("""
        INSERT INTO roles_permisos_base (rol_id, permiso_id)
        SELECT r.id, p.id
        FROM roles r
        CROSS JOIN permisos p
        WHERE r.codigo = 'ADMIN'
        AND p.codigo IN (
            'admin.ver_items_sin_mla',
            'admin.gestionar_items_sin_mla_banlist',
            'admin.ver_comparacion_listas_ml'
        )
        ON CONFLICT DO NOTHING;
    """)
    
    # Asignar permisos de solo lectura a rol GERENTE
    op.execute("""
        INSERT INTO roles_permisos_base (rol_id, permiso_id)
        SELECT r.id, p.id
        FROM roles r
        CROSS JOIN permisos p
        WHERE r.codigo = 'GERENTE'
        AND p.codigo IN (
            'admin.ver_items_sin_mla',
            'admin.ver_comparacion_listas_ml'
        )
        ON CONFLICT DO NOTHING;
    """)


def downgrade():
    # Eliminar permisos de roles
    op.execute("""
        DELETE FROM roles_permisos_base
        WHERE permiso_id IN (
            SELECT id FROM permisos
            WHERE codigo IN (
                'admin.ver_items_sin_mla',
                'admin.gestionar_items_sin_mla_banlist',
                'admin.ver_comparacion_listas_ml'
            )
        );
    """)
    
    # Eliminar permisos
    op.execute("""
        DELETE FROM permisos
        WHERE codigo IN (
            'admin.ver_items_sin_mla',
            'admin.gestionar_items_sin_mla_banlist',
            'admin.ver_comparacion_listas_ml'
        );
    """)
    
    # Revertir orden de permisos (opcional)
    op.execute("""
        UPDATE permisos SET orden = 59 WHERE codigo = 'produccion.marcar_prearmado';
    """)
