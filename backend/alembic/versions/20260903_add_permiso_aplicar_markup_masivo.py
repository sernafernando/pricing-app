"""Agregar permiso productos.aplicar_markup_masivo

Revision ID: 20260903_markup_masivo
Revises: 20260708_ml_bot_defs
Create Date: 2026-09-03

"""

from alembic import op

revision = "20260903_markup_masivo"
down_revision = "20260708_ml_bot_defs"
branch_labels = None
depends_on = None

CODIGO = "productos.aplicar_markup_masivo"


def upgrade() -> None:
    op.execute("""
        INSERT INTO permisos (codigo, nombre, descripcion, categoria, orden, es_critico, created_at)
        VALUES (
            'productos.aplicar_markup_masivo',
            'Acciones masivas de markup',
            'Aplicar markup objetivo ML Clásica y/o config de cuotas sobre productos visibles',
            'productos',
            39,
            true,
            NOW()
        )
        ON CONFLICT (codigo) DO NOTHING;
    """)

    op.execute("""
        INSERT INTO roles_permisos_base (rol_id, permiso_id)
        SELECT r.id, p.id
        FROM roles r
        CROSS JOIN permisos p
        WHERE r.codigo IN ('ADMIN', 'PRICING')
          AND p.codigo = 'productos.aplicar_markup_masivo'
        ON CONFLICT DO NOTHING;
    """)


def downgrade() -> None:
    op.execute("""
        DELETE FROM roles_permisos_base
        WHERE permiso_id IN (
            SELECT id FROM permisos WHERE codigo = 'productos.aplicar_markup_masivo'
        );
    """)
    op.execute("""
        DELETE FROM usuarios_permisos_override
        WHERE permiso_id IN (
            SELECT id FROM permisos WHERE codigo = 'productos.aplicar_markup_masivo'
        );
    """)
    op.execute("""
        DELETE FROM permisos WHERE codigo = 'productos.aplicar_markup_masivo';
    """)
