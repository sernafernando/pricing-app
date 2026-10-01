"""ml_ops.resincronizar permission for the per-sale "Resincronizar" action

Revision ID: 20260930_ml_ops_resincronizar
Revises: 20260929_ml_group_metrics_gross_amount
Create Date: 2026-09-30

The sale detail panel can re-fetch one order (and its payments/shipment) from
Mercado Libre and recompute its stored metrics (ODD `ventas-ml-ui-pendiente`
T7, spec `ml-order-resync` R22). That spends Mercado Libre API requests and
rewrites stored money fields, so it gets its OWN permission instead of riding
on `ml_ops.ver` (read) or `ml_ops.gestionar` (divergence bookkeeping).

Granted to ADMIN only, same precedent and rationale as
`20260916_ml_ops_varios_editar_perm.py`: SUPERADMIN short-circuits the
catalog, and GERENTE keeps read via `ml_ops.ver`. Anyone else is granted it
per user through the overrides screen.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20260930_ml_ops_resincronizar"
down_revision: Union[str, None] = "20260929_ml_group_metrics_gross_amount"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

CODIGO = "ml_ops.resincronizar"
PERMISO_NOMBRE = "Resincronizar venta (ventas ML)"
PERMISO_DESCRIPCION = (
    "Volver a traer una venta desde Mercado Libre (orden, pagos y envío) y recalcular "
    "su Costo Gauss desde el panel de detalle. Gasta pedidos a la API de ML."
)
PERMISO_CATEGORIA = "ml_ops"
PERMISO_ORDEN = 204
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
