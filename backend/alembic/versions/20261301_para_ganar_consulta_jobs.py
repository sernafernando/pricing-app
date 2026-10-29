"""para_ganar: consultation job tables (A1/P6 worker queue)

Revision ID: 20261301_para_ganar_consulta_jobs
Revises: 20261231_para_ganar_revision_baseline
Create Date: 2026-10-29

Stores PM/cron-owned consultation batches and per-MLA items drained by the
ML worker (refresh catalog competition → P5 evaluate).
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20261301_para_ganar_consulta_jobs"
down_revision: Union[str, None] = "20261231_para_ganar_revision_baseline"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "para_ganar_consulta_job",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("created_by_id", sa.Integer(), nullable=True),
        sa.Column("source", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("total_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("done_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("skipped_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("failed_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("pendiente_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("sin_novedades_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("last_progress_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["created_by_id"], ["usuarios.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_para_ganar_consulta_job_created_by_id", "para_ganar_consulta_job", ["created_by_id"])
    op.create_index("ix_para_ganar_consulta_job_status", "para_ganar_consulta_job", ["status"])
    op.create_index("ix_para_ganar_consulta_job_last_progress_at", "para_ganar_consulta_job", ["last_progress_at"])

    op.create_table(
        "para_ganar_consulta_job_item",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("job_id", sa.Integer(), nullable=False),
        sa.Column("mla", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("revision_estado", sa.String(length=32), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["job_id"], ["para_ganar_consulta_job.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("job_id", "mla", name="uq_para_ganar_consulta_job_item_job_mla"),
    )
    op.create_index("ix_para_ganar_consulta_job_item_job_id", "para_ganar_consulta_job_item", ["job_id"])
    op.create_index(
        "ix_para_ganar_consulta_job_item_claim",
        "para_ganar_consulta_job_item",
        ["status", "job_id", "id"],
    )


def downgrade() -> None:
    op.drop_index("ix_para_ganar_consulta_job_item_claim", table_name="para_ganar_consulta_job_item")
    op.drop_index("ix_para_ganar_consulta_job_item_job_id", table_name="para_ganar_consulta_job_item")
    op.drop_table("para_ganar_consulta_job_item")
    op.drop_index("ix_para_ganar_consulta_job_last_progress_at", table_name="para_ganar_consulta_job")
    op.drop_index("ix_para_ganar_consulta_job_status", table_name="para_ganar_consulta_job")
    op.drop_index("ix_para_ganar_consulta_job_created_by_id", table_name="para_ganar_consulta_job")
    op.drop_table("para_ganar_consulta_job")
