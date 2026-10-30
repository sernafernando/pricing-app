"""sell out: the sell_out.repartir permission (split a fixed-total campaign)

Revision ID: 20261216_sell_out_repartir_permiso
Revises: 20261215_sell_in_bono_acumulable
Create Date: 2026-10-29

Sell in / sell out, T26c (S34). A `monto_total` campaign's amount is split by
hand among its products by the PM or an admin. Splitting it
(`sell_out.repartir`) is separate from loading and editing campaigns
(`sell_out.gestionar`), so it can be given to a PM without letting them edit
the campaign; a PM only splits among the products of their own brands (the
API enforces that). Granted to ADMIN and PRICING (the PM role), seeded like
`20261105_sell_out_campanas`. Idempotent; the downgrade removes the grants,
the user overrides and the permission.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20261216_sell_out_repartir_permiso"
down_revision: Union[str, None] = "20261215_sell_in_bono_acumulable"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

CODIGO = "sell_out.repartir"
ROLES = ("ADMIN", "PRICING")

_INSERT_PERMISO = sa.text("""
    INSERT INTO permisos (codigo, nombre, descripcion, categoria, orden, es_critico, created_at)
    VALUES (:codigo, :nombre, :descripcion, 'productos', 84, false, NOW())
    ON CONFLICT (codigo) DO NOTHING
""")

_INSERT_ROL_PERMISO = sa.text("""
    INSERT INTO roles_permisos_base (rol_id, permiso_id)
    SELECT r.id, p.id FROM roles r CROSS JOIN permisos p
    WHERE r.codigo = :rol AND p.codigo = :codigo
    ON CONFLICT DO NOTHING
""")

_DELETES = [
    "DELETE FROM roles_permisos_base WHERE permiso_id IN (SELECT id FROM permisos WHERE codigo = :codigo)",
    "DELETE FROM usuarios_permisos_override WHERE permiso_id IN (SELECT id FROM permisos WHERE codigo = :codigo)",
    "DELETE FROM permisos WHERE codigo = :codigo",
]


def upgrade() -> None:
    conn = op.get_bind()
    conn.execute(
        _INSERT_PERMISO,
        {
            "codigo": CODIGO,
            "nombre": "Repartir campañas de sell out por monto total",
            "descripcion": (
                "Repartir el monto total de una campaña de sell out entre sus productos (% o monto fijo). "
                "Sin gestionar campañas, solo entre los productos de sus marcas."
            ),
        },
    )
    for rol in ROLES:
        conn.execute(_INSERT_ROL_PERMISO, {"rol": rol, "codigo": CODIGO})


def downgrade() -> None:
    conn = op.get_bind()
    for statement in _DELETES:
        conn.execute(sa.text(statement), {"codigo": CODIGO})
