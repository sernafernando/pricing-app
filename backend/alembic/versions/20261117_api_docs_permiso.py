"""admin.ver_api_docs (in-app API docs page)

Revision ID: 20261117_api_docs_permiso
Revises: 20261116_ml_ads_contribution_settlement
Create Date: 2026-10-23

Gates `GET /api/dev/openapi.json` and the frontend `/api-docs` page, which shows every endpoint of the
API. Granted to ADMIN, same pattern as `20261114_ml_ads_contributions_permiso`; SUPERADMIN gets it
implicitly. Developers without ADMIN get it through a per-user override.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20261117_api_docs_permiso"
down_revision: Union[str, None] = "20261116_ml_ads_contribution_settlement"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

PERMISO = {
    "codigo": "admin.ver_api_docs",
    "nombre": "Ver documentación de la API",
    "descripcion": "Ver la lista de endpoints de la API con sus parámetros y respuestas, y probarlos.",
    "categoria": "administracion",
    "orden": 65,
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
