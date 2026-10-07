"""Grant the Métricas ML board to the PRICING and VENTAS roles

Revision ID: 20261006_ml_metricas_permisos_pm
Revises: 20261007_ml_publicaciones_vincular_perm
Create Date: 2026-10-06

ODD `metricas-ml-scope-pm` T3: the PMs work from the PRICING and VENTAS roles
(the ones that open the old ML dashboard through `ventas_ml.ver_dashboard`) and
could not open the new board, which was seeded only for ADMIN and GERENTE
(`20261001_ml_metricas_permisos`). They get both permissions -- PMs see the
margins, like the old dashboard -- and the board itself bounds what each one
sees to their own (marca, categoría) pairs. The permissions already exist.

Known limitation (accepted, as in `20261001_ml_metricas_permisos`): the upgrade
is idempotent (`ON CONFLICT DO NOTHING`), so it cannot tell the grants it
created from ones an admin added to PRICING/VENTAS beforehand. The downgrade
removes those two permissions from both roles regardless of who granted them.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20261006_ml_metricas_permisos_pm"
down_revision: Union[str, None] = "20261007_ml_publicaciones_vincular_perm"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

ROL_PERMISOS = {
    "PRICING": ["ml_metricas.ver", "ml_metricas.ver_ganancia"],
    "VENTAS": ["ml_metricas.ver", "ml_metricas.ver_ganancia"],
}

_INSERT_ROL_PERMISO = sa.text("""
    INSERT INTO roles_permisos_base (rol_id, permiso_id)
    SELECT r.id, p.id
    FROM roles r
    CROSS JOIN permisos p
    WHERE r.codigo = :rol_codigo
      AND p.codigo = :permiso_codigo
    ON CONFLICT DO NOTHING
""")

_DELETE_ROL_PERMISO = sa.text("""
    DELETE FROM roles_permisos_base
    WHERE rol_id IN (SELECT id FROM roles WHERE codigo = :rol_codigo)
      AND permiso_id IN (SELECT id FROM permisos WHERE codigo = :permiso_codigo)
""")


def upgrade() -> None:
    conn = op.get_bind()
    for rol, codigos in ROL_PERMISOS.items():
        for codigo in codigos:
            conn.execute(_INSERT_ROL_PERMISO, {"rol_codigo": rol, "permiso_codigo": codigo})


def downgrade() -> None:
    """Remove both permissions from PRICING and VENTAS.

    Accepted limitation: grants that existed before the upgrade are removed
    too, because the migration does not record which rows it inserted.
    """
    conn = op.get_bind()
    for rol, codigos in ROL_PERMISOS.items():
        for codigo in codigos:
            conn.execute(_DELETE_ROL_PERMISO, {"rol_codigo": rol, "permiso_codigo": codigo})
