"""catalog_competition_refresh_pending queue for hay_mejores → snapshot refresh.

Revision ID: 20261104_catalog_competition_refresh_pending
Revises: 20261230_sell_out_renovada_de
Create Date: 2026-11-04

One row per MLA. Enqueued when hay_mejores_ofertas newly flags (or re-marks with a
new fingerprint); drained by ml_publications.catalog_competition_refresh.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20261104_catalog_competition_refresh_pending"
down_revision: Union[str, Sequence[str], None] = "20261230_sell_out_renovada_de"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "catalog_competition_refresh_pending",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("mla", sa.String(length=32), nullable=False),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("mla", name="uq_catalog_competition_refresh_pending_mla"),
    )
    op.create_index(
        "ix_catalog_competition_refresh_pending_due_at",
        "catalog_competition_refresh_pending",
        ["due_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_catalog_competition_refresh_pending_due_at", table_name="catalog_competition_refresh_pending")
    op.drop_table("catalog_competition_refresh_pending")
