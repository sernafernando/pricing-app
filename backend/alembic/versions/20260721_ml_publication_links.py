"""productos-catalog-family-tree PR1a: create ml_publication_links and ml_item_relations

Revision ID: 20260721_ml_publication_links
Revises: 20260721_ml_bot_answer_history
Create Date: 2026-07-21

Data-foundation tables for the recursive catalog/family publication tree
(design "Productos Catalog/Family Publication Tree", PR1a). Both tables are
ADDITIVE and intentionally kept separate from `tb_mercadolibre_items_publicados`:
that table's 5-minute ERP incremental sync `setattr`s every key in its
`item_dict` on every pass, so any ML-API-only column added there would be
NULLed on the very next sync. These new tables have their own writer (the
publication-link backfill/sync service, PR1b) and are never touched by the
ERP sync.

`ml_publication_links`: one scalar snapshot row per MLA (family_id,
user_product_id, inventory_id, catalog_listing, catalog_product_id,
fetched_at for staleness/cadence tracking).

`ml_item_relations`: junction table for ML's `item_relations` (MLA -> related
MLA edges, e.g. stock-synced "vinculada" publications), unique on
(mla, related_mla) to support idempotent upserts.

No runtime behavior change yet — nothing reads/writes these tables until
PR1b's backfill/sync service lands.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260721_ml_publication_links"
down_revision: Union[str, None] = "20260721_ml_bot_answer_history"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "ml_publication_links",
        sa.Column("mla", sa.String(length=50), nullable=False),
        sa.Column("family_id", sa.String(length=50), nullable=True),
        sa.Column("user_product_id", sa.String(length=50), nullable=True),
        sa.Column("inventory_id", sa.String(length=50), nullable=True),
        sa.Column("catalog_listing", sa.Boolean(), nullable=True, server_default=sa.false()),
        sa.Column("catalog_product_id", sa.String(length=50), nullable=True),
        sa.Column("item_id", sa.Integer(), nullable=True),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
        ),
        sa.PrimaryKeyConstraint("mla"),
    )
    op.create_index("ix_ml_publication_links_family_id", "ml_publication_links", ["family_id"])
    op.create_index("ix_ml_publication_links_item_id", "ml_publication_links", ["item_id"])

    op.create_table(
        "ml_item_relations",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("mla", sa.String(length=50), nullable=False),
        sa.Column("related_mla", sa.String(length=50), nullable=False),
        sa.Column("stock_relation", sa.Integer(), nullable=True),
        sa.Column("variation_id", sa.String(length=50), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("mla", "related_mla", name="uq_ml_item_relations_mla_related_mla"),
    )
    op.create_index("ix_ml_item_relations_mla", "ml_item_relations", ["mla"])
    op.create_index("ix_ml_item_relations_related_mla", "ml_item_relations", ["related_mla"])
    op.create_index(
        "ix_ml_item_relations_mla_related_mla_lookup",
        "ml_item_relations",
        ["mla", "related_mla"],
    )


def downgrade() -> None:
    op.drop_index("ix_ml_item_relations_mla_related_mla_lookup", table_name="ml_item_relations")
    op.drop_index("ix_ml_item_relations_related_mla", table_name="ml_item_relations")
    op.drop_index("ix_ml_item_relations_mla", table_name="ml_item_relations")
    op.drop_table("ml_item_relations")

    op.drop_index("ix_ml_publication_links_item_id", table_name="ml_publication_links")
    op.drop_index("ix_ml_publication_links_family_id", table_name="ml_publication_links")
    op.drop_table("ml_publication_links")
