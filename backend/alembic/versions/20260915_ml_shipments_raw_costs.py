"""ml_shipments_ops: persist the whole shipment-costs payload

Revision ID: 20260915_raw_costs
Revises: 20260914_total_gauss
Create Date: 2026-09-15

Adds `raw_costs` (JSONB, nullable), the verbatim `/shipments/<id>/costs`
response. Additive, no backfill: existing rows read NULL until their next
cost sync, which is indistinguishable from today's state.

Why it exists: keeping only `sender_cost`/`receiver_cost` collapsed two
different facts into the same pair of zeroes -- a shipment ML subsidised
100%, and one whose costs were never fetched. The payload carries what
tells them apart, and also `senders[0].compensation`, where money ML pays
the seller for a Flex shipment would show up.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260915_raw_costs"
down_revision: Union[str, None] = "20260914_total_gauss"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("ml_shipments_ops", sa.Column("raw_costs", postgresql.JSONB(), nullable=True))


def downgrade() -> None:
    op.drop_column("ml_shipments_ops", "raw_costs")
