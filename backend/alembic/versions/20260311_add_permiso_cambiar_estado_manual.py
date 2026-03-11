"""Add envios_flex.cambiar_estado_manual permission

Separate the ability to change ML status on manual shipments from
envios_flex.config (which is a critical admin permission).  Depot
operators who manage manual shipments need this action without
requiring full config access.

Revision ID: 20260311_estado_manual_perm
Revises: 20260311_item_trx_serials
Create Date: 2026-03-11

"""

from alembic import op

revision = "20260311_estado_manual_perm"
down_revision = "20260311_item_trx_serials"
branch_labels = None
depends_on = None

CODIGO = "envios_flex.cambiar_estado_manual"


def upgrade():
    # 1. Insert permission into catalog
    op.execute("""
        INSERT INTO permisos (codigo, nombre, descripcion, categoria, orden, es_critico, created_at)
        VALUES (
            'envios_flex.cambiar_estado_manual',
            'Cambiar estado ML de envíos manuales',
            'Cambiar el estado ML (listo/enviado/entregado) de envíos manuales',
            'envios_flex',
            112,
            false,
            NOW()
        )
        ON CONFLICT (codigo) DO NOTHING;
    """)

    # 2. Assign to ADMIN role (has envios_flex.* but explicit is safer)
    op.execute("""
        INSERT INTO roles_permisos_base (rol_id, permiso_id)
        SELECT r.id, p.id
        FROM roles r
        CROSS JOIN permisos p
        WHERE r.codigo = 'ADMIN'
          AND p.codigo = 'envios_flex.cambiar_estado_manual'
        ON CONFLICT DO NOTHING;
    """)


def downgrade():
    op.execute("""
        DELETE FROM roles_permisos_base
        WHERE permiso_id IN (
            SELECT id FROM permisos WHERE codigo = 'envios_flex.cambiar_estado_manual'
        );
    """)

    op.execute("""
        DELETE FROM usuarios_permisos_override
        WHERE permiso_id IN (
            SELECT id FROM permisos WHERE codigo = 'envios_flex.cambiar_estado_manual'
        );
    """)

    op.execute("""
        DELETE FROM permisos WHERE codigo = 'envios_flex.cambiar_estado_manual';
    """)
