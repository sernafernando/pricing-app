"""ml_publicaciones.ver_auditoria_stock (Auditoría de stock view in Publicaciones ML)

Revision ID: 20261121_ml_publicaciones_auditoria_stock_perm
Revises: 20261120_tactical_sell_in_usd
Create Date: 2026-11-17

Gates the Auditoría de stock view of Publicaciones ML and its endpoints (stock value per product, ERP + Full,
in USD and ARS). Read-only, so not critical. Granted to ADMIN only; SUPERADMIN gets it implicitly, anyone else
through a per-user override.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20261121_ml_publicaciones_auditoria_stock_perm"
down_revision: Union[str, None] = "20261120_tactical_sell_in_usd"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

PERMISO = {
    "codigo": "ml_publicaciones.ver_auditoria_stock",
    "nombre": "Ver auditoría de stock",
    "descripcion": "Ver la vista Auditoría de stock de Publicaciones ML: stock ERP y Full valorizado en USD y ARS.",
    "categoria": "ml_ops",
    "orden": 209,
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
