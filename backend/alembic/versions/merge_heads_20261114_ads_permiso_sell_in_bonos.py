"""merge the Ads contributions permission and sell-in bonus scope heads

Revision ID: 20261114_merge_ads_permiso_sell_in_bonos
Revises: 20261114_ml_ads_contributions_permiso, 20261114_sell_in_bonos_alcance
Create Date: 2026-11-14

#1706 and #1707 each chained their migration after 20261113_ml_ads_campaign_contributions
and were merged in the same window, leaving two heads. They touch unrelated objects (a
permission seed and the sell-in bonus columns), so the merge has no operations of its own.
"""

from typing import Sequence, Union


# revision identifiers, used by Alembic.
revision: str = "20261114_merge_ads_permiso_sell_in_bonos"
down_revision: Union[str, None] = (
    "20261114_ml_ads_contributions_permiso",
    "20261114_sell_in_bonos_alcance",
)
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
