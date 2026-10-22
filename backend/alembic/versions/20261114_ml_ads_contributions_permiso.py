"""ml_metricas.gestionar_aportes_ads (ml-ads-brand-contribution T1b)

Revision ID: 20261114_ml_ads_contributions_permiso
Revises: 20261113_ml_ads_campaign_contributions
Create Date: 2026-10-22

Loading, editing and deleting a brand contribution to an Ads campaign needs this permission on top of
`ml_metricas.ver_ganancia`. Granted to ADMIN only, same pattern as `20261105_sell_out_campanas`.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20261114_ml_ads_contributions_permiso"
down_revision: Union[str, None] = "20261113_ml_ads_campaign_contributions"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

PERMISO = {
    "codigo": "ml_metricas.gestionar_aportes_ads",
    "nombre": "Gestionar aportes de marcas a campañas de Ads",
    "descripcion": "Cargar, editar y borrar el aporte (% o monto fijo) de una marca a una campaña de Product Ads.",
    "categoria": "ventas_ml",
    "orden": 72,
}

_INSERT_PERMISO = sa.text("""
    INSERT INTO permisos (codigo, nombre, descripcion, categoria, orden, es_critico, created_at)
    VALUES (:codigo, :nombre, :descripcion, :categoria, :orden, false, NOW())
    ON CONFLICT (codigo) DO NOTHING
""")

_INSERT_ROL_PERMISO = sa.text("""
    INSERT INTO roles_permisos_base (rol_id, permiso_id)
    SELECT r.id, p.id FROM roles r CROSS JOIN permisos p
    WHERE r.codigo = 'ADMIN' AND p.codigo = :codigo
    ON CONFLICT DO NOTHING
""")

_DELETES = [
    "DELETE FROM roles_permisos_base WHERE permiso_id IN (SELECT id FROM permisos WHERE codigo = :codigo)",
    "DELETE FROM usuarios_permisos_override WHERE permiso_id IN (SELECT id FROM permisos WHERE codigo = :codigo)",
    "DELETE FROM permisos WHERE codigo = :codigo",
]


def upgrade() -> None:
    conn = op.get_bind()
    conn.execute(_INSERT_PERMISO, PERMISO)
    conn.execute(_INSERT_ROL_PERMISO, {"codigo": PERMISO["codigo"]})


def downgrade() -> None:
    conn = op.get_bind()
    for statement in _DELETES:
        conn.execute(sa.text(statement), {"codigo": PERMISO["codigo"]})
