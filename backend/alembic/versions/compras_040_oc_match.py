"""compras_040: OC-match jobs and renglones (foundations, hook unwired)

Revision ID: compras_040_oc_match
Revises: 20260909_activity_cursor
Create Date: 2026-09-09

Additive tables for feat-compras-oc-match Phase 1. down_revision is the
Alembic head at apply time (`20260909_activity_cursor`), not compras_039
(later heads already exist on that lineage).
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "compras_040_oc_match"
down_revision: Union[str, None] = "20260909_activity_cursor"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "compras_oc_match_jobs",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column(
            "pedido_id",
            sa.BigInteger(),
            sa.ForeignKey("pedidos_compra.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "attachment_id",
            sa.BigInteger(),
            sa.ForeignKey("compras_adjuntos.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.String(length=20),
            nullable=False,
            server_default="queued",
        ),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("acta", sa.Text(), nullable=True),
        sa.Column("excel_rel_path", sa.String(length=500), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "pedido_id",
            "attachment_id",
            name="uq_oc_match_jobs_pedido_attachment",
        ),
        sa.CheckConstraint(
            "status IN ('queued','running','done','error','skipped')",
            name="ck_oc_match_jobs_status",
        ),
    )
    op.create_index("ix_oc_match_jobs_status", "compras_oc_match_jobs", ["status"])
    op.create_index("ix_oc_match_jobs_pedido_id", "compras_oc_match_jobs", ["pedido_id"])
    op.create_index(
        "ix_oc_match_jobs_started_at",
        "compras_oc_match_jobs",
        ["started_at"],
    )

    op.create_table(
        "compras_oc_match_renglones",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column(
            "job_id",
            sa.BigInteger(),
            sa.ForeignKey("compras_oc_match_jobs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("indice", sa.Integer(), nullable=False),
        sa.Column("descripcion", sa.Text(), nullable=True),
        sa.Column("cantidad", sa.Numeric(18, 4), nullable=True),
        sa.Column("precio_unitario", sa.Numeric(18, 4), nullable=True),
        sa.Column("moneda", sa.String(length=3), nullable=True),
        sa.Column("codigo_proveedor", sa.String(length=100), nullable=True),
        sa.Column("codigo_fabricante", sa.String(length=100), nullable=True),
        sa.Column("ean_extract", sa.String(length=32), nullable=True),
        sa.Column("ean_ultimos4", sa.String(length=4), nullable=True),
        sa.Column(
            "omitir",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column("motivo_omitir", sa.Text(), nullable=True),
        sa.Column("match_estado", sa.String(length=20), nullable=True),
        sa.Column("item_id", sa.String(length=64), nullable=True),
        sa.Column("ean", sa.String(length=32), nullable=True),
        sa.Column("confianza", sa.String(length=16), nullable=True),
        sa.Column("motivo", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "job_id",
            "indice",
            name="uq_oc_match_renglones_job_indice",
        ),
        sa.CheckConstraint(
            "match_estado IS NULL OR match_estado IN ('ok','no_hallado','omitido')",
            name="ck_oc_match_renglones_match_estado",
        ),
    )
    op.create_index(
        "ix_oc_match_renglones_job_id",
        "compras_oc_match_renglones",
        ["job_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_oc_match_renglones_job_id", table_name="compras_oc_match_renglones")
    op.drop_table("compras_oc_match_renglones")
    op.drop_index("ix_oc_match_jobs_started_at", table_name="compras_oc_match_jobs")
    op.drop_index("ix_oc_match_jobs_pedido_id", table_name="compras_oc_match_jobs")
    op.drop_index("ix_oc_match_jobs_status", table_name="compras_oc_match_jobs")
    op.drop_table("compras_oc_match_jobs")
