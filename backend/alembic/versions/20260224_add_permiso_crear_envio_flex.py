"""Agregar permiso pedidos.crear_envio_flex

Permiso específico para crear envíos flex desde Pedidos Pendientes,
separado de envios_flex.subir_etiquetas que es para el tab de Envíos Flex.

Revision ID: 20260224_crear_envio
Revises: 20260224_permisos_tabs
Create Date: 2026-02-24

"""

from alembic import op

revision = "20260224_crear_envio"
down_revision = "20260224_permisos_tabs"
branch_labels = None
depends_on = None

CODIGO = "pedidos.crear_envio_flex"


def upgrade():
    # 1. Insertar permiso
    op.execute("""
        INSERT INTO permisos (codigo, nombre, descripcion, categoria, orden, es_critico, created_at)
        VALUES
            ('pedidos.crear_envio_flex', 'Crear envío flex desde Pedidos', 'Crear envíos flex manuales desde la pestaña Pedidos Pendientes', 'productos', 68, false, NOW())
        ON CONFLICT (codigo) DO NOTHING;
    """)

    # 2. ADMIN
    op.execute("""
        INSERT INTO roles_permisos_base (rol_id, permiso_id)
        SELECT r.id, p.id
        FROM roles r
        CROSS JOIN permisos p
        WHERE r.codigo = 'ADMIN'
          AND p.codigo = 'pedidos.crear_envio_flex'
        ON CONFLICT DO NOTHING;
    """)

    # 3. GERENTE
    op.execute("""
        INSERT INTO roles_permisos_base (rol_id, permiso_id)
        SELECT r.id, p.id
        FROM roles r
        CROSS JOIN permisos p
        WHERE r.codigo = 'GERENTE'
          AND p.codigo = 'pedidos.crear_envio_flex'
        ON CONFLICT DO NOTHING;
    """)

    # 4. VENTAS
    op.execute("""
        INSERT INTO roles_permisos_base (rol_id, permiso_id)
        SELECT r.id, p.id
        FROM roles r
        CROSS JOIN permisos p
        WHERE r.codigo = 'VENTAS'
          AND p.codigo = 'pedidos.crear_envio_flex'
        ON CONFLICT DO NOTHING;
    """)


def downgrade():
    op.execute("""
        DELETE FROM roles_permisos_base
        WHERE permiso_id IN (
            SELECT id FROM permisos WHERE codigo = 'pedidos.crear_envio_flex'
        );
    """)

    op.execute("""
        DELETE FROM usuarios_permisos_override
        WHERE permiso_id IN (
            SELECT id FROM permisos WHERE codigo = 'pedidos.crear_envio_flex'
        );
    """)

    op.execute("""
        DELETE FROM permisos WHERE codigo = 'pedidos.crear_envio_flex';
    """)
