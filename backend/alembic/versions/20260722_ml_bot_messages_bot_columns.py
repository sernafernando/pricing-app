"""ml-bot-messages-reply Phase A: bot draft/classify columns on ml_bot_messages

Revision ID: 20260722_ml_bot_messages_bot_columns
Revises: compras_037_pedido_cuenta_corriente
Create Date: 2026-07-22

Adds the drafting/classification state machine columns to `ml_bot_messages`
(design "Migration columns"): all nullable/additive, does not touch ML's raw
`status` column (hard collision-avoidance rule — see
app/models/ml_bot_message.py docstring). `bot_status` is a NEW, separate
column driving the Phase A state machine:

    (NULL|pending) -> drafting -> {awaiting_human|blocked_claim|failed}
    drafting -> pending (bounded retry / stale reclaim)
    awaiting_human -> superseded (newer buyer message re-opens aggregation)
    {awaiting_human|blocked_claim} -> taken_over -> {sent|failed}
    failed -> pending (manual retry)

Only a human take-over + explicit send (Phase A `send-now` action, itself
gated off by default) may ever reach `sent` in this phase — there is no
auto-send path here.

Dialect-guard (mirrors `20260721_ml_bot_answer_history`'s convention): the
partial index on `bot_status` uses `postgresql_where` and is only created on
Postgres — SQLite (the CI/test dialect) gets a plain (non-partial) index
instead, so `alembic upgrade head` stays clean everywhere even though the
app's test suite builds its schema from the ORM directly, not this
migration.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260722_ml_bot_messages_bot_columns"
down_revision: Union[str, None] = "compras_037_pedido_cuenta_corriente"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    is_postgres = bind.dialect.name == "postgresql"

    op.add_column("ml_bot_messages", sa.Column("bot_status", sa.String(length=24), nullable=True))
    op.add_column("ml_bot_messages", sa.Column("drafted_answer", sa.Text(), nullable=True))
    op.add_column("ml_bot_messages", sa.Column("intent_category", sa.String(length=40), nullable=True))
    op.add_column("ml_bot_messages", sa.Column("confidence", sa.Numeric(4, 3), nullable=True))
    op.add_column("ml_bot_messages", sa.Column("answer_source", sa.String(length=10), nullable=True))
    op.add_column("ml_bot_messages", sa.Column("llm_provider", sa.String(length=100), nullable=True))
    op.add_column(
        "ml_bot_messages",
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column("ml_bot_messages", sa.Column("last_error", sa.Text(), nullable=True))
    op.add_column("ml_bot_messages", sa.Column("drafted_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        "ml_bot_messages",
        sa.Column("bot_updated_at", sa.DateTime(timezone=True), nullable=True, onupdate=sa.func.now()),
    )

    if is_postgres:
        op.create_index(
            "idx_ml_bot_messages_bot_status",
            "ml_bot_messages",
            ["bot_status"],
            postgresql_where=sa.text("bot_status IS NOT NULL"),
        )
    else:
        op.create_index("idx_ml_bot_messages_bot_status", "ml_bot_messages", ["bot_status"])


def downgrade() -> None:
    op.drop_index("idx_ml_bot_messages_bot_status", table_name="ml_bot_messages")
    op.drop_column("ml_bot_messages", "bot_updated_at")
    op.drop_column("ml_bot_messages", "drafted_at")
    op.drop_column("ml_bot_messages", "last_error")
    op.drop_column("ml_bot_messages", "attempts")
    op.drop_column("ml_bot_messages", "llm_provider")
    op.drop_column("ml_bot_messages", "answer_source")
    op.drop_column("ml_bot_messages", "confidence")
    op.drop_column("ml_bot_messages", "intent_category")
    op.drop_column("ml_bot_messages", "drafted_answer")
    op.drop_column("ml_bot_messages", "bot_status")
