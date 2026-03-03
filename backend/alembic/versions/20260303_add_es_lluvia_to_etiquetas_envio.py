"""Add es_lluvia column to etiquetas_envio

Revision ID: lluvia_001
Revises: None (standalone — alembic chain broken, apply directly)
Create Date: 2026-03-03
"""

import sqlalchemy as sa
from alembic import op

revision = "lluvia_001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "etiquetas_envio",
        sa.Column(
            "es_lluvia",
            sa.Boolean(),
            server_default="false",
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("etiquetas_envio", "es_lluvia")
