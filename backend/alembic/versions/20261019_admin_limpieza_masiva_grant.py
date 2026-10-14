"""grant admin.limpieza_masiva to every admin.ver_panel holder

Revision ID: 20261019_admin_limpieza_masiva_grant
Revises: 20261018_merge_sale_lines_promo_refresh
Create Date: 2026-10-19

The bulk "limpiar rebate" and "limpiar web transferencia" endpoints are now gated
by `admin.limpieza_masiva`, the catalog code create_permisos_system seeded for
exactly this action but that nothing enforced. Until now the only gate was the
Admin panel route (`admin.ver_panel`, a view permission). To make sure nobody who
can run the cleanup today loses it, every role and every granting user override
that holds `admin.ver_panel` also receives `admin.limpieza_masiva`. An explicit
denial override on `admin.limpieza_masiva` is left as it is.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20261019_admin_limpieza_masiva_grant"
down_revision: Union[str, None] = "20261018_merge_sale_lines_promo_refresh"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

CODIGO = "admin.limpieza_masiva"
CODIGO_VER_PANEL = "admin.ver_panel"

# Same row create_permisos_system seeds; only inserted if it is missing.
_INSERT_PERMISO = sa.text("""
    INSERT INTO permisos (codigo, nombre, descripcion, categoria, orden, es_critico, created_at)
    VALUES (
        :codigo,
        'Limpieza masiva de datos',
        'Ejecutar limpieza masiva de rebate/web transferencia',
        'administracion',
        55,
        true,
        NOW()
    )
    ON CONFLICT (codigo) DO NOTHING
""")

_GRANT_ROLES_WITH_VER_PANEL = sa.text("""
    INSERT INTO roles_permisos_base (rol_id, permiso_id)
    SELECT b.rol_id, lm.id
    FROM roles_permisos_base b
    JOIN permisos vp ON vp.id = b.permiso_id AND vp.codigo = :ver_panel
    CROSS JOIN permisos lm
    WHERE lm.codigo = :codigo
    ON CONFLICT DO NOTHING
""")

_GRANT_OVERRIDES_WITH_VER_PANEL = sa.text("""
    INSERT INTO usuarios_permisos_override (usuario_id, permiso_id, concedido, motivo)
    SELECT o.usuario_id, lm.id, true, 'Migración: limpieza masiva separada de admin.ver_panel'
    FROM usuarios_permisos_override o
    JOIN permisos vp ON vp.id = o.permiso_id AND vp.codigo = :ver_panel
    CROSS JOIN permisos lm
    WHERE lm.codigo = :codigo
      AND o.concedido
    ON CONFLICT DO NOTHING
""")


def upgrade() -> None:
    conn = op.get_bind()
    params = {"codigo": CODIGO, "ver_panel": CODIGO_VER_PANEL}
    conn.execute(_INSERT_PERMISO, params)
    conn.execute(_GRANT_ROLES_WITH_VER_PANEL, params)
    conn.execute(_GRANT_OVERRIDES_WITH_VER_PANEL, params)


def downgrade() -> None:
    # The permission row predates this migration and grants added here cannot be
    # told apart from grants made before or after it, so removing them could take
    # access away from someone who legitimately had it. Nothing to undo.
    pass
