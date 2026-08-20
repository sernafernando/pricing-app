"""Create tickets_vikunja_sync ledger table (sdd/tickets-sync-vikunja PR 1)

Revision ID: 20260820_ticket_vikunja_sync
Revises: 20260819_triage_ejemplos_permiso
Create Date: 2026-08-20
"""

from alembic import op
import sqlalchemy as sa

revision = "20260820_ticket_vikunja_sync"
down_revision = "20260819_triage_ejemplos_permiso"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "tickets_vikunja_sync",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "ticket_id",
            sa.Integer(),
            sa.ForeignKey("tickets.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("vikunja_task_id", sa.Integer(), nullable=True),
        sa.Column("estado", sa.String(length=20), nullable=False, server_default="pendiente"),
        sa.Column("intentos", sa.SmallInteger(), nullable=False, server_default="0"),
        sa.Column("ultimo_error", sa.String(length=500), nullable=True),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("synced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("notificado_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("adjuntos_pendientes", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint("ticket_id", name="uq_tickets_vikunja_sync_ticket_id"),
    )
    op.create_index("ix_tickets_vikunja_sync_ticket_id", "tickets_vikunja_sync", ["ticket_id"])
    op.create_index("ix_tickets_vikunja_sync_estado", "tickets_vikunja_sync", ["estado"])
    op.create_index(
        "ix_tickets_vikunja_sync_estado_updated_at",
        "tickets_vikunja_sync",
        ["estado", "updated_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_tickets_vikunja_sync_estado_updated_at", table_name="tickets_vikunja_sync")
    op.drop_index("ix_tickets_vikunja_sync_estado", table_name="tickets_vikunja_sync")
    op.drop_index("ix_tickets_vikunja_sync_ticket_id", table_name="tickets_vikunja_sync")
    op.drop_table("tickets_vikunja_sync")
