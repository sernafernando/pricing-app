"""Agregar permiso consultas.ver_mi_ranking (scoped ranking access)

Revision ID: 20260601_02_consultas_ver_mi_ranking_permiso
Revises: 20260601_01_stock_por_deposito
Create Date: 2026-06-01

Inserta el permiso ``consultas.ver_mi_ranking`` que otorga acceso a la misma
vista de ranking de productos pero restringida a las marcas/categorías asignadas
al propio PM (filas donde ``marcas_pm.usuario_id = current_user.id``).

Precedencia:
  - Si el usuario tiene ``consultas.ver_ranking`` (o es SUPERADMIN) → acceso FULL.
  - Si tiene SOLO ``consultas.ver_mi_ranking`` → acceso SCOPED (solo sus marcas/categorías).
  - Si no tiene ninguno → 403.

NO se asigna a ningún rol por defecto — se debe conceder manualmente como
override por usuario (``usuarios_permisos_override.concedido = true``).
"""

from alembic import op

revision = "20260601_02_consultas_ver_mi_ranking_permiso"
down_revision = "20260601_01_stock_por_deposito"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        INSERT INTO permisos (codigo, nombre, descripcion, categoria, orden, es_critico, created_at)
        VALUES (
            'consultas.ver_mi_ranking',
            'Ver mi ranking de productos',
            'Acceso al ranking de productos restringido a las marcas/categorías propias del PM (marcas_pm.usuario_id = usuario actual). Requiere consultas.ver_ranking para acceso completo sin restricción.',
            'consultas',
            101,
            false,
            NOW()
        )
        ON CONFLICT (codigo) DO NOTHING;
    """)
    # No se asigna a ningún rol — es un permiso individual (override por usuario).


def downgrade() -> None:
    # 1. Limpiar overrides de usuario
    op.execute("""
        DELETE FROM usuarios_permisos_override
        WHERE permiso_id IN (
            SELECT id FROM permisos WHERE codigo = 'consultas.ver_mi_ranking'
        );
    """)

    # 2. Limpiar asignaciones de rol (por si se asignó manualmente)
    op.execute("""
        DELETE FROM roles_permisos_base
        WHERE permiso_id IN (
            SELECT id FROM permisos WHERE codigo = 'consultas.ver_mi_ranking'
        );
    """)

    # 3. Eliminar el permiso
    op.execute("""
        DELETE FROM permisos WHERE codigo = 'consultas.ver_mi_ranking';
    """)
