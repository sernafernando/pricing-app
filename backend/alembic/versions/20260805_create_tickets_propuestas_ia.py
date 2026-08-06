"""Create tickets_propuestas_ia table (tickets-ai-triage PR 2b)

Side table for AI-generated ticket field proposals. A proposal never
writes to `tickets` — a human (or, later, an auto-apply flag) confirms it
via a dedicated confirmation service (PR 4b), the only code path allowed
to write `tickets.<campo>`.

`estado` is VARCHAR + CHECK against a closed vocabulary
(pendiente|confirmada|descartada|reemplazada), NOT a Postgres ENUM type —
you cannot drop a value from a PG enum, so downgrade() would be a lie.
Same rationale as `Ticket.severidad`/`Ticket.urgencia` (PR 2a).

The partial unique index `(ticket_id, campo) WHERE estado='pendiente'`
allows at most one pending proposal per ticket field at a time, while
still letting a fresh triage run write a new pendiente row once the prior
one is confirmada/descartada/reemplazada — a plain unique constraint
would wrongly block that. Postgres-only DDL (`WHERE` clause on a unique
index); covered by @pytest.mark.postgres tests.

Revision ID: 20260805_propuestas_ia
Revises: 20260805_ticket_sev_urg_cols
Create Date: 2026-08-05
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "20260805_propuestas_ia"
down_revision = "20260805_ticket_sev_urg_cols"
branch_labels = None
depends_on = None

_ESTADO_VALUES = ("pendiente", "confirmada", "descartada", "reemplazada")
_UNIQUE_PENDIENTE_INDEX = "uq_tickets_propuestas_ia_ticket_campo_pendiente"


def upgrade() -> None:
    op.create_table(
        "tickets_propuestas_ia",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("ticket_id", sa.Integer(), sa.ForeignKey("tickets.id"), nullable=False),
        sa.Column("campo", sa.String(50), nullable=False),
        sa.Column("valor_propuesto", postgresql.JSONB(), nullable=False),
        sa.Column("confianza", sa.Numeric(3, 2), nullable=True),
        sa.Column("modelo", sa.String(60), nullable=True),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("estado", sa.String(20), nullable=False, server_default="pendiente"),
        sa.Column("confirmado_por_id", sa.Integer(), sa.ForeignKey("usuarios.id"), nullable=True),
        sa.Column("confirmado_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "estado IN (" + ", ".join(f"'{v}'" for v in _ESTADO_VALUES) + ")",
            name="ck_tickets_propuestas_ia_estado",
        ),
    )
    op.create_index("ix_tickets_propuestas_ia_ticket_id", "tickets_propuestas_ia", ["ticket_id"])
    op.create_index(
        _UNIQUE_PENDIENTE_INDEX,
        "tickets_propuestas_ia",
        ["ticket_id", "campo"],
        unique=True,
        postgresql_where=sa.text("estado = 'pendiente'"),
    )


def downgrade() -> None:
    op.drop_index(_UNIQUE_PENDIENTE_INDEX, table_name="tickets_propuestas_ia")
    op.drop_index("ix_tickets_propuestas_ia_ticket_id", table_name="tickets_propuestas_ia")
    op.drop_table("tickets_propuestas_ia")
