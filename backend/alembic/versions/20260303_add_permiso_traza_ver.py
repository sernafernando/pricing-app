"""Agregar permiso traza.ver

Permite acceder al módulo de Traza (consulta unificada de historial
de seriales, facturas, RMAs y casos de seguimiento).
Accesible por varios sectores: ADMIN, GERENTE, PRICING, VENTAS, LOGISTICA.

Revision ID: 20260303_traza_ver
Revises: 20260303_weather
Create Date: 2026-03-03

"""

from alembic import op

revision = "20260303_traza_ver"
down_revision = "20260303_weather"
branch_labels = None
depends_on = None

CODIGO = "traza.ver"


def upgrade():
    # 1. Insertar permiso en catálogo
    op.execute("""
        INSERT INTO permisos (codigo, nombre, descripcion, categoria, orden, es_critico, created_at)
        VALUES
            ('traza.ver',
             'Ver Traza',
             'Acceder al módulo de traza unificada: historial de seriales, facturas, RMAs y casos de seguimiento',
             'consultas', 50, false, NOW())
        ON CONFLICT (codigo) DO NOTHING;
    """)

    # 2. Asignar a ADMIN
    op.execute("""
        INSERT INTO roles_permisos_base (rol_id, permiso_id)
        SELECT r.id, p.id
        FROM roles r
        CROSS JOIN permisos p
        WHERE r.codigo = 'ADMIN'
          AND p.codigo = 'traza.ver'
        ON CONFLICT DO NOTHING;
    """)

    # 3. Asignar a GERENTE
    op.execute("""
        INSERT INTO roles_permisos_base (rol_id, permiso_id)
        SELECT r.id, p.id
        FROM roles r
        CROSS JOIN permisos p
        WHERE r.codigo = 'GERENTE'
          AND p.codigo = 'traza.ver'
        ON CONFLICT DO NOTHING;
    """)

    # 4. Asignar a PRICING
    op.execute("""
        INSERT INTO roles_permisos_base (rol_id, permiso_id)
        SELECT r.id, p.id
        FROM roles r
        CROSS JOIN permisos p
        WHERE r.codigo = 'PRICING'
          AND p.codigo = 'traza.ver'
        ON CONFLICT DO NOTHING;
    """)

    # 5. Asignar a VENTAS
    op.execute("""
        INSERT INTO roles_permisos_base (rol_id, permiso_id)
        SELECT r.id, p.id
        FROM roles r
        CROSS JOIN permisos p
        WHERE r.codigo = 'VENTAS'
          AND p.codigo = 'traza.ver'
        ON CONFLICT DO NOTHING;
    """)

    # 6. Asignar a LOGISTICA
    op.execute("""
        INSERT INTO roles_permisos_base (rol_id, permiso_id)
        SELECT r.id, p.id
        FROM roles r
        CROSS JOIN permisos p
        WHERE r.codigo = 'LOGISTICA'
          AND p.codigo = 'traza.ver'
        ON CONFLICT DO NOTHING;
    """)


def downgrade():
    op.execute("""
        DELETE FROM roles_permisos_base
        WHERE permiso_id IN (
            SELECT id FROM permisos WHERE codigo = 'traza.ver'
        );
    """)

    op.execute("""
        DELETE FROM usuarios_permisos_override
        WHERE permiso_id IN (
            SELECT id FROM permisos WHERE codigo = 'traza.ver'
        );
    """)

    op.execute("""
        DELETE FROM permisos WHERE codigo = 'traza.ver';
    """)
