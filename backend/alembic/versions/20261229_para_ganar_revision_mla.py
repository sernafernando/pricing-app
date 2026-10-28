"""para_ganar: Advisor revision states per MLA (P4)

Revision ID: 20261229_para_ganar_revision_mla
Revises: 20261228_para_ganar_periodicidad
Create Date: 2026-12-29

Persists Pendiente de revisión / Sin novedades for the Advisor cola.
Written by the evaluation engine (P5); P4 only stores and exposes them.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20261229_para_ganar_revision_mla"
down_revision: Union[str, None] = "20261228_para_ganar_periodicidad"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "para_ganar_revision_mla",
        sa.Column("mla", sa.String(length=32), primary_key=True),
        sa.Column("estado", sa.String(length=32), nullable=False),
        sa.Column(
            "evaluated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_by_id",
            sa.Integer(),
            sa.ForeignKey("usuarios.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_para_ganar_revision_mla_estado",
        "para_ganar_revision_mla",
        ["estado"],
    )
    op.create_index(
        "ix_para_ganar_revision_mla_updated_by_id",
        "para_ganar_revision_mla",
        ["updated_by_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_para_ganar_revision_mla_updated_by_id", table_name="para_ganar_revision_mla")
    op.drop_index("ix_para_ganar_revision_mla_estado", table_name="para_ganar_revision_mla")
    op.drop_table("para_ganar_revision_mla")
