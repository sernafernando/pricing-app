"""merge pxq cantidad_ge_1 y triage_auto_apply

Revision ID: 7f4b76219e4c
Revises: 20260812_pxq_cantidad_ge_1, 20260812_triage_auto_apply
Create Date: 2026-08-13 17:25:00.903071

"""

from typing import Sequence, Union


# revision identifiers, used by Alembic.
revision: str = "7f4b76219e4c"
down_revision: Union[str, None] = ("20260812_pxq_cantidad_ge_1", "20260812_triage_auto_apply")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
