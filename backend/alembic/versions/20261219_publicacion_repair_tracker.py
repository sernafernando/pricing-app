"""Create publicacion_repair_run and publicacion_repair_event

Revision ID: 20261219_publicacion_repair_tracker
Revises: 20261218_ml_pub_snapshots_shipping
Create Date: 2026-11-02

Audit tables for envio/sku publication repair jobs. Not the user-price
auditoria table and not free_shipping_fix_log.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "20261219_publicacion_repair_tracker"
down_revision: Union[str, None] = "20261218_ml_pub_snapshots_shipping"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "publicacion_repair_run",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("job_type", sa.String(length=20), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("scanned", sa.Integer(), server_default="0", nullable=False),
        sa.Column("changed", sa.Integer(), server_default="0", nullable=False),
        sa.Column("skipped", sa.Integer(), server_default="0", nullable=False),
        sa.Column("errors", sa.Integer(), server_default="0", nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("trigger", sa.String(length=40), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_publicacion_repair_run_job_type", "publicacion_repair_run", ["job_type"])
    op.create_index("ix_publicacion_repair_run_status", "publicacion_repair_run", ["status"])
    op.create_index("ix_publicacion_repair_run_started", "publicacion_repair_run", ["started_at"])

    op.create_table(
        "publicacion_repair_event",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("run_id", sa.Integer(), nullable=False),
        sa.Column("mla_id", sa.String(length=50), nullable=False),
        sa.Column("item_id", sa.BigInteger(), nullable=True),
        sa.Column("action", sa.String(length=20), nullable=False),
        sa.Column("before", JSONB(), nullable=True),
        sa.Column("after", JSONB(), nullable=True),
        sa.Column("detail", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["run_id"], ["publicacion_repair_run.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_publicacion_repair_event_run_id", "publicacion_repair_event", ["run_id"])
    op.create_index("ix_publicacion_repair_event_mla_id", "publicacion_repair_event", ["mla_id"])
    op.create_index(
        "ix_publicacion_repair_event_run_mla",
        "publicacion_repair_event",
        ["run_id", "mla_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_publicacion_repair_event_run_mla", table_name="publicacion_repair_event")
    op.drop_index("ix_publicacion_repair_event_mla_id", table_name="publicacion_repair_event")
    op.drop_index("ix_publicacion_repair_event_run_id", table_name="publicacion_repair_event")
    op.drop_table("publicacion_repair_event")
    op.drop_index("ix_publicacion_repair_run_started", table_name="publicacion_repair_run")
    op.drop_index("ix_publicacion_repair_run_status", table_name="publicacion_repair_run")
    op.drop_index("ix_publicacion_repair_run_job_type", table_name="publicacion_repair_run")
    op.drop_table("publicacion_repair_run")
