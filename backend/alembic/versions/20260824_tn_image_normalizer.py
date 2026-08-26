"""tn_image_normalizer: run/artifact/item schema (slice 3, no readers/writers yet)

Revision ID: 20260824_tn_image_normalizer
Revises: 20260821_tn_reconcile_excepcion
Create Date: 2026-08-24

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260824_tn_image_normalizer"
down_revision: Union[str, None] = "20260821_tn_reconcile_excepcion"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "tn_image_normalization_run",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_by_user_id", sa.Integer(), nullable=False),
        sa.Column("preset", sa.SmallInteger(), nullable=False),
        sa.Column("fill_color", sa.String(length=7), nullable=False, server_default="#ffffff"),
        sa.Column("output_format", sa.String(length=8), nullable=False),
        sa.Column("quality", sa.SmallInteger(), nullable=False),
        sa.Column("max_output_bytes", sa.Integer(), nullable=False),
        sa.Column("params_fingerprint", sa.String(length=32), nullable=False),
        # Safe default is not optional: no stage may write to Tienda Nube
        # without a human having seen a dry-run first.
        sa.Column("dry_run", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("state", sa.String(length=24), nullable=False),
        sa.Column("totals", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["usuarios.id"]),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "tn_image_artifact",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("source_hash", sa.String(length=64), nullable=False),
        sa.Column("normalization_params", sa.String(length=32), nullable=False),
        sa.Column("output_path", sa.Text(), nullable=True),
        sa.Column("output_hash", sa.String(length=64), nullable=True),
        sa.Column("output_bytes", sa.Integer(), nullable=True),
        sa.Column("width", sa.Integer(), nullable=True),
        sa.Column("height", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        # Dedup key is a property of the artifact itself — one artifact
        # legitimately serves many EANs and many runs, which is why this is
        # a separate table rather than a constraint on the item row.
        sa.UniqueConstraint("source_hash", "normalization_params", name="uq_tn_img_artifact_dedup"),
    )

    op.create_table(
        "tn_image_normalization_item",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("run_id", sa.Integer(), nullable=False),
        sa.Column("ean", sa.String(length=20), nullable=False),
        sa.Column("tn_product_id", sa.Integer(), nullable=True),
        sa.Column("source_slot", sa.SmallInteger(), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("source_hash", sa.String(length=64), nullable=True),
        sa.Column("artifact_id", sa.Integer(), nullable=True),
        # `inconclusive` is a first-class state distinct from `failed` — see
        # `inconclusive_reason` below — never a status string reused by both.
        sa.Column("state", sa.String(length=32), nullable=False),
        sa.Column("inconclusive_reason", sa.Text(), nullable=True),
        sa.Column("tn_image_id", sa.Integer(), nullable=True),
        sa.Column("claim_definitive", sa.Boolean(), nullable=True),
        sa.Column("attempts", sa.SmallInteger(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["run_id"], ["tn_image_normalization_run.id"]),
        sa.ForeignKeyConstraint(["artifact_id"], ["tn_image_artifact.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    # The review grid's main filter.
    op.create_index(
        "ix_tn_image_normalization_item_run_id_state",
        "tn_image_normalization_item",
        ["run_id", "state"],
    )
    op.create_index("ix_tn_image_normalization_item_ean", "tn_image_normalization_item", ["ean"])
    op.create_index("ix_tn_image_normalization_item_tn_product_id", "tn_image_normalization_item", ["tn_product_id"])


def downgrade() -> None:
    op.drop_index("ix_tn_image_normalization_item_tn_product_id", table_name="tn_image_normalization_item")
    op.drop_index("ix_tn_image_normalization_item_ean", table_name="tn_image_normalization_item")
    op.drop_index("ix_tn_image_normalization_item_run_id_state", table_name="tn_image_normalization_item")
    op.drop_table("tn_image_normalization_item")
    op.drop_table("tn_image_artifact")
    op.drop_table("tn_image_normalization_run")
