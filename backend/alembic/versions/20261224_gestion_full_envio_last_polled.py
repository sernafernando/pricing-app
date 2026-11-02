"""gestion_full_envio.last_polled_at for reconcile batch rotation

Revision ID: 20261224_gestion_full_envio_last_polled
Revises: 20261223_gestion_full_envio_ops
Create Date: 2026-11-02
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20261224_gestion_full_envio_last_polled"
down_revision: Union[str, None] = "20261223_gestion_full_envio_ops"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "gestion_full_envio",
        sa.Column("last_polled_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_gestion_full_envio_last_polled_at",
        "gestion_full_envio",
        ["last_polled_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_gestion_full_envio_last_polled_at", table_name="gestion_full_envio")
    op.drop_column("gestion_full_envio", "last_polled_at")
