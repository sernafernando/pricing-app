"""ml_publicaciones.vincular permission for the manual product-link endpoints

Revision ID: 20261007_ml_publicaciones_vincular_perm
Revises: 20261006_ml_publications_product_links
Create Date: 2026-10-07

The Mercado Libre publications store links every publication unit to one of our
products by SKU (spec `ml-publicaciones-store`, Domain 6). The operator can fix a
wrong link, link by hand or mark "no product" through the manual-link endpoints;
that overrides what the automatic rule decided, so it gets its OWN permission
instead of riding on `ml_ops.ver` (which only reads links).

Granted to ADMIN only, same precedent and rationale as
`20260930_ml_ops_resincronizar_perm.py`: SUPERADMIN short-circuits the catalog and
anyone else is granted it per user through the overrides screen.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20261007_ml_publicaciones_vincular_perm"
down_revision: Union[str, None] = "20261006_ml_publications_product_links"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

CODIGO = "ml_publicaciones.vincular"
PERMISO_NOMBRE = "Vincular publicaciones ML con productos"
PERMISO_DESCRIPCION = (
    "Vincular a mano una publicación (o una variación) de Mercado Libre con un producto, marcarla "
    "como 'sin producto' o volver a la vinculación automática por SKU."
)
PERMISO_CATEGORIA = "ml_ops"
PERMISO_ORDEN = 205  # 200-204 are taken by the other ml_ops permissions
PERMISO_ES_CRITICO = False

ROL_PERMISOS = {"ADMIN": [CODIGO]}

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
    conn.execute(
        _INSERT_PERMISO,
        {
            "codigo": CODIGO,
            "nombre": PERMISO_NOMBRE,
            "descripcion": PERMISO_DESCRIPCION,
            "categoria": PERMISO_CATEGORIA,
            "orden": PERMISO_ORDEN,
            "es_critico": PERMISO_ES_CRITICO,
        },
    )

    for rol, codigos in ROL_PERMISOS.items():
        for codigo in codigos:
            conn.execute(_INSERT_ROL_PERMISO, {"rol_codigo": rol, "permiso_codigo": codigo})


def downgrade() -> None:
    conn = op.get_bind()

    conn.execute(_DELETE_ROLES_PERMISOS_BASE, {"codigo": CODIGO})
    conn.execute(_DELETE_USUARIOS_PERMISOS_OVERRIDE, {"codigo": CODIGO})
    conn.execute(_DELETE_PERMISO, {"codigo": CODIGO})
