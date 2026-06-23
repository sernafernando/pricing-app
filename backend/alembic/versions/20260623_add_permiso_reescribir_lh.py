"""Agregar permiso etiquetas.reescribir_lh para roles DEPO y ADMIN

Revision ID: 20260623_permiso_reescribir_lh
Revises: 20260622_cheques_banco_deposito
Create Date: 2026-06-23

"""

from alembic import op

revision = "20260623_permiso_reescribir_lh"
down_revision = "20260622_cheques_banco_deposito"
branch_labels = None
depends_on = None

CODIGO = "etiquetas.reescribir_lh"


def upgrade() -> None:
    # 1. Insert the new permission
    op.execute("""
        INSERT INTO permisos (codigo, nombre, descripcion, categoria, orden, es_critico, created_at)
        VALUES (
            'etiquetas.reescribir_lh',
            'Reescribir ^LH de etiquetas',
            'Corregir el offset vertical (^LH y) de etiquetas ZPL de Mercado Libre',
            'etiquetas',
            200,
            false,
            NOW()
        )
        ON CONFLICT (codigo) DO NOTHING;
    """)

    # 2. Assign to DEPO role
    op.execute("""
        INSERT INTO roles_permisos_base (rol_id, permiso_id)
        SELECT r.id, p.id
        FROM roles r
        CROSS JOIN permisos p
        WHERE r.codigo = 'DEPO'
          AND p.codigo = 'etiquetas.reescribir_lh'
        ON CONFLICT DO NOTHING;
    """)

    # 3. Assign to ADMIN role (explicit — ADMIN is not implicit)
    op.execute("""
        INSERT INTO roles_permisos_base (rol_id, permiso_id)
        SELECT r.id, p.id
        FROM roles r
        CROSS JOIN permisos p
        WHERE r.codigo = 'ADMIN'
          AND p.codigo = 'etiquetas.reescribir_lh'
        ON CONFLICT DO NOTHING;
    """)


def downgrade() -> None:
    # Remove role assignments
    op.execute("""
        DELETE FROM roles_permisos_base
        WHERE permiso_id IN (
            SELECT id FROM permisos WHERE codigo = 'etiquetas.reescribir_lh'
        );
    """)

    # Remove user-level overrides
    op.execute("""
        DELETE FROM usuarios_permisos_override
        WHERE permiso_id IN (
            SELECT id FROM permisos WHERE codigo = 'etiquetas.reescribir_lh'
        );
    """)

    # Remove the permission itself
    op.execute("""
        DELETE FROM permisos WHERE codigo = 'etiquetas.reescribir_lh';
    """)
