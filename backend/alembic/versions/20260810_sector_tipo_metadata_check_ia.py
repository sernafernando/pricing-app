"""Extend campo CHECK constraint on tickets_propuestas_ia with
sector/tipo_ticket/metadata_ia (tickets-ai-triage: give the Inbox an exit)

The Inbox seeded by 20260805_seed_inbox_sector_and_workflow.py never had an
exit: nothing moved a ticket's `sector_id`/`tipo_ticket_id` out of it. This
slice teaches triage to propose a real `sector_codigo`/`tipo_ticket_codigo`
from the configured catalogue, and lets a human confirm it via the SAME
`tickets_propuestas_ia` mechanism `severidad`/`urgencia`/`titulo`/`resumen`
already use (PR 4b) — so the CHECK constraint's vocabulary
(`ck_tickets_propuestas_ia_campo`, added by 20260806_campo_check_ia.py) must
grow to match `confirmacion_service.CAMPOS_CONFIRMABLES`, or every INSERT
for these new campos fails at the DB layer. `metadata_ia` carries
`area_probable`/`tamano`/`detalle` as one JSONB blob, merged into
`Ticket.campos_metadata` on confirmation rather than new columns.

Same VARCHAR + CHECK rationale as the constraint being replaced: dropping a
value from a Postgres enum type is impossible, so an ENUM's downgrade()
would be a lie.

Revision ID: 20260810_sector_tipo_check_ia
Revises: 20260807_seed_agente_ia
Create Date: 2026-08-10
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "20260810_sector_tipo_check_ia"
down_revision = "20260807_seed_agente_ia"
branch_labels = None
depends_on = None

_CONSTRAINT_NAME = "ck_tickets_propuestas_ia_campo"
_OLD_VALUES = ("severidad", "urgencia", "titulo", "resumen")
_NEW_VALUES = _OLD_VALUES + ("sector", "tipo_ticket", "metadata_ia")


def upgrade() -> None:
    op.drop_constraint(_CONSTRAINT_NAME, "tickets_propuestas_ia", type_="check")
    op.create_check_constraint(
        _CONSTRAINT_NAME,
        "tickets_propuestas_ia",
        "campo IN (" + ", ".join(f"'{v}'" for v in _NEW_VALUES) + ")",
    )


def downgrade() -> None:
    # Real pre-push review finding: re-creating the OLD constraint while a
    # row still uses 'sector'/'tipo_ticket'/'metadata_ia' (the normal case
    # after even one triage run) would fail with a raw CheckViolation —
    # same "refuse loudly rather than fail cryptically or corrupt data"
    # convention as 20260805_seed_inbox_sector_and_workflow.py's downgrade.
    bind = op.get_bind()
    nuevos = ("sector", "tipo_ticket", "metadata_ia")
    count = bind.execute(
        sa.text("SELECT COUNT(*) FROM tickets_propuestas_ia WHERE campo IN :campos").bindparams(
            sa.bindparam("campos", expanding=True)
        ),
        {"campos": nuevos},
    ).scalar_one()
    if count:
        raise RuntimeError(
            f"Cannot downgrade 20260810_sector_tipo_check_ia: {count} tickets_propuestas_ia row(s) still use "
            f"campo IN {nuevos}. Reassign or delete them first — the old CHECK constraint would otherwise "
            f"reject them, and silently deleting AI proposal history on downgrade is worse than refusing."
        )
    op.drop_constraint(_CONSTRAINT_NAME, "tickets_propuestas_ia", type_="check")
    op.create_check_constraint(
        _CONSTRAINT_NAME,
        "tickets_propuestas_ia",
        "campo IN (" + ", ".join(f"'{v}'" for v in _OLD_VALUES) + ")",
    )
