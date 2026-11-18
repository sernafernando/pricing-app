"""ventas por fuera manual costs: `costo_unitario` becomes the unit Precio Costo (owner L3/L4)

Revision ID: 20261124_vpf_override_costo_precio_costo
Revises: 20261123_ml_publicaciones_presets
Create Date: 2026-11-18

Until now a manual cost was stored as the line's Costo D per unit (ModalEditarCosto added VARIOS, the load divided by
COSTO_D_FACTOR: `precio_costo = costo_unitario x cantidad / 1.065`). From now on it is the unit Precio Costo
(`precio_costo = costo_unitario x cantidad`) and the list adds Costo D x 1.065 on top. Rewriting each stored value as
`costo_unitario / 1.065` keeps every fixed line's precio_costo (and so its Costo D) exactly as it is, also when the fix
is re-applied after a re-upload; without it, a fix saved before the deploy would get the 6.5% twice. No-op when there
are no overrides; the lines are not touched (their precio_costo is already right). Downgrade multiplies back.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20261124_vpf_override_costo_precio_costo"
down_revision: Union[str, None] = "20261123_ml_publicaciones_presets"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# COSTO_D_FACTOR at the time of this migration, frozen: a later change of the constant must not rewrite history.
FACTOR = "1.065"
SQL = "UPDATE ventas_fuera_linea_overrides SET costo_unitario = round(costo_unitario {} {}, 6) WHERE costo_unitario IS NOT NULL"


def upgrade() -> None:
    op.get_bind().execute(sa.text(SQL.format("/", FACTOR)))


def downgrade() -> None:
    op.get_bind().execute(sa.text(SQL.format("*", FACTOR)))
