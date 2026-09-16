"""ml_ops.varios_editar permission for the "% de varios" edit screen

Revision ID: 20260916_ml_ops_varios_editar
Revises: 20260915_costo_fecha
Create Date: 2026-09-16

The "% de varios" history (`VariosVentaPct`) already had a working
backend, but no screen to load it -- so in practice nobody could set it.
Product decision (verbatim): "ponelo en la vista esa con permiso aparte,
que se pueda ver pero no editar sin el permiso". The modal lives in the
ML sales view, gated behind the existing `ml_ops.ver` (read: history is
visible to anyone who can open that view). Writing a new version needs a
SEPARATE, NEW permission -- this migration adds exactly that row, same
shape/precedent as `20260828_ml_operation_links_check_and_permissions.py`.

Granted to ADMIN only (this changes a percentage every sale's breakdown
subtracts -- narrower than `ml_ops.gestionar`, which only touches
divergence bookkeeping). GERENTE keeps read via `ml_ops.ver` but not this
one. SUPERADMIN intentionally absent: `PermisosService.tiene_permiso`/
`obtener_permisos_usuario` short-circuit on `usuario.es_superadmin` before
consulting the catalog, so a catalog row for SUPERADMIN would be dead
data, not a grant (same rationale as the migration above).
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20260916_ml_ops_varios_editar"
down_revision: Union[str, None] = "20260915_costo_fecha"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

CODIGO = "ml_ops.varios_editar"
PERMISO_NOMBRE = "Editar % de varios (ventas ML)"
PERMISO_DESCRIPCION = (
    "Cargar una nueva versión del % de varios que el desglose de ventas ML resta "
    "para llegar al Total Gauss. Sin este permiso el historial es visible pero "
    "no editable."
)
PERMISO_CATEGORIA = "ml_ops"
PERMISO_ORDEN = 203
PERMISO_ES_CRITICO = True

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
