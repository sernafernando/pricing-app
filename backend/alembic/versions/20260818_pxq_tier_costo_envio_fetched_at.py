"""Add costo_envio_fetched_at to ml_pxq_tier (pxq-markup-antes-de-publicar
slice B).

Additive, no backfill: NULL means "never fetched," which is exactly the
state every existing row is already in and forces the first auto-fetch
(`pxq_markup_service.refresh_tier_shipping`) rather than fabricating a
false-fresh timestamp for rows that predate this column.

Tracks the freshness of `costo_envio_total`'s VALUE, not who wrote it (D3):
both a successful proxy fetch AND a manual write to `costo_envio_total`
stamp this column; a write to `precio_unitario`/`cantidad_minima` NULLs it
(see `app/services/pxq_tier_service.update_pxq_tier`).

TIMESTAMPTZ, matching every other timestamp on this table
(`created_at`/`updated_at`) — a naive comparison against the 24h TTL would
be meaningless.

ROLLBACK NOTE: the trigger (`refresh_tier_shipping`) is what must be
reverted first if this needs to be walked back in production — that is
what cuts traffic to the ml-webhook proxy. This column is purely additive
and can safely stay even if the trigger is reverted.

Revision ID: 20260818_pxq_tier_costo_envio_fetched_at
Revises: 20260813_propuesta_corregida
Create Date: 2026-08-18
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "20260818_pxq_tier_costo_envio_fetched_at"
# Rebased from 20260813_propuesta_corregida: main gained
# 20260814_tickets_triage_ejemplos (same parent) while the PxQ chain was in
# review, which split the graph into two heads on merge. This revision has
# not been applied anywhere yet, so re-parenting it keeps the chain linear
# (same resolution as 449d10ba, not a merge revision).
down_revision = "20260814_tickets_triage_ejemplos"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "ml_pxq_tier",
        sa.Column("costo_envio_fetched_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("ml_pxq_tier", "costo_envio_fetched_at")
