"""Add tickets.triage.confirmar permission (tickets-ai-triage PR 4b)

Seeds `tickets.triage.confirmar`, granted DYNAMICALLY (via join, not a
hardcoded role list) to every role that currently holds `tickets.gestionar`.
Deliberately NOT reusing `tickets.gestionar` itself — that bundles state
changes, assignment, workflow edits, attachment deletion and internal
comments (design §9b); confirming an AI proposal is a narrower judgment.

The future service role `AGENTE_IA` (slice 6) doesn't exist yet here —
slice 6's own migration must grant it this permission too.

Revision ID: 20260806_triage_confirmar
Revises: 20260805_seed_inbox
Create Date: 2026-08-06
"""

from alembic import op

revision = "20260806_triage_confirmar"
down_revision = "20260805_seed_inbox"
branch_labels = None
depends_on = None

PERMISO_CODIGO = "tickets.triage.confirmar"


def upgrade() -> None:
    op.execute(f"""
        INSERT INTO permisos (codigo, nombre, descripcion, categoria, orden, es_critico, created_at)
        VALUES (
            '{PERMISO_CODIGO}',
            'Confirmar propuestas de IA',
            'Confirmar o descartar clasificaciones de severidad/urgencia propuestas por IA en tickets',
            'tickets',
            134,
            false,
            NOW()
        )
        ON CONFLICT (codigo) DO NOTHING;
    """)

    # Dynamic grant: every role currently holding tickets.gestionar also
    # gets tickets.triage.confirmar, computed via a join rather than a
    # hardcoded role list.
    op.execute(f"""
        INSERT INTO roles_permisos_base (rol_id, permiso_id)
        SELECT DISTINCT rpb.rol_id, p_nuevo.id
        FROM roles_permisos_base rpb
        JOIN permisos p_gestionar ON p_gestionar.id = rpb.permiso_id AND p_gestionar.codigo = 'tickets.gestionar'
        CROSS JOIN permisos p_nuevo
        WHERE p_nuevo.codigo = '{PERMISO_CODIGO}'
        ON CONFLICT DO NOTHING;
    """)


def downgrade() -> None:
    op.execute(f"""
        DELETE FROM roles_permisos_base
        WHERE permiso_id IN (SELECT id FROM permisos WHERE codigo = '{PERMISO_CODIGO}');
    """)
    op.execute(f"""
        DELETE FROM usuarios_permisos_override
        WHERE permiso_id IN (SELECT id FROM permisos WHERE codigo = '{PERMISO_CODIGO}');
    """)
    op.execute(f"DELETE FROM permisos WHERE codigo = '{PERMISO_CODIGO}';")
