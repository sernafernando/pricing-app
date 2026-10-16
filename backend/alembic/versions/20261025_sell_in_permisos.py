"""sell_in.ver and sell_in.gestionar permissions for the sell-in purchases API

Revision ID: 20261025_sell_in_permisos
Revises: 20261024_sell_in_tables
Create Date: 2026-10-25

Sell in / sell out, T2. Reading the sell-in purchases (`sell_in.ver`) and
loading or voiding them (`sell_in.gestionar`) are separate permissions: a
purchase lowers product cost, so writing one is a pricing decision.

Granted to ADMIN only, same precedent as `20261007_ml_publicaciones_vincular_perm.py`:
SUPERADMIN short-circuits the catalog and anyone else is granted them per user
through the overrides screen.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20261025_sell_in_permisos"
down_revision: Union[str, None] = "20261024_sell_in_tables"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# (codigo, nombre, descripcion, categoria, orden, es_critico)
PERMISOS = [
    (
        "sell_in.ver",
        "Ver compras con sell in",
        "Ver las compras con sell in (descuento de compra), cómo se repartió y cuántas unidades se consumieron.",
        "productos",
        80,
        False,
    ),
    (
        "sell_in.gestionar",
        "Gestionar compras con sell in",
        "Cargar y anular compras con sell in. Bajan el costo de las unidades de esa compra.",
        "productos",
        81,
        False,
    ),
]

ROL_PERMISOS = {"ADMIN": [p[0] for p in PERMISOS]}

_INSERT_PERMISO = sa.text("""
    INSERT INTO permisos (codigo, nombre, descripcion, categoria, orden, es_critico, created_at)
    VALUES (:codigo, :nombre, :descripcion, :categoria, :orden, :es_critico, NOW())
    ON CONFLICT (codigo) DO NOTHING
""")

_INSERT_ROL_PERMISO = sa.text("""
    INSERT INTO roles_permisos_base (rol_id, permiso_id)
    SELECT r.id, p.id
    FROM roles r
    CROSS JOIN permisos p
    WHERE r.codigo = :rol_codigo
      AND p.codigo = :permiso_codigo
    ON CONFLICT DO NOTHING
""")

_DELETE_ROLES_PERMISOS_BASE = sa.text("""
    DELETE FROM roles_permisos_base
    WHERE permiso_id IN (SELECT id FROM permisos WHERE codigo = :codigo)
""")

_DELETE_USUARIOS_PERMISOS_OVERRIDE = sa.text("""
    DELETE FROM usuarios_permisos_override
    WHERE permiso_id IN (SELECT id FROM permisos WHERE codigo = :codigo)
""")

_DELETE_PERMISO = sa.text("DELETE FROM permisos WHERE codigo = :codigo")


def upgrade() -> None:
    conn = op.get_bind()
    for codigo, nombre, descripcion, categoria, orden, es_critico in PERMISOS:
        conn.execute(
            _INSERT_PERMISO,
            {
                "codigo": codigo,
                "nombre": nombre,
                "descripcion": descripcion,
                "categoria": categoria,
                "orden": orden,
                "es_critico": es_critico,
            },
        )

    for rol, codigos in ROL_PERMISOS.items():
        for codigo in codigos:
            conn.execute(_INSERT_ROL_PERMISO, {"rol_codigo": rol, "permiso_codigo": codigo})


def downgrade() -> None:
    conn = op.get_bind()
    for codigo, *_ in PERMISOS:
        conn.execute(_DELETE_ROLES_PERMISOS_BASE, {"codigo": codigo})
        conn.execute(_DELETE_USUARIOS_PERMISOS_OVERRIDE, {"codigo": codigo})
        conn.execute(_DELETE_PERMISO, {"codigo": codigo})
