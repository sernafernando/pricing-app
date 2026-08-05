"""Add ticket severidad/urgencia/*_origen/texto_original columns (tickets-ai-triage PR 2a)

Adds five nullable columns to `tickets` for AI-assisted triage:
  - severidad / urgencia: the two axes of triage, VARCHAR + CHECK against a
    closed vocabulary — NOT a Postgres ENUM type. You cannot drop a value
    from a PG enum, so downgrade() would be a lie. `Ticket.prioridad` already
    made that mistake with SQLEnum; this migration does not repeat it.
  - severidad_origen / urgencia_origen: who/what set the value
    (humano | ia_confirmada | ia_auto), same VARCHAR + CHECK approach.
  - texto_original: the reporter's verbatim intake text.

NULL in severidad/urgencia means "unclassified" — this migration writes no
data, it only adds the columns. Nothing yet writes to them; a later slice
(triage service + confirmation lifecycle) does.

`Ticket.prioridad` is unchanged: NOT NULL, present in 5 schemas + 2
endpoints, kept for backward compat and deprecated in the UI, never
derived from/to the columns added here (see the `# ponytail:` marker on
the model).

Revision ID: 20260805_ticket_sev_urg_cols
Revises: 20260801_pxq_tier_snapshot
Create Date: 2026-08-05
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "20260805_ticket_sev_urg_cols"
down_revision = "20260801_pxq_tier_snapshot"
branch_labels = None
depends_on = None

_SEVERIDAD_VALUES = ("trivial", "menor", "mayor", "critica")
_URGENCIA_VALUES = ("baja", "normal", "alta", "inmediata")
_ORIGEN_VALUES = ("humano", "ia_confirmada", "ia_auto")


def _in_check(column: str, values: tuple[str, ...]) -> str:
    quoted = ", ".join(f"'{v}'" for v in values)
    return f"{column} IN ({quoted})"


def upgrade() -> None:
    op.add_column("tickets", sa.Column("severidad", sa.String(12), nullable=True))
    op.add_column("tickets", sa.Column("urgencia", sa.String(12), nullable=True))
    op.add_column("tickets", sa.Column("severidad_origen", sa.String(14), nullable=True))
    op.add_column("tickets", sa.Column("urgencia_origen", sa.String(14), nullable=True))
    op.add_column("tickets", sa.Column("texto_original", sa.Text(), nullable=True))

    op.create_check_constraint(
        "ck_tickets_severidad",
        "tickets",
        _in_check("severidad", _SEVERIDAD_VALUES),
    )
    op.create_check_constraint(
        "ck_tickets_urgencia",
        "tickets",
        _in_check("urgencia", _URGENCIA_VALUES),
    )
    op.create_check_constraint(
        "ck_tickets_severidad_origen",
        "tickets",
        _in_check("severidad_origen", _ORIGEN_VALUES),
    )
    op.create_check_constraint(
        "ck_tickets_urgencia_origen",
        "tickets",
        _in_check("urgencia_origen", _ORIGEN_VALUES),
    )

    op.create_index("ix_tickets_severidad", "tickets", ["severidad"])
    op.create_index("ix_tickets_urgencia", "tickets", ["urgencia"])
    op.create_index(
        "ix_tickets_estado_urgencia_created",
        "tickets",
        ["estado_id", "urgencia", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_tickets_estado_urgencia_created", table_name="tickets")
    op.drop_index("ix_tickets_urgencia", table_name="tickets")
    op.drop_index("ix_tickets_severidad", table_name="tickets")

    op.drop_constraint("ck_tickets_urgencia_origen", "tickets", type_="check")
    op.drop_constraint("ck_tickets_severidad_origen", "tickets", type_="check")
    op.drop_constraint("ck_tickets_urgencia", "tickets", type_="check")
    op.drop_constraint("ck_tickets_severidad", "tickets", type_="check")

    op.drop_column("tickets", "texto_original")
    op.drop_column("tickets", "urgencia_origen")
    op.drop_column("tickets", "severidad_origen")
    op.drop_column("tickets", "urgencia")
    op.drop_column("tickets", "severidad")
