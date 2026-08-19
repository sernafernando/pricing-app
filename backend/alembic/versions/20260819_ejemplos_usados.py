"""add ejemplos_usados to tickets_propuestas_ia

Revision ID: 20260819_ejemplos_usados
Revises: 20260818_pxq_tier_costo_envio_fetched_at
Create Date: 2026-08-19 00:00:00

tickets-triage-feedback PR4b: nullable retrieval-observability column, own
migration so this slice stays independently shippable from the rest of
PR4b's code (dark-launched, both `TICKETS_TRIAGE_EJEMPLOS_CAPTURE` and
`TICKETS_TRIAGE_EJEMPLOS_READ` default False — zero behavior change on
merge). See `PropuestaIA.ejemplos_usados`'s own docstring for its three-way
NULL/0/N meaning.
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "20260819_ejemplos_usados"
down_revision = "20260818_pxq_tier_costo_envio_fetched_at"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "tickets_propuestas_ia",
        sa.Column("ejemplos_usados", sa.SmallInteger(), nullable=True),
    )


def downgrade():
    op.drop_column("tickets_propuestas_ia", "ejemplos_usados")
