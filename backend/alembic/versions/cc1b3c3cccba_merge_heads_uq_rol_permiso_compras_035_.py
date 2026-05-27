"""merge heads uq_rol_permiso + compras_035_dinero_a_cuenta

Revision ID: cc1b3c3cccba
Revises: 20260518_uq_rol_permiso, compras_035_dinero_a_cuenta
Create Date: 2026-05-27 11:32:18.203448

"""

from typing import Sequence, Union


# revision identifiers, used by Alembic.
revision: str = "cc1b3c3cccba"
down_revision: Union[str, None] = ("20260518_uq_rol_permiso", "compras_035_dinero_a_cuenta")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
