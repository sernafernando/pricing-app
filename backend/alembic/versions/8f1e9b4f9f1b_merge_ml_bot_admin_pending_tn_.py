"""merge ml_bot_admin_pending + tn_publicacion_permiso

Revision ID: 8f1e9b4f9f1b
Revises: 20260723_ml_bot_admin_pending, 20260723_tn_publicacion_permiso
Create Date: 2026-07-23 15:52:26.739894

"""

from typing import Sequence, Union


# revision identifiers, used by Alembic.
revision: str = "8f1e9b4f9f1b"
down_revision: Union[str, None] = ("20260723_ml_bot_admin_pending", "20260723_tn_publicacion_permiso")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
