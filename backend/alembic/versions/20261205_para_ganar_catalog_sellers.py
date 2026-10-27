"""para_ganar: catalog seller roster + disposition

Revision ID: 20261205_para_ganar_catalog_sellers
Revises: 20261201_para_ganar_criterios_mla
Create Date: 2026-12-05

Stores sellers seen in a catalog (from competition snapshots) with a
disposition for TOP/ranking: active, ignore_participant, hide, exclude_from_top.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20261205_para_ganar_catalog_sellers"
down_revision: Union[str, None] = "20261201_para_ganar_criterios_mla"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "para_ganar_catalog_sellers",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("catalog_product_id", sa.String(length=50), nullable=False),
        sa.Column("seller_id", sa.String(length=32), nullable=False),
        sa.Column("nickname", sa.String(length=128), nullable=True),
        sa.Column(
            "disposition",
            sa.String(length=32),
            nullable=False,
            server_default="active",
        ),
        sa.Column("last_item_id", sa.String(length=32), nullable=True),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.Column(
            "updated_by_id",
            sa.Integer(),
            sa.ForeignKey("usuarios.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.UniqueConstraint(
            "catalog_product_id",
            "seller_id",
            name="uq_para_ganar_catalog_seller",
        ),
    )
    op.create_index("ix_para_ganar_catalog_sellers_id", "para_ganar_catalog_sellers", ["id"])
    op.create_index(
        "ix_para_ganar_catalog_sellers_catalog_product_id",
        "para_ganar_catalog_sellers",
        ["catalog_product_id"],
    )
    op.create_index(
        "ix_para_ganar_catalog_sellers_seller_id",
        "para_ganar_catalog_sellers",
        ["seller_id"],
    )
    op.create_index(
        "ix_para_ganar_catalog_sellers_updated_by_id",
        "para_ganar_catalog_sellers",
        ["updated_by_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_para_ganar_catalog_sellers_updated_by_id",
        table_name="para_ganar_catalog_sellers",
    )
    op.drop_index(
        "ix_para_ganar_catalog_sellers_seller_id",
        table_name="para_ganar_catalog_sellers",
    )
    op.drop_index(
        "ix_para_ganar_catalog_sellers_catalog_product_id",
        table_name="para_ganar_catalog_sellers",
    )
    op.drop_index("ix_para_ganar_catalog_sellers_id", table_name="para_ganar_catalog_sellers")
    op.drop_table("para_ganar_catalog_sellers")
