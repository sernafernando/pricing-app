"""merge grupos.ver and ml_ads contribution soft-delete heads

Revision ID: 20261105_merge_grupos_ver_ml_ads_soft_delete
Revises: 20261105_grupos_ver, 20261231_ml_ads_contribution_soft_delete
Create Date: 2026-11-05

#2083 (grupos.ver) and #2067 (soft-delete aportes) both chained after
20261105_tacticals and landed on main in the same window, leaving two heads.
Unrelated objects, so this merge has no operations of its own.
"""

from typing import Sequence, Union

revision: str = "20261105_merge_grupos_ver_ml_ads_soft_delete"
down_revision: Union[str, None] = (
    "20261105_grupos_ver",
    "20261231_ml_ads_contribution_soft_delete",
)
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
