"""gestion_full.ver (open Gestión Full)

Revision ID: 20261106_gestion_full_ver
Revises: 20261105_merge_grupos_ver_ml_ads_soft_delete
Create Date: 2026-11-05

Owner, 2026-11-05: Gestión Full must not depend on Productos but on its own view permission. Until now the screen
and its read endpoints opened with `productos.ver` or `ml_ops.ver`. `gestion_full.ver` replaces both. It is granted
to every role that holds either of them, and to every user with a per-user grant of either, so nobody who opens the
screen today loses it. Depósito / gestor tabs keep `gestion_full.depositos` / `gestion_full.gestor`.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20261106_gestion_full_ver"
down_revision: Union[str, None] = "20261105_merge_grupos_ver_ml_ads_soft_delete"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

PERMISO = {
    "codigo": "gestion_full.ver",
    "nombre": "Gestión Full — ver",
    "descripcion": "Abrir la pantalla Gestión Full (planificación y consulta de envíos a Full).",
    "categoria": "productos",
    "orden": 89,  # before gestion_full.depositos (90) and gestion_full.gestor (91)
}

# The permissions that opened the screen until this revision.
ANTERIORES = ("productos.ver", "ml_ops.ver")

_INSERT_PERMISO = sa.text("""
    INSERT INTO permisos (codigo, nombre, descripcion, categoria, orden, es_critico, created_at)
    VALUES (:codigo, :nombre, :descripcion, :categoria, :orden, false, NOW())
    ON CONFLICT (codigo) DO NOTHING
""")

_GRANT_ROLES = sa.text("""
    INSERT INTO roles_permisos_base (rol_id, permiso_id)
    SELECT DISTINCT b.rol_id, nuevo.id
    FROM roles_permisos_base b
    JOIN permisos anterior ON anterior.id = b.permiso_id AND anterior.codigo IN ('productos.ver', 'ml_ops.ver')
    CROSS JOIN permisos nuevo
    WHERE nuevo.codigo = :codigo
    UNION
    SELECT r.id, nuevo.id FROM roles r CROSS JOIN permisos nuevo
    WHERE r.codigo = 'ADMIN' AND nuevo.codigo = :codigo
    ON CONFLICT DO NOTHING
""")

_GRANT_USERS = sa.text("""
    INSERT INTO usuarios_permisos_override (usuario_id, permiso_id, concedido, motivo, created_at)
    SELECT DISTINCT o.usuario_id, nuevo.id, true, 'gestion_full.ver: tenía acceso a Gestión Full', NOW()
    FROM usuarios_permisos_override o
    JOIN permisos anterior ON anterior.id = o.permiso_id AND anterior.codigo IN ('productos.ver', 'ml_ops.ver')
    CROSS JOIN permisos nuevo
    WHERE nuevo.codigo = :codigo AND o.concedido
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
    conn.execute(_GRANT_ROLES, {"codigo": PERMISO["codigo"]})
    conn.execute(_GRANT_USERS, {"codigo": PERMISO["codigo"]})


def downgrade() -> None:
    conn = op.get_bind()
    for statement in _DELETES:
        conn.execute(sa.text(statement), {"codigo": PERMISO["codigo"]})
