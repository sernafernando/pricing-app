"""ml_order_metrics + ml_order_metrics_dirty + worker_job_state (ventas-ml-rediseno PR1)

Revision ID: 20260922_ml_order_metrics
Revises: compras_041_oc_match_progress_phase
Create Date: 2026-09-22

PR1 is INERT: these three tables alone, no triggers, no worker (design D1,
D2, D3, D6). `ml_order_metrics` is 1:1 with `ml_orders_ops` (FK ON DELETE
CASCADE); `ml_order_metrics_dirty` is the versioned queue later PRs' triggers
and worker will read/write; `worker_job_state` is schedule/liveness state for
the generic worker (PR2+). Also adds `ix_ml_orders_ops_seller_date` (design
D2: KPI scope needs `(seller_id, date_created)`, not indexed today).

down_revision must be the unique alembic head at merge (branch tip
`compras_041_oc_match_progress_phase`; rehang if main advanced).
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "20260922_ml_order_metrics"
down_revision: Union[str, None] = "compras_041_oc_match_progress_phase"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "ml_order_metrics",
        sa.Column("order_id", sa.BigInteger(), nullable=False),
        sa.Column("neto", sa.Numeric(14, 2), nullable=True),
        sa.Column("neto_sin_iva", sa.Numeric(14, 2), nullable=True),
        sa.Column("iva_reconcilia", sa.Boolean(), nullable=True),
        sa.Column("costo_mercaderia", sa.Numeric(14, 2), nullable=True),
        sa.Column("total_gauss", sa.Numeric(14, 2), nullable=True),
        sa.Column("markup_pct", sa.Numeric(9, 2), nullable=True),
        sa.Column("gauss_status", sa.String(16), nullable=False),
        sa.Column("provisional_falta", sa.String(64), nullable=True),
        sa.Column("unresolved_reason", sa.String(64), nullable=True),
        sa.Column("formula_version", sa.SmallInteger(), nullable=False),
        sa.Column("computed_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["order_id"], ["ml_orders_ops.order_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("order_id"),
        sa.CheckConstraint("gauss_status IN ('ok', 'provisional', 'unresolved')", name="ck_ml_order_metrics_status"),
    )
    op.create_index("ix_ml_order_metrics_status", "ml_order_metrics", ["gauss_status"])
    # `DESC NULLS LAST` is Postgres-only syntax (design D2: sort key for the
    # listing) -- SQLite gets a plain descending index, same guard pattern
    # as `20260722_ml_bot_messages_bot_columns.py`.
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.create_index(
            "ix_ml_order_metrics_total_gauss",
            "ml_order_metrics",
            [sa.text("total_gauss DESC NULLS LAST")],
        )
    else:
        op.create_index(
            "ix_ml_order_metrics_total_gauss",
            "ml_order_metrics",
            [sa.text("total_gauss DESC")],
        )

    op.create_table(
        "ml_order_metrics_dirty",
        sa.Column("order_id", sa.BigInteger(), nullable=False),
        sa.Column("version", sa.BigInteger(), nullable=False, server_default="1"),
        sa.Column("reason", sa.String(32), nullable=False),
        sa.Column("enqueued_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("claimed_by", sa.String(64), nullable=True),
        sa.Column("claim_token", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("attempts", sa.SmallInteger(), nullable=False, server_default="0"),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("suspect", sa.Boolean(), nullable=False, server_default="false"),
        sa.PrimaryKeyConstraint("order_id"),
    )
    op.create_index("ix_ml_order_metrics_dirty_enqueued_at", "ml_order_metrics_dirty", ["enqueued_at"])

    op.create_table(
        "worker_job_state",
        sa.Column("name", sa.String(64), nullable=False),
        sa.Column("last_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_success_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("state", sa.String(32), nullable=True),
        sa.Column("detail", postgresql.JSONB(), nullable=True),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("name"),
    )

    # Plain CREATE INDEX on the ingestion table ml_orders_ops: it takes
    # seconds and briefly blocks that table's writes. CONCURRENTLY was tried
    # and reverted -- it must run outside a transaction, which neither this
    # migration's runner nor the round-trip test can provide without special
    # casing, and the only writer affected is the background sweep, which
    # retries.
    # `if_not_exists`: the ORM model declares this index too, so a schema
    # built by `create_all` (the test fixtures) already has it.
    op.create_index(
        "ix_ml_orders_ops_seller_date",
        "ml_orders_ops",
        ["seller_id", "date_created"],
        if_not_exists=True,
    )


def downgrade() -> None:
    op.drop_index("ix_ml_orders_ops_seller_date", table_name="ml_orders_ops", if_exists=True)
    op.drop_table("worker_job_state")
    op.drop_index("ix_ml_order_metrics_dirty_enqueued_at", table_name="ml_order_metrics_dirty")
    op.drop_table("ml_order_metrics_dirty")
    op.drop_index("ix_ml_order_metrics_total_gauss", table_name="ml_order_metrics")
    op.drop_index("ix_ml_order_metrics_status", table_name="ml_order_metrics")
    op.drop_table("ml_order_metrics")
