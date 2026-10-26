"""ml_publicaciones.pausar (pause / activate a publication from Publicaciones ML)

Revision ID: 20261126_ml_publicaciones_pausar_perm
Revises: 20261117_api_docs_permiso
Create Date: 2026-10-26

Gates `POST /api/ml-publications/items/{item_id}/status`, which pauses or activates a publication at
Mercado Libre. Critical: it changes what buyers can see. Granted to ADMIN, same pattern as
`20261117_api_docs_permiso`; SUPERADMIN gets it implicitly, anyone else through a per-user override.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20261126_ml_publicaciones_pausar_perm"
down_revision: Union[str, None] = "20261117_api_docs_permiso"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

PERMISO = {
    "codigo": "ml_publicaciones.pausar",
    "nombre": "Pausar y activar publicaciones ML",
    "descripcion": "Pausar o activar publicaciones en Mercado Libre desde Publicaciones ML.",
    "categoria": "ml_ops",
    "orden": 206,
}

_INSERT_PERMISO = sa.text("""
    INSERT INTO permisos (codigo, nombre, descripcion, categoria, orden, es_critico, created_at)
    VALUES (:codigo, :nombre, :descripcion, :categoria, :orden, true, NOW())
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
