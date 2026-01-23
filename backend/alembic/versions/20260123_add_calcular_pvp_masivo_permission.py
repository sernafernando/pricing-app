"""add productos.calcular_pvp_masivo permission

Revision ID: 20260123_pvp_masivo
Revises: merge_heads_20251222
Create Date: 2026-01-23

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '20260123_pvp_masivo'
down_revision = 'merge_heads_20251222'
branch_labels = None
depends_on = None


def upgrade():
    # Insertar nuevo permiso
    op.execute("""
        INSERT INTO permisos (codigo, nombre, descripcion, categoria, orden, es_critico)
        VALUES (
            'productos.calcular_pvp_masivo',
            'Cálculo PVP masivo',
            'Ejecutar cálculo masivo de precios PVP (clásica + cuotas) con goal-seek',
            'productos',
            38,
            true
        )
        ON CONFLICT (codigo) DO NOTHING
    """)

    # Asignar permiso a rol ADMIN (solo si no existe)
    op.execute("""
        INSERT INTO roles_permisos_base (rol_id, permiso_id)
        SELECT r.id, p.id
        FROM roles r, permisos p
        WHERE r.codigo = 'ADMIN'
        AND p.codigo = 'productos.calcular_pvp_masivo'
        AND NOT EXISTS (
            SELECT 1 FROM roles_permisos_base rpb
            WHERE rpb.rol_id = r.id AND rpb.permiso_id = p.id
        )
    """)

    # Asignar permiso a rol VENTAS (solo si no existe)
    op.execute("""
        INSERT INTO roles_permisos_base (rol_id, permiso_id)
        SELECT r.id, p.id
        FROM roles r, permisos p
        WHERE r.codigo = 'VENTAS'
        AND p.codigo = 'productos.calcular_pvp_masivo'
        AND NOT EXISTS (
            SELECT 1 FROM roles_permisos_base rpb
            WHERE rpb.rol_id = r.id AND rpb.permiso_id = p.id
        )
    """)


def downgrade():
    # Eliminar permiso de roles
    op.execute("""
        DELETE FROM roles_permisos_base
        WHERE permiso_id IN (
            SELECT id FROM permisos WHERE codigo = 'productos.calcular_pvp_masivo'
        )
    """)

    # Eliminar permiso
    op.execute("""
        DELETE FROM permisos WHERE codigo = 'productos.calcular_pvp_masivo'
    """)
