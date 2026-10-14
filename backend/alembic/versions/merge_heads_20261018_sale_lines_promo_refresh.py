"""merge the sale lines and promotion reactivation refresh heads

Revision ID: 20261018_merge_sale_lines_promo_refresh
Revises: 20261018_ml_sale_lines, 20261018_promo_refresh_reactivation
Create Date: 2026-10-18

#1515 and #1521 each chained their migration after 20261017_ml_items_installments_campaign
and were merged in the same window, leaving two heads. They create unrelated tables
(ml_sale_lines and promo_refresh_reactivation), so the merge has no operations of its own.
"""

from typing import Sequence, Union


# revision identifiers, used by Alembic.
revision: str = "20261018_merge_sale_lines_promo_refresh"
down_revision: Union[str, None] = (
    "20261018_ml_sale_lines",
    "20261018_promo_refresh_reactivation",
)
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
