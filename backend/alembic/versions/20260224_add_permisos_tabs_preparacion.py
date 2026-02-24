"""Agregar permisos individuales para tabs de Preparación

3 nuevos permisos para controlar acceso granular a cada pestaña:
- produccion.ver_preparacion (tab Preparación)
- pedidos.ver_pendientes (tab Pedidos Pendientes)
- envios_flex.ver_codigos_postales (tab Códigos Postales)

Revision ID: 20260224_permisos_tabs
Revises: 20260224_bultos
Create Date: 2026-02-24

"""

from alembic import op

revision = "20260224_permisos_tabs"
down_revision = "20260224_bultos"
branch_labels = None
depends_on = None

CODIGOS = [
    "produccion.ver_preparacion",
    "pedidos.ver_pendientes",
    "envios_flex.ver_codigos_postales",
]


def upgrade():
    # 1. Insertar los 3 permisos nuevos
    op.execute("""
        INSERT INTO permisos (codigo, nombre, descripcion, categoria, orden, es_critico, created_at)
        VALUES
            ('produccion.ver_preparacion', 'Ver tab Preparación', 'Acceso a la pestaña Preparación (resumen de productos a preparar)', 'productos', 66, false, NOW()),
            ('pedidos.ver_pendientes', 'Ver tab Pedidos Pendientes', 'Acceso a la pestaña Pedidos Pendientes (exportar pedidos a logísticas)', 'productos', 67, false, NOW()),
            ('envios_flex.ver_codigos_postales', 'Ver tab Códigos Postales', 'Acceso a la pestaña Códigos Postales (gestión de CP y cordones)', 'envios_flex', 108, false, NOW())
        ON CONFLICT (codigo) DO NOTHING;
    """)

    # 2. ADMIN: los 3 permisos nuevos
    op.execute("""
        INSERT INTO roles_permisos_base (rol_id, permiso_id)
        SELECT r.id, p.id
        FROM roles r
        CROSS JOIN permisos p
        WHERE r.codigo = 'ADMIN'
          AND p.codigo IN ('produccion.ver_preparacion', 'pedidos.ver_pendientes', 'envios_flex.ver_codigos_postales')
        ON CONFLICT DO NOTHING;
    """)

    # 3. GERENTE: los 3 permisos (puede ver todo)
    op.execute("""
        INSERT INTO roles_permisos_base (rol_id, permiso_id)
        SELECT r.id, p.id
        FROM roles r
        CROSS JOIN permisos p
        WHERE r.codigo = 'GERENTE'
          AND p.codigo IN ('produccion.ver_preparacion', 'pedidos.ver_pendientes', 'envios_flex.ver_codigos_postales')
        ON CONFLICT DO NOTHING;
    """)

    # 4. VENTAS: solo pedidos pendientes (necesitan ver sus pedidos)
    op.execute("""
        INSERT INTO roles_permisos_base (rol_id, permiso_id)
        SELECT r.id, p.id
        FROM roles r
        CROSS JOIN permisos p
        WHERE r.codigo = 'VENTAS'
          AND p.codigo = 'pedidos.ver_pendientes'
        ON CONFLICT DO NOTHING;
    """)


def downgrade():
    # Limpiar asignaciones de rol
    op.execute("""
        DELETE FROM roles_permisos_base
        WHERE permiso_id IN (
            SELECT id FROM permisos
            WHERE codigo IN ('produccion.ver_preparacion', 'pedidos.ver_pendientes', 'envios_flex.ver_codigos_postales')
        );
    """)

    # Limpiar overrides de usuario (si hay)
    op.execute("""
        DELETE FROM usuarios_permisos_override
        WHERE permiso_id IN (
            SELECT id FROM permisos
            WHERE codigo IN ('produccion.ver_preparacion', 'pedidos.ver_pendientes', 'envios_flex.ver_codigos_postales')
        );
    """)

    # Eliminar permisos
    op.execute("""
        DELETE FROM permisos
        WHERE codigo IN ('produccion.ver_preparacion', 'pedidos.ver_pendientes', 'envios_flex.ver_codigos_postales');
    """)
