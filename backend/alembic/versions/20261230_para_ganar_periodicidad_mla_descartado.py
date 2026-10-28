"""para_ganar: dismiss new-MLA alerts without subscribing

Revision ID: 20261230_para_ganar_periodicidad_descartado
Revises: 20261229_para_ganar_revision_mla
Create Date: 2026-12-30

Stores MLAs the operator acknowledged as 'new' without adding them to the
explicit periodicidad list. Future MLAs not in this set still alert.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20261230_para_ganar_periodicidad_descartado"
down_revision: Union[str, None] = "20261229_para_ganar_revision_mla"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "para_ganar_periodicidad_ean_mla_descartado",
        sa.Column(
            "ean",
            sa.String(length=64),
            sa.ForeignKey("para_ganar_periodicidad_ean.ean", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("mla", sa.String(length=32), primary_key=True),
        sa.Column(
            "discarded_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "discarded_by_id",
            sa.Integer(),
            sa.ForeignKey("usuarios.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_para_ganar_periodicidad_ean_mla_descartado_by",
        "para_ganar_periodicidad_ean_mla_descartado",
        ["discarded_by_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_para_ganar_periodicidad_ean_mla_descartado_by",
        table_name="para_ganar_periodicidad_ean_mla_descartado",
    )
    op.drop_table("para_ganar_periodicidad_ean_mla_descartado")
