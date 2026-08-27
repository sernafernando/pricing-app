"""ml-bot-panel-operador PR6: add `sent_at` to ml_bot_messages

Revision ID: 20260827_ml_bot_messages_sent_at
Revises: 20260826_ml_orders_ops_models
Create Date: 2026-08-27

Adds a nullable send timestamp, distinct from `bot_updated_at` (which is a
generic "row last touched" signal, bumped by `onupdate` on ANY column write
— not only the transition into `sent`). Design decision 4: the timestamp is
stamped inside the existing success CAS in the `/messages/{id}/send` handler
so it commits atomically with the `bot_status='sent'` transition.

Deliberately NO backfill: `bot_updated_at` is a different signal and using
it to backfill `sent_at` on already-sent historic rows would fabricate a
timestamp that was never actually the send time. Historic `sent` rows stay
`sent_at IS NULL` — the frontend renders that case as "sent, time unknown",
never as blank/not-sent.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260827_ml_bot_messages_sent_at"
down_revision: Union[str, None] = "20260826_ml_orders_ops_models"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("ml_bot_messages", sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("ml_bot_messages", "sent_at")
