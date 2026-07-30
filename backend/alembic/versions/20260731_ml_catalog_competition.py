"""promos-catalog-prices-and-official-store: ml_catalog_competition table + latest view

Revision ID: 20260731_ml_catalog_competition
Revises: 20260727_ppp_lateral_index
Create Date: 2026-07-31

Snapshot-per-fetch persistence for MercadoLibre catalog-competition data
(slice C1a, design #1210 section 3.1). Shape is modeled on
`ml_catalog_status`, with two deliberate divergences:

1. `TIMESTAMPTZ` (`DateTime(timezone=True)`) on every timestamp column,
   consistently in both the DDL and the model. `ml_catalog_status`'s raw
   SQL used a bare TIMESTAMP while its model declared `timezone=True` —
   a latent tz-naive/tz-aware mismatch. The repo has a documented
   tz-naive incident; this migration does not repeat it.
2. Created via a real Alembic migration. `ml_catalog_status` was created
   by raw SQL (`backend/sql/create_ml_catalog_status.sql`), which
   violates backend/CLAUDE.md's "ALWAYS create Alembic migrations" rule.

The view `v_ml_catalog_competition_latest` is versioned here (not left
as an ad-hoc SQL file) so a fresh environment is never missing it, and
so `downgrade()` has something real to drop.

`competitors` is JSONB, NOT NULL DEFAULT '[]' — a `not_catalog` or
`error` row has zero competitors, which is `[]`, never `NULL`.
`fetch_status` and `source_payload_hash` exist so a future cron can
record a no-op refresh without another migration.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "20260731_ml_catalog_competition"
down_revision = "20260727_ppp_lateral_index"
branch_labels = None
depends_on = None

TABLE_NAME = "ml_catalog_competition"
VIEW_NAME = "v_ml_catalog_competition_latest"


def upgrade() -> None:
    op.create_table(
        TABLE_NAME,
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("mla", sa.String(length=20), nullable=False),
        sa.Column(
            "fecha_consulta",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("catalog_product_id", sa.String(length=50), nullable=True),
        # ok | not_catalog | error — non-catalog MLAs are a first-class
        # stored fact, not a silently-dropped row.
        sa.Column("fetch_status", sa.String(length=20), nullable=False),
        sa.Column("our_item_id", sa.String(length=20), nullable=True),
        sa.Column("our_seller_id", sa.String(length=32), nullable=True),
        sa.Column("our_price", sa.Numeric(18, 2), nullable=True),
        sa.Column("our_currency_id", sa.String(length=8), nullable=True),
        sa.Column("our_bucket_key", sa.String(length=64), nullable=True),
        sa.Column(
            "competitors",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("competitor_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("source_payload_hash", sa.String(length=64), nullable=True),
        sa.Column("error_detail", sa.String(length=500), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint("mla", "fecha_consulta", name="uq_ml_catalog_competition_mla_fecha"),
    )
    # Leading column mla serves both the DISTINCT ON in the view below and
    # any mla-only lookup, so no separate single-column index is created.
    op.create_index(
        "idx_mlcc_mla_fecha",
        TABLE_NAME,
        ["mla", sa.text("fecha_consulta DESC")],
    )
    op.create_index("idx_mlcc_fetch_status", TABLE_NAME, ["fetch_status"])

    op.execute(
        f"""
        CREATE OR REPLACE VIEW {VIEW_NAME} AS
        SELECT DISTINCT ON (mla)
            mla, fecha_consulta, catalog_product_id, fetch_status,
            our_item_id, our_seller_id, our_price, our_currency_id, our_bucket_key,
            competitors, competitor_count, source_payload_hash, error_detail
        FROM {TABLE_NAME}
        ORDER BY mla, fecha_consulta DESC
        """
    )


def downgrade() -> None:
    op.execute(f"DROP VIEW IF EXISTS {VIEW_NAME}")
    op.drop_index("idx_mlcc_fetch_status", table_name=TABLE_NAME)
    op.drop_index("idx_mlcc_mla_fecha", table_name=TABLE_NAME)
    op.drop_table(TABLE_NAME)
