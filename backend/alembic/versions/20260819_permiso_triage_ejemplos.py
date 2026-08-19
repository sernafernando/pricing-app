"""Add tickets.triage.ejemplos permission (tickets-triage-feedback PR5a)

Seeds `tickets.triage.ejemplos`, DELIBERATELY INDEPENDENT from
`tickets.triage.confirmar` — curating the few-shot correction corpus
(listing/toggling captured `EjemploCorreccion` rows) is a narrower judgment
than confirming AI triage proposals, so a user holding one permission must
not get the other for free (mirrors `20260806_add_permiso_triage_confirmar.py`'s
own rationale for splitting out of `tickets.gestionar`).

Granted DYNAMICALLY (via join, not a hardcoded role list) to every role that
currently holds `tickets.triage.confirmar` — a reasonable default starting
population; per-role curation access can be tightened later via the
permissions panel without another migration.

Chains on `20260819_ejemplos_usados` (PR4b, #1157). Both slices were authored
off the same `20260818_pxq_tier_costo_envio_fetched_at` head while PR4b was
still open; this branch was rebased onto main afterwards and re-pointed here,
so the graph stays a single chain instead of two divergent alembic heads.

Revision ID: 20260819_triage_ejemplos_permiso
Revises: 20260819_ejemplos_usados
Create Date: 2026-08-19
"""

from typing import Sequence, Union

from alembic import op

revision: str = "20260819_triage_ejemplos_permiso"
down_revision: Union[str, None] = "20260819_ejemplos_usados"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

PERMISO_CODIGO = "tickets.triage.ejemplos"


def upgrade() -> None:
    op.execute(f"""
        INSERT INTO permisos (codigo, nombre, descripcion, categoria, orden, es_critico, created_at)
        VALUES (
            '{PERMISO_CODIGO}',
            'Curar ejemplos de correcciones IA',
            'Listar y activar/desactivar ejemplos capturados de correcciones humanas usados en el few-shot de triage IA',
            'tickets',
            135,
            false,
            NOW()
        )
        ON CONFLICT (codigo) DO NOTHING;
    """)

    # Dynamic grant: every role currently holding tickets.triage.confirmar
    # also gets tickets.triage.ejemplos, computed via a join rather than a
    # hardcoded role list.
    op.execute(f"""
        INSERT INTO roles_permisos_base (rol_id, permiso_id)
        SELECT DISTINCT rpb.rol_id, p_nuevo.id
        FROM roles_permisos_base rpb
        JOIN permisos p_confirmar ON p_confirmar.id = rpb.permiso_id AND p_confirmar.codigo = 'tickets.triage.confirmar'
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
        DELETE FROM permisos WHERE codigo = '{PERMISO_CODIGO}';
    """)
