"""Agregar permiso reportes.recibir_notificaciones_markup

Controla qué usuarios reciben notificaciones automáticas de markup bajo.
Antes se enviaban a TODOS los usuarios activos (incluyendo depósito).
Ahora solo a quienes tengan este permiso: ADMIN, GERENTE y PRICING.

Revision ID: 20260225_notif_markup
Revises: 20260224_crear_envio
Create Date: 2026-02-25

"""

from alembic import op

revision = "20260225_notif_markup"
down_revision = "20260224_crear_envio"
branch_labels = None
depends_on = None

CODIGO = "reportes.recibir_notificaciones_markup"


def upgrade():
    # 1. Insertar permiso en catálogo
    op.execute("""
        INSERT INTO permisos (codigo, nombre, descripcion, categoria, orden, es_critico, created_at)
        VALUES
            ('reportes.recibir_notificaciones_markup',
             'Recibir notificaciones de markup',
             'Recibir notificaciones automáticas cuando una venta tiene markup negativo o por debajo del esperado',
             'reportes', 42, false, NOW())
        ON CONFLICT (codigo) DO NOTHING;
    """)

    # 2. Asignar a ADMIN
    op.execute("""
        INSERT INTO roles_permisos_base (rol_id, permiso_id)
        SELECT r.id, p.id
        FROM roles r
        CROSS JOIN permisos p
        WHERE r.codigo = 'ADMIN'
          AND p.codigo = 'reportes.recibir_notificaciones_markup'
        ON CONFLICT DO NOTHING;
    """)

    # 3. Asignar a GERENTE
    op.execute("""
        INSERT INTO roles_permisos_base (rol_id, permiso_id)
        SELECT r.id, p.id
        FROM roles r
        CROSS JOIN permisos p
        WHERE r.codigo = 'GERENTE'
          AND p.codigo = 'reportes.recibir_notificaciones_markup'
        ON CONFLICT DO NOTHING;
    """)

    # 4. Asignar a PRICING
    op.execute("""
        INSERT INTO roles_permisos_base (rol_id, permiso_id)
        SELECT r.id, p.id
        FROM roles r
        CROSS JOIN permisos p
        WHERE r.codigo = 'PRICING'
          AND p.codigo = 'reportes.recibir_notificaciones_markup'
        ON CONFLICT DO NOTHING;
    """)


def downgrade():
    op.execute("""
        DELETE FROM roles_permisos_base
        WHERE permiso_id IN (
            SELECT id FROM permisos WHERE codigo = 'reportes.recibir_notificaciones_markup'
        );
    """)

    op.execute("""
        DELETE FROM usuarios_permisos_override
        WHERE permiso_id IN (
            SELECT id FROM permisos WHERE codigo = 'reportes.recibir_notificaciones_markup'
        );
    """)

    op.execute("""
        DELETE FROM permisos WHERE codigo = 'reportes.recibir_notificaciones_markup';
    """)
