"""grupos.ver (see the Grupos tab of Sell in / Sell out)

Revision ID: 20261105_grupos_ver
Revises: 20261105_tacticals
Create Date: 2026-11-04

Owner: "hoy no existe un permiso para que se vean los grupos, así que solo yo los veo". Until now the Grupos tab
showed only with `config.editar_constantes`, the permission of every group write. `grupos.ver` shows the tab and its
reach (`GET /offset-grupos-alcance`); creating, editing and deleting groups still need `config.editar_constantes`.
Granted to ADMIN, like the other sell-in / sell-out permissions; anyone else through a per-user override.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20261105_grupos_ver"
down_revision: Union[str, None] = "20261105_tacticals"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

PERMISO = {
    "codigo": "grupos.ver",
    "nombre": "Ver grupos de productos",
    "descripcion": "Ver la pestaña Grupos de Sell in / Sell out: los grupos, sus filtros y las campañas que los usan.",
    "categoria": "productos",
    "orden": 92,  # next to the sell-in / sell-out permissions (82-90); 91 is taken
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
