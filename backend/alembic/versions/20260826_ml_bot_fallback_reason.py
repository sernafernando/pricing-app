"""ml-bot: add ml_bot_questions.fallback_reason

Revision ID: 20260826_ml_bot_fallback_reason
Revises: 20260821_tn_reconcile_excepcion
Create Date: 2026-08-26

Adds a nullable `fallback_reason` column (design ml-bot-fallback-reason-
tracking §WU2) recording WHY a question landed in the fallback path
(`injection_flagged`, `provider_error`, `fallback_denylist`, `deflection`,
`low_confidence`, `drafted_no_answer`). Nullable, no default, no backfill:
existing rows keep `fallback_reason IS NULL` — only newly-drafted rows
populate it going forward.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260826_ml_bot_fallback_reason"
down_revision: Union[str, None] = "20260821_tn_reconcile_excepcion"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "ml_bot_questions",
        sa.Column("fallback_reason", sa.String(length=32), nullable=True),
    )
    op.create_index(
        "idx_ml_bot_questions_fallback_reason",
        "ml_bot_questions",
        ["fallback_reason"],
    )


def downgrade() -> None:
    op.drop_index("idx_ml_bot_questions_fallback_reason", table_name="ml_bot_questions")
    op.drop_column("ml_bot_questions", "fallback_reason")
