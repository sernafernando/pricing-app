"""para_ganar: periodicidad subscription by EAN

Revision ID: 20261228_para_ganar_periodicidad
Revises: 20261205_para_ganar_catalog_sellers
Create Date: 2026-12-28

EAN is the unit of periodic review subscription. Scope: whole EAN, explicit
MLAs, or rules (tipos / pricelists / tienda oficial).
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20261228_para_ganar_periodicidad"
down_revision: Union[str, None] = "20261205_para_ganar_catalog_sellers"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "para_ganar_periodicidad_ean",
        sa.Column("ean", sa.String(length=64), primary_key=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("scope_mode", sa.String(length=16), nullable=False, server_default="all"),
        sa.Column(
            "tipos_publicacion",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "pricelist_ids",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "tienda_oficial_ids",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "created_at",
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
        sa.Column("updated_by_id", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(
            ["updated_by_id"],
            ["usuarios.id"],
            ondelete="SET NULL",
        ),
    )
    op.create_index(
        "ix_para_ganar_periodicidad_ean_updated_by_id",
        "para_ganar_periodicidad_ean",
        ["updated_by_id"],
    )

    op.create_table(
        "para_ganar_periodicidad_ean_mla",
        sa.Column("ean", sa.String(length=64), primary_key=True),
        sa.Column("mla", sa.String(length=32), primary_key=True),
        sa.ForeignKeyConstraint(
            ["ean"],
            ["para_ganar_periodicidad_ean.ean"],
            ondelete="CASCADE",
        ),
    )
    op.create_index(
        "ix_para_ganar_periodicidad_ean_mla_mla",
        "para_ganar_periodicidad_ean_mla",
        ["mla"],
    )


def downgrade() -> None:
    op.drop_index("ix_para_ganar_periodicidad_ean_mla_mla", table_name="para_ganar_periodicidad_ean_mla")
    op.drop_table("para_ganar_periodicidad_ean_mla")
    op.drop_index(
        "ix_para_ganar_periodicidad_ean_updated_by_id",
        table_name="para_ganar_periodicidad_ean",
    )
    op.drop_table("para_ganar_periodicidad_ean")
